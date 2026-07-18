"""以地图为单位并行、以节点为单位串联的进程内执行器。"""

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Protocol

from app.ai.errors import AiErrorCategory, AiProviderError
from app.workflow.context import (
    AttributeMemoryContext,
    ContextBuilder,
    LocationSimulationContext,
)
from app.workflow.retry import AttemptObserver, AttemptResult
from app.workflow.runtime import (
    MapChainRun,
    NodeKey,
    ProgressEvent,
    RunStatus,
    TurnRun,
    terminal_kind,
)
from app.workflow.schemas import AttributeMemoryAnalysisOutput, LocationSimulationOutput


class MapTaskInvoker(Protocol):
    """执行器只依赖两项固定节点能力，避免携带数据库或 Provider 细节。"""

    async def invoke_location(
        self,
        context: LocationSimulationContext,
        *,
        on_attempt: AttemptObserver | None = None,
    ) -> AttemptResult[LocationSimulationOutput]: ...

    async def invoke_attribute_memory(
        self,
        context: AttributeMemoryContext,
        *,
        on_attempt: AttemptObserver | None = None,
    ) -> AttemptResult[AttributeMemoryAnalysisOutput]: ...


type AttributeContextBuilder = Callable[
    [LocationSimulationContext, LocationSimulationOutput], AttributeMemoryContext
]
type ProgressSink = Callable[[ProgressEvent], Awaitable[None]]
type Clock = Callable[[], float]


_SAFE_AI_ERRORS: dict[AiErrorCategory, str] = {
    AiErrorCategory.INVALID_REQUEST: "AI 请求无效, 请检查模型与任务设置",
    AiErrorCategory.AUTHENTICATION: "AI 认证失败, 请检查 Provider API Key",
    AiErrorCategory.PERMISSION: "AI 权限不足, 请检查模型访问权限",
    AiErrorCategory.INSUFFICIENT_BALANCE: "AI 余额不足, 请检查 Provider 账户",
    AiErrorCategory.RATE_LIMITED: "AI 服务持续限流, 请稍后重试",
    AiErrorCategory.TIMEOUT: "AI 服务多次超时, 请稍后重试或调整任务超时",
    AiErrorCategory.NETWORK: "无法连接 AI 服务, 请检查网络与 Provider 地址",
    AiErrorCategory.UNAVAILABLE: "AI 服务暂不可用, 请稍后重试",
    AiErrorCategory.INVALID_RESPONSE: "AI 返回内容多次无效, 请检查模型能力或任务设置",
    AiErrorCategory.CANCELLED: "AI 任务已取消",
}


def _safe_ai_error(error: AiProviderError) -> str:
    """只按受控分类生成操作提示，绝不转发厂商正文或异常链。"""

    return _SAFE_AI_ERRORS[error.category]


class MapChainExecutor:
    """地图间共享限流并发，单地图只在地点节点成功后才进入属性节点。"""

    def __init__(
        self,
        invoker: MapTaskInvoker,
        *,
        max_provider_calls: int = 3,
        build_attribute_context: AttributeContextBuilder = (
            ContextBuilder.build_attribute_memory_context
        ),
        progress_sink: ProgressSink | None = None,
        clock: Clock = monotonic,
    ) -> None:
        if max_provider_calls < 1:
            raise ValueError("Provider 并发上限必须至少为 1")
        self._invoker = invoker
        self._max_provider_calls = max_provider_calls
        self._build_attribute_context = build_attribute_context
        self._progress_sink = progress_sink
        self._clock = clock

    async def execute(self, run: TurnRun) -> None:
        run.start(self._clock())
        semaphore = asyncio.Semaphore(self._max_provider_calls)
        try:
            async with asyncio.TaskGroup() as tasks:
                for map_run in run.map_runs.values():
                    tasks.create_task(self._execute_map(run, map_run, semaphore))
        except asyncio.CancelledError:
            # TaskGroup 会先取消同组调用；丢弃输出后把取消转为可安全查询的终态。
            run.cancel()
        except BaseException:
            # 原始异常可能包含厂商或网络上下文，运行状态只暴露可操作的安全信息。
            safe_error = next(
                (item.safe_error for item in run.map_runs.values() if item.safe_error is not None),
                "AI 任务执行失败",
            )
            run.fail(safe_error)
        else:
            run.succeed()

    async def emit_terminal(self, run: TurnRun) -> None:
        """由 Manager 在结算结束后发布唯一终态，避免先宣布成功再跳过结算。"""

        await self._emit_terminal_once(run)

    async def _execute_map(
        self,
        run: TurnRun,
        map_run: MapChainRun,
        semaphore: asyncio.Semaphore,
    ) -> None:
        map_run.status = RunStatus.RUNNING
        current_node = NodeKey.LOCATION_SIMULATION
        last_attempt: int | None = None

        async def location_attempt(attempt: int, retrying: bool) -> None:
            nonlocal last_attempt
            last_attempt = attempt
            await self._emit(
                run,
                "node_retrying" if retrying else "node_started",
                map_run.location_id,
                NodeKey.LOCATION_SIMULATION,
                attempt,
                retrying=retrying,
            )

        async def attribute_attempt(attempt: int, retrying: bool) -> None:
            nonlocal last_attempt
            last_attempt = attempt
            await self._emit(
                run,
                "node_retrying" if retrying else "node_started",
                map_run.location_id,
                NodeKey.ATTRIBUTE_MEMORY_ANALYSIS,
                attempt,
                retrying=retrying,
            )

        try:
            async with semaphore:
                location_result = await self._invoker.invoke_location(
                    map_run.location,
                    on_attempt=location_attempt,
                )
            map_run.location_output = location_result.value
            map_run.location_attempt = location_result.attempt
            await self._emit(
                run,
                "node_succeeded",
                map_run.location_id,
                NodeKey.LOCATION_SIMULATION,
                location_result.attempt,
            )
            # 属性上下文构建属于第二节点，失败事件不得沿用地点节点的尝试次数。
            current_node = NodeKey.ATTRIBUTE_MEMORY_ANALYSIS
            last_attempt = None
            map_run.attribute_context = self._build_attribute_context(
                map_run.location,
                location_result.value,
            )
            async with semaphore:
                attribute_result = await self._invoker.invoke_attribute_memory(
                    map_run.attribute_context,
                    on_attempt=attribute_attempt,
                )
            map_run.attribute_output = attribute_result.value
            map_run.attribute_attempt = attribute_result.attempt
            map_run.status = RunStatus.SUCCEEDED
            await self._emit(
                run,
                "map_completed",
                map_run.location_id,
                NodeKey.ATTRIBUTE_MEMORY_ANALYSIS,
                attribute_result.attempt,
            )
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            map_run.status = RunStatus.FAILED
            map_run.failed_node = current_node
            map_run.safe_error = (
                _safe_ai_error(error) if isinstance(error, AiProviderError) else "AI 任务执行失败"
            )
            await self._emit(
                run,
                "node_failed",
                map_run.location_id,
                current_node,
                last_attempt,
                error=map_run.safe_error,
            )
            raise

    async def _emit(
        self,
        run: TurnRun,
        kind: str,
        location_id: str | None,
        node: NodeKey | None,
        attempt: int | None,
        *,
        retrying: bool = False,
        error: str | None = None,
    ) -> None:
        started = run.started_at
        if started is None:
            raise RuntimeError("运行未记录起始时间")
        event = ProgressEvent(
            run_id=run.run_id,
            kind=kind,
            location_id=location_id,
            node=node,
            attempt=attempt,
            max_attempts=3,
            retrying=retrying,
            completed_maps=run.completed_maps,
            total_maps=run.total_maps,
            elapsed_ms=max(0, int((self._clock() - started) * 1000)),
            error=error,
        )
        run.events.append(event)
        if self._progress_sink is not None:
            await self._progress_sink(event)

    async def _emit_terminal_once(self, run: TurnRun) -> None:
        if run.terminal_emitted:
            return
        error = run.error if run.status is RunStatus.FAILED else None
        started = run.started_at
        event = ProgressEvent(
            run_id=run.run_id,
            kind=terminal_kind(run.status),
            location_id=None,
            node=None,
            attempt=None,
            max_attempts=3,
            retrying=False,
            completed_maps=run.completed_maps,
            total_maps=run.total_maps,
            # 未被 stream 领取的 pending 运行也必须产生可订阅的取消终态。
            elapsed_ms=(0 if started is None else max(0, int((self._clock() - started) * 1000))),
            error=error,
        )
        run.events.append(event)
        run.terminal_emitted = True
        if self._progress_sink is None:
            return
        try:
            await self._progress_sink(event)
        except asyncio.CancelledError:
            # 终态只尝试一次；订阅端即使在收到后取消，也不能改写已完成的结算结果。
            return
        except Exception:
            # 查询接口仍能读取安全终态，投递失败不得触发矛盾的第二种终态。
            return
