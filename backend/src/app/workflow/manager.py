"""应用级唯一活动轮次的内存管理与退出清理。"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from app.workflow.context import LocationSimulationContext, TurnContextSnapshot
from app.workflow.executor import MapTaskInvoker
from app.workflow.runtime import RunStatus, TurnRun, TurnRunSummary


class ActiveTurnRunError(RuntimeError):
    """应用已有活动轮次时拒绝创建，避免两轮冻结输入相互覆盖。"""


class FrozenRunInvoker(MapTaskInvoker, Protocol):
    """冻结调用器同时满足两个固定节点的调用协议。"""

    @property
    def memory_max_chars(self) -> int: ...


class RunInvoker(Protocol):
    """运行开始前冻结全部节点配置；运行期间不得再次读取可变设置。"""

    def freeze_for_run(self) -> FrozenRunInvoker: ...


class RunExecutor(Protocol):
    """Manager 只管理运行生命周期，不依赖地图执行器的具体实现。"""

    async def execute(self, run: TurnRun) -> None: ...

    async def emit_terminal(self, run: TurnRun) -> None: ...


type ExecutorFactory = Callable[[FrozenRunInvoker], RunExecutor]
type SettlementHandler = Callable[[TurnRun], Awaitable[int]]


class TurnRunManager:
    """只保留短暂的安全终态，绝不将运行或 AI 输出写入数据库。"""

    def __init__(
        self,
        executor_factory: ExecutorFactory,
        *,
        settlement_handler: SettlementHandler,
    ) -> None:
        self._executor_factory = executor_factory
        self._settlement_handler = settlement_handler
        self._lock = asyncio.Lock()
        self._active_run: TurnRun | None = None
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._terminal_summary: TurnRunSummary | None = None

    @property
    def active_run(self) -> TurnRun | None:
        return self._active_run

    async def start(
        self,
        source: Sequence[LocationSimulationContext] | TurnContextSnapshot,
        invoker: RunInvoker,
    ) -> TurnRun:
        """在活动槽内同步冻结调用器，保证配置保存只能影响之后创建的轮次。"""

        async with self._lock:
            if self._active_run is not None:
                raise ActiveTurnRunError("已有活动轮次")
            # 状态查询只保留最近一次结束轮次；新轮次开始即淘汰旧摘要。
            self._terminal_summary = None
            frozen_invoker = invoker.freeze_for_run()
            frozen_source = source if isinstance(source, TurnContextSnapshot) else tuple(source)
            run = TurnRun.create(
                frozen_source,
                memory_max_chars=frozen_invoker.memory_max_chars,
            )
            self._active_run = run
            self._tasks[run.run_id] = asyncio.create_task(
                self._run(run, self._executor_factory(frozen_invoker))
            )
            return run

    async def wait(self, run_id: str) -> TurnRunSummary:
        task = self._tasks.get(run_id)
        if task is not None:
            await task
        summary = self._terminal_summary
        if summary is not None and summary.run_id == run_id:
            return summary
        raise KeyError("轮次不存在或已过期")

    async def shutdown(self) -> None:
        """进程退出必须协作式取消活动 AI I/O，不能让未结算输出存活。"""

        async with self._lock:
            task = next(iter(self._tasks.values()), None)
        if task is not None:
            task.cancel()
            await task

    async def _run(self, run: TurnRun, executor: RunExecutor) -> None:
        turn_id: int | None = None
        try:
            await executor.execute(run)
            if run.status is RunStatus.SUCCEEDED:
                # 成功输出仍在活动槽内交给结算；结算失败不得让第二轮抢占同一事实快照。
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
                await executor.emit_terminal(run)
            except asyncio.CancelledError:
                # 结算已经结束；终态订阅取消不能倒写世界结果或制造第二种终态。
                pass
            except Exception:
                # 安全摘要仍可查询，投递错误不能阻止 payload 清理与活动槽释放。
                pass
            summary = run.summary(turn_id if run.status is RunStatus.SUCCEEDED else None)
            run.clear_payload()
            async with self._lock:
                self._tasks.pop(run.run_id, None)
                self._terminal_summary = summary
                if self._active_run is run:
                    self._active_run = None
