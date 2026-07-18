"""地图链执行器的并行、串联与丢弃输出回归测试。"""

import asyncio

import pytest

from app.ai.errors import AiErrorCategory, AiProviderError
from app.workflow.context import AttributeMemoryContext, LocationSimulationContext
from app.workflow.executor import MapChainExecutor
from app.workflow.retry import AttemptObserver, AttemptResult
from app.workflow.runtime import NodeKey, ProgressEvent, RunStatus, TurnRun, terminal_kind
from app.workflow.schemas import (
    AttributeMemoryAnalysisOutput,
    InteractionGroupOutput,
    LocationSimulationOutput,
    RoleAttributeMemoryOutput,
    RoleChronicleOutput,
)


def _location(location_id: str) -> LocationSimulationContext:
    return LocationSimulationContext(
        location_id=location_id,
        day=1,
        time_slot="morning",
        player_intent=None,
        roles=(),
    )


def test_terminal_kind_rejects_non_terminal_status() -> None:
    with pytest.raises(ValueError, match="非终态"):
        terminal_kind(RunStatus.RUNNING)


class ControlledInvoker:
    """用 Event 控制节点推进，避免并发测试依赖真实等待。"""

    def __init__(self) -> None:
        self.location_started: dict[str, asyncio.Event] = {}
        self.location_release: dict[str, asyncio.Event] = {}
        self.attribute_started: dict[str, asyncio.Event] = {}
        self.attribute_release: dict[str, asyncio.Event] = {}
        self.location_calls: list[str] = []
        self.attribute_calls: list[str] = []
        self.active_calls = 0
        self.max_active_calls = 0
        self.location_error: dict[str, Exception] = {}
        self.attribute_error: dict[str, Exception] = {}
        self.location_attempts: dict[str, tuple[int, ...]] = {}

    def _event(self, values: dict[str, asyncio.Event], location_id: str) -> asyncio.Event:
        return values.setdefault(location_id, asyncio.Event())

    def location_started_event(self, location_id: str) -> asyncio.Event:
        return self._event(self.location_started, location_id)

    def attribute_started_event(self, location_id: str) -> asyncio.Event:
        return self._event(self.attribute_started, location_id)

    async def invoke_location(
        self,
        context: LocationSimulationContext,
        *,
        on_attempt: AttemptObserver | None = None,
    ) -> AttemptResult[LocationSimulationOutput]:
        attempts = self.location_attempts.get(context.location_id, (1,))
        if on_attempt is not None:
            for attempt in attempts:
                await on_attempt(attempt, attempt > 1)
        self.location_calls.append(context.location_id)
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self._event(self.location_started, context.location_id).set()
        await self._event(self.location_release, context.location_id).wait()
        self.active_calls -= 1
        if error := self.location_error.get(context.location_id):
            raise error
        return AttemptResult(value=_location_output(context.location_id), attempt=attempts[-1])

    async def invoke_attribute_memory(
        self,
        context: AttributeMemoryContext,
        *,
        on_attempt: AttemptObserver | None = None,
    ) -> AttemptResult[AttributeMemoryAnalysisOutput]:
        location_id = context.location_id
        if on_attempt is not None:
            await on_attempt(1, False)
        self.attribute_calls.append(location_id)
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self._event(self.attribute_started, location_id).set()
        await self._event(self.attribute_release, location_id).wait()
        self.active_calls -= 1
        if error := self.attribute_error.get(location_id):
            raise error
        return AttemptResult(value=_attribute_output(location_id), attempt=1)


def _location_output(location_id: str) -> LocationSimulationOutput:
    return LocationSimulationOutput(
        location_id=location_id,
        groups=[InteractionGroupOutput(group_id="group", role_ids=[1])],
        events=[],
        chronicles=[RoleChronicleOutput(role_id=1, content="地点完成", known_event_keys=[])],
    )


def _attribute_output(location_id: str) -> AttributeMemoryAnalysisOutput:
    return AttributeMemoryAnalysisOutput(
        location_id=location_id,
        roles=[
            RoleAttributeMemoryOutput(
                role_id=1,
                attribute_update_intents=[],
                memory_append="属性完成",
            )
        ],
    )


def _attribute_context(
    location: LocationSimulationContext,
    output: LocationSimulationOutput,
) -> AttributeMemoryContext:
    assert output.location_id == location.location_id
    return AttributeMemoryContext(location_id=location.location_id, groups=(), roles=())


async def _wait(event: asyncio.Event) -> None:
    await asyncio.wait_for(event.wait(), timeout=1)


@pytest.mark.asyncio
async def test_each_map_runs_attribute_only_after_its_own_location_completes() -> None:
    invoker = ControlledInvoker()
    executor = MapChainExecutor(invoker, build_attribute_context=_attribute_context)
    run = TurnRun.create((_location("home"),))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    assert invoker.attribute_calls == []
    invoker.location_release["home"].set()
    await _wait(invoker.attribute_started_event("home"))
    invoker.attribute_release["home"].set()
    await task

    assert run.status is RunStatus.SUCCEEDED
    assert invoker.location_calls == ["home"]
    assert invoker.attribute_calls == ["home"]


@pytest.mark.asyncio
async def test_maps_overlap_but_shared_semaphore_limits_provider_calls() -> None:
    invoker = ControlledInvoker()
    executor = MapChainExecutor(
        invoker,
        max_provider_calls=2,
        build_attribute_context=_attribute_context,
    )
    run = TurnRun.create((_location("home"), _location("school"), _location("guild")))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    await _wait(invoker.location_started_event("school"))
    assert "guild" not in invoker.location_started
    invoker.location_release["home"].set()
    await _wait(invoker.location_started_event("guild"))
    invoker.location_release["school"].set()
    invoker.location_release["guild"].set()
    await _wait(invoker.attribute_started_event("home"))
    await _wait(invoker.attribute_started_event("school"))
    invoker.attribute_release["home"].set()
    await _wait(invoker.attribute_started_event("guild"))
    for event in invoker.attribute_release.values():
        event.set()
    await task

    assert invoker.max_active_calls <= 2
    assert run.status is RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_location_failure_skips_its_attribute_and_discards_all_outputs() -> None:
    invoker = ControlledInvoker()
    invoker.location_error["home"] = RuntimeError("provider failed")
    executor = MapChainExecutor(invoker, build_attribute_context=_attribute_context)
    run = TurnRun.create((_location("home"),))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    invoker.location_release["home"].set()
    await task

    assert run.status is RunStatus.FAILED
    assert invoker.attribute_calls == []
    assert run.map_runs["home"].location_output is None
    assert run.map_runs["home"].attribute_output is None
    assert run.map_runs["home"].failed_node is NodeKey.LOCATION_SIMULATION
    assert run.map_runs["home"].safe_error == "AI 任务执行失败"
    failure = next(event for event in run.events if event.kind == "node_failed")
    assert (failure.location_id, failure.node, failure.attempt) == (
        "home",
        NodeKey.LOCATION_SIMULATION,
        1,
    )


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (AiErrorCategory.AUTHENTICATION, "AI 认证失败, 请检查 Provider API Key"),
        (AiErrorCategory.NETWORK, "无法连接 AI 服务, 请检查网络与 Provider 地址"),
        (AiErrorCategory.INVALID_RESPONSE, "AI 返回内容多次无效, 请检查模型能力或任务设置"),
    ],
)
async def test_known_provider_failures_expose_actionable_safe_errors(
    category: AiErrorCategory,
    expected: str,
) -> None:
    invoker = ControlledInvoker()
    invoker.location_error["home"] = AiProviderError(
        category=category,
        message="Authorization: Bearer secret-provider-key",
        retryable=category is not AiErrorCategory.AUTHENTICATION,
    )
    executor = MapChainExecutor(invoker, build_attribute_context=_attribute_context)
    run = TurnRun.create((_location("home"),))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    invoker.location_release["home"].set()
    await task

    assert run.status is RunStatus.FAILED
    assert run.error == expected
    assert run.map_runs["home"].safe_error == expected
    assert "secret-provider-key" not in " ".join(event.error or "" for event in run.events)


@pytest.mark.asyncio
async def test_progress_exposes_each_attempt_and_retry_flag_from_invoker() -> None:
    invoker = ControlledInvoker()
    invoker.location_attempts["home"] = (1, 2)
    executor = MapChainExecutor(invoker, build_attribute_context=_attribute_context)
    run = TurnRun.create((_location("home"),))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    invoker.location_release["home"].set()
    await _wait(invoker.attribute_started_event("home"))
    invoker.attribute_release["home"].set()
    await task

    attempts = [
        (event.attempt, event.retrying)
        for event in run.events
        if event.location_id == "home" and event.node is NodeKey.LOCATION_SIMULATION
    ]
    assert attempts == [(1, False), (2, True), (2, False)]


@pytest.mark.asyncio
async def test_attribute_failure_does_not_repeat_successful_location() -> None:
    invoker = ControlledInvoker()
    invoker.attribute_error["home"] = RuntimeError("attribute failed")
    executor = MapChainExecutor(invoker, build_attribute_context=_attribute_context)
    run = TurnRun.create((_location("home"),))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    invoker.location_release["home"].set()
    await _wait(invoker.attribute_started_event("home"))
    invoker.attribute_release["home"].set()
    await task

    assert invoker.location_calls == ["home"]
    assert invoker.attribute_calls == ["home"]
    assert run.status is RunStatus.FAILED
    assert run.map_runs["home"].failed_node is NodeKey.ATTRIBUTE_MEMORY_ANALYSIS
    failure = next(event for event in run.events if event.kind == "node_failed")
    assert failure.attempt == 1


@pytest.mark.asyncio
async def test_attribute_context_failure_uses_attribute_node_without_location_attempt() -> None:
    invoker = ControlledInvoker()

    def fail_to_build_attribute_context(
        _location: LocationSimulationContext,
        _output: LocationSimulationOutput,
    ) -> AttributeMemoryContext:
        raise RuntimeError("上下文构建失败")

    executor = MapChainExecutor(invoker, build_attribute_context=fail_to_build_attribute_context)
    run = TurnRun.create((_location("home"),))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    invoker.location_release["home"].set()
    await task

    failure = next(event for event in run.events if event.kind == "node_failed")
    assert (failure.node, failure.attempt) == (NodeKey.ATTRIBUTE_MEMORY_ANALYSIS, None)


@pytest.mark.asyncio
async def test_terminal_sink_error_does_not_interrupt_successful_run() -> None:
    invoker = ControlledInvoker()

    async def failing_terminal_sink(event: ProgressEvent) -> None:
        if event.kind == "run_succeeded":
            raise RuntimeError("客户端已断开")

    executor = MapChainExecutor(
        invoker,
        build_attribute_context=_attribute_context,
        progress_sink=failing_terminal_sink,
    )
    run = TurnRun.create((_location("home"),))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    invoker.location_release["home"].set()
    await _wait(invoker.attribute_started_event("home"))
    invoker.attribute_release["home"].set()
    await task
    await executor.emit_terminal(run)

    assert run.status is RunStatus.SUCCEEDED
    assert run.terminal_emitted is True
    assert [event.kind for event in run.events if event.kind.startswith("run_")] == [
        "run_succeeded"
    ]


@pytest.mark.asyncio
async def test_terminal_sink_cancellation_never_rewrites_or_repeats_success() -> None:
    invoker = ControlledInvoker()
    delivered: list[str] = []

    async def cancelling_terminal_sink(event: ProgressEvent) -> None:
        if event.kind == "run_succeeded":
            delivered.append(event.kind)
            raise asyncio.CancelledError

    executor = MapChainExecutor(
        invoker,
        build_attribute_context=_attribute_context,
        progress_sink=cancelling_terminal_sink,
    )
    run = TurnRun.create((_location("home"),))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    invoker.location_release["home"].set()
    await _wait(invoker.attribute_started_event("home"))
    invoker.attribute_release["home"].set()
    await task
    await executor.emit_terminal(run)
    await executor.emit_terminal(run)

    assert run.status is RunStatus.SUCCEEDED
    assert run.terminal_emitted is True
    assert delivered == ["run_succeeded"]
    assert [event.kind for event in run.events if event.kind.startswith("run_")] == [
        "run_succeeded"
    ]


@pytest.mark.asyncio
async def test_cancellation_cooperatively_cancels_inflight_calls_and_discards_outputs() -> None:
    invoker = ControlledInvoker()
    executor = MapChainExecutor(invoker, build_attribute_context=_attribute_context)
    run = TurnRun.create((_location("home"), _location("school")))
    task = asyncio.create_task(executor.execute(run))

    await _wait(invoker.location_started_event("home"))
    await _wait(invoker.location_started_event("school"))
    task.cancel()
    await task
    await executor.emit_terminal(run)

    assert run.status is RunStatus.CANCELLED
    assert all(item.location_output is None for item in run.map_runs.values())
    assert [event.kind for event in run.events if event.kind.startswith("run_")] == [
        "run_cancelled"
    ]
