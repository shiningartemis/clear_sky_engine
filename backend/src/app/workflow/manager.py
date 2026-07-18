"""应用级唯一活动轮次的内存管理、领取、取消与退出清理。"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.workflow.context import LocationSimulationContext, TurnContextSnapshot
from app.workflow.executor import MapTaskInvoker, ProgressSink
from app.workflow.runtime import ProgressEvent, RunStatus, TurnRun, TurnRunSummary


class ActiveTurnRunError(RuntimeError):
    """应用已有活动轮次时拒绝创建，避免两轮冻结输入相互覆盖。"""


class TurnRunAlreadyClaimedError(RuntimeError):
    """一个运行只允许由首次流连接领取，避免重复执行或多订阅者竞态。"""


class FrozenRunInvoker(MapTaskInvoker, Protocol):
    """冻结调用器同时满足两个固定节点的调用协议。"""

    @property
    def memory_max_chars(self) -> int: ...


class RunInvoker(Protocol):
    """运行创建时冻结全部节点配置；运行期间不得再次读取可变设置。"""

    def freeze_for_run(self) -> FrozenRunInvoker: ...


class RunExecutor(Protocol):
    """Manager 只管理运行生命周期，不依赖地图执行器的具体实现。"""

    async def execute(self, run: TurnRun) -> None: ...

    async def emit_terminal(self, run: TurnRun) -> None: ...


type ExecutorFactory = Callable[[FrozenRunInvoker, ProgressSink], RunExecutor]
type SettlementHandler = Callable[[TurnRun], Awaitable[int]]
type ClaimTimeoutWaiter = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class TurnRunSubscription:
    """首次 stream 领取后获得的单消费者事件入口。"""

    run_id: str
    _queue: asyncio.Queue[ProgressEvent]

    async def receive(self) -> ProgressEvent:
        return await self._queue.get()


@dataclass
class _ManagedRun:
    run: TurnRun
    executor: RunExecutor
    queue: asyncio.Queue[ProgressEvent]
    claimed: bool = False
    execution_task: asyncio.Task[None] | None = None
    claim_timeout_task: asyncio.Task[None] | None = None
    done: asyncio.Event | None = None

    def completion_event(self) -> asyncio.Event:
        if self.done is None:
            self.done = asyncio.Event()
        return self.done


class TurnRunManager:
    """运行只在首次流连接后执行，并只短暂保留安全终态摘要。"""

    def __init__(
        self,
        executor_factory: ExecutorFactory,
        *,
        settlement_handler: SettlementHandler,
        claim_timeout_seconds: float = 10,
        wait_for_claim_timeout: ClaimTimeoutWaiter = asyncio.sleep,
    ) -> None:
        if claim_timeout_seconds <= 0:
            raise ValueError("领取超时必须大于 0")
        self._executor_factory = executor_factory
        self._settlement_handler = settlement_handler
        self._claim_timeout_seconds = claim_timeout_seconds
        self._wait_for_claim_timeout = wait_for_claim_timeout
        self._lock = asyncio.Lock()
        self._active: _ManagedRun | None = None
        self._terminal_summary: TurnRunSummary | None = None

    @property
    def active_run(self) -> TurnRun | None:
        return self._active.run if self._active is not None else None

    async def create(
        self,
        source: Sequence[LocationSimulationContext] | TurnContextSnapshot,
        invoker: RunInvoker,
    ) -> TurnRun:
        """占用唯一活动槽并冻结配置，但在 stream 领取前绝不启动 AI。"""

        async with self._lock:
            if self._active is not None:
                raise ActiveTurnRunError("已有活动轮次")
            frozen_invoker = invoker.freeze_for_run()
            frozen_source = source if isinstance(source, TurnContextSnapshot) else tuple(source)
            run = TurnRun.create(
                frozen_source,
                memory_max_chars=frozen_invoker.memory_max_chars,
            )
            queue = asyncio.Queue[ProgressEvent]()

            async def publish(event: ProgressEvent) -> None:
                await queue.put(event)

            managed = _ManagedRun(
                run=run,
                executor=self._executor_factory(frozen_invoker, publish),
                queue=queue,
            )
            # 新运行创建即淘汰上一安全摘要；run_id 从不形成进程内无界历史。
            self._terminal_summary = None
            self._active = managed
            managed.claim_timeout_task = asyncio.create_task(self._expire_unclaimed(managed))
            return run

    async def get(self, run_id: str) -> TurnRunSummary:
        async with self._lock:
            managed = self._active
            if managed is not None and managed.run.run_id == run_id:
                summary = managed.run.summary()
                if summary.status is RunStatus.SUCCEEDED:
                    # 执行器成功后仍需原子结算；提交前不能向查询端宣布成功。
                    return TurnRunSummary(
                        run_id=summary.run_id,
                        status=RunStatus.RUNNING,
                        turn_id=None,
                        error=None,
                    )
                return summary
            summary = self._terminal_summary
            if summary is not None and summary.run_id == run_id:
                return summary
        raise KeyError("轮次不存在或已过期")

    async def claim(self, run_id: str) -> TurnRunSubscription:
        """首次流连接原子领取运行；失败连接不得触发第二次执行。"""

        async with self._lock:
            managed = self._required_active(run_id)
            if managed.claimed:
                raise TurnRunAlreadyClaimedError("轮次已被领取")
            managed.claimed = True
            timeout_task = managed.claim_timeout_task
            if timeout_task is not None:
                timeout_task.cancel()
            managed.execution_task = asyncio.create_task(self._run(managed))
            return TurnRunSubscription(run_id=run_id, _queue=managed.queue)

    async def cancel(self, run_id: str) -> TurnRunSummary:
        """幂等取消 pending 或 running 运行，并等待临时结果彻底清理。"""

        async with self._lock:
            summary = self._terminal_summary
            if summary is not None and summary.run_id == run_id:
                return summary
            managed = self._required_active(run_id)
            done = managed.completion_event()
            task = managed.execution_task
            if task is None:
                managed.claimed = True
                if managed.claim_timeout_task is not None:
                    managed.claim_timeout_task.cancel()
                managed.run.cancel()
                task = asyncio.create_task(self._finish_pending_cancellation(managed))
                managed.execution_task = task
            elif (
                managed.run.status
                in {
                    RunStatus.PENDING,
                    RunStatus.RUNNING,
                    RunStatus.SUCCEEDED,
                }
                and not task.done()
            ):
                task.cancel()

        if task is not asyncio.current_task():
            try:
                await task
            except asyncio.CancelledError:
                # create_task 后尚未获得首个执行片段就取消时，_run 的 finally 不会运行。
                if managed.run.status is RunStatus.PENDING:
                    managed.run.cancel()
                    await self._finish_pending_cancellation(managed)
        await done.wait()
        return await self.get(run_id)

    async def wait(self, run_id: str) -> TurnRunSummary:
        async with self._lock:
            summary = self._terminal_summary
            if summary is not None and summary.run_id == run_id:
                return summary
            managed = self._required_active(run_id)
            done = managed.completion_event()
        await done.wait()
        return await self.get(run_id)

    async def shutdown(self) -> None:
        """应用退出必须取消 pending/running AI I/O，并等待活动槽释放。"""

        async with self._lock:
            run_id = self._active.run.run_id if self._active is not None else None
        if run_id is not None:
            await self.cancel(run_id)

    def _required_active(self, run_id: str) -> _ManagedRun:
        managed = self._active
        if managed is None or managed.run.run_id != run_id:
            raise KeyError("轮次不存在或已过期")
        return managed

    async def _expire_unclaimed(self, managed: _ManagedRun) -> None:
        try:
            await self._wait_for_claim_timeout(self._claim_timeout_seconds)
        except asyncio.CancelledError:
            return
        async with self._lock:
            if self._active is not managed or managed.claimed:
                return
            managed.claimed = True
            managed.run.cancel()
            managed.execution_task = asyncio.current_task()
        await self._finish_pending_cancellation(managed)

    async def _finish_pending_cancellation(self, managed: _ManagedRun) -> None:
        try:
            await managed.executor.emit_terminal(managed.run)
        except asyncio.CancelledError:
            # pending 取消仍必须完成摘要清理；终态投递中断不恢复运行。
            pass
        except Exception:
            pass
        await self._finalize(managed, turn_id=None)

    async def _run(self, managed: _ManagedRun) -> None:
        run = managed.run
        turn_id: int | None = None
        try:
            await managed.executor.execute(run)
            if run.status is RunStatus.SUCCEEDED:
                try:
                    turn_id = await self._settlement_handler(run)
                except asyncio.CancelledError:
                    raise
                except BaseException:
                    run.fail("轮次结算失败")
        except asyncio.CancelledError:
            run.cancel()
        except BaseException:
            run.fail("AI 任务执行失败")
        finally:
            if run.status is RunStatus.PENDING or run.status is RunStatus.RUNNING:
                run.fail("AI 任务执行失败")
            try:
                await managed.executor.emit_terminal(run)
            except asyncio.CancelledError:
                # 结算已经结束；订阅取消不能倒写世界结果或制造第二种终态。
                pass
            except Exception:
                pass
            await self._finalize(
                managed,
                turn_id if run.status is RunStatus.SUCCEEDED else None,
            )

    async def _finalize(self, managed: _ManagedRun, turn_id: int | None) -> None:
        run = managed.run
        summary = run.summary(turn_id)
        run.clear_payload()
        async with self._lock:
            if self._active is managed:
                self._terminal_summary = summary
                self._active = None
            managed.completion_event().set()
