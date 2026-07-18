"""进程内运行管理器的唯一活动槽与配置冻结测试。"""

import asyncio

import pytest

from app.workflow.context import AttributeMemoryContext, LocationSimulationContext
from app.workflow.manager import ActiveTurnRunError, FrozenRunInvoker, TurnRunManager
from app.workflow.retry import AttemptObserver, AttemptResult
from app.workflow.runtime import RunStatus, TurnRun
from app.workflow.schemas import AttributeMemoryAnalysisOutput, LocationSimulationOutput


async def _settle(_run: TurnRun) -> int:
    return 1


class FrozenInvoker:
    def __init__(self, version: int) -> None:
        self.version = version
        self.memory_max_chars = 50

    async def invoke_location(
        self,
        context: LocationSimulationContext,
        *,
        on_attempt: AttemptObserver | None = None,
    ) -> AttemptResult[LocationSimulationOutput]:
        raise RuntimeError("测试执行器不会调用节点")

    async def invoke_attribute_memory(
        self,
        context: AttributeMemoryContext,
        *,
        on_attempt: AttemptObserver | None = None,
    ) -> AttemptResult[AttributeMemoryAnalysisOutput]:
        raise RuntimeError("测试执行器不会调用节点")


class VersionedInvoker:
    def __init__(self) -> None:
        self.version = 1
        self.freeze_calls: list[int] = []

    def freeze_for_run(self) -> FrozenInvoker:
        self.freeze_calls.append(self.version)
        return FrozenInvoker(self.version)


class BlockingExecutor:
    def __init__(self, invoker: FrozenInvoker, gate: asyncio.Event) -> None:
        self.version = invoker.version
        self.gate = gate
        self.started = asyncio.Event()

    async def execute(self, run: TurnRun) -> None:
        self.started.set()
        await self.gate.wait()
        run.status = RunStatus.SUCCEEDED

    async def emit_terminal(self, run: TurnRun) -> None:
        return None


async def test_manager_rejects_second_active_run_and_releases_slot_after_completion() -> None:
    gate = asyncio.Event()
    executors: list[BlockingExecutor] = []

    def factory(invoker: FrozenRunInvoker) -> BlockingExecutor:
        assert isinstance(invoker, FrozenInvoker)
        executor = BlockingExecutor(invoker, gate)
        executors.append(executor)
        return executor

    manager = TurnRunManager(factory, settlement_handler=_settle)
    first = await manager.start((), VersionedInvoker())
    await asyncio.wait_for(executors[0].started.wait(), timeout=1)
    assert first.memory_max_chars == 50

    with pytest.raises(ActiveTurnRunError):
        await manager.start((), VersionedInvoker())
    gate.set()
    await manager.wait(first.run_id)

    assert manager.active_run is None
    assert first.status is RunStatus.SUCCEEDED


async def test_manager_freezes_configuration_for_each_new_run() -> None:
    gates = [asyncio.Event(), asyncio.Event()]
    executors: list[BlockingExecutor] = []

    def factory(invoker: FrozenRunInvoker) -> BlockingExecutor:
        assert isinstance(invoker, FrozenInvoker)
        executor = BlockingExecutor(invoker, gates[len(executors)])
        executors.append(executor)
        return executor

    source = VersionedInvoker()
    manager = TurnRunManager(factory, settlement_handler=_settle)
    first = await manager.start((), source)
    await asyncio.wait_for(executors[0].started.wait(), timeout=1)
    source.version = 2
    gates[0].set()
    await manager.wait(first.run_id)
    second = await manager.start((), source)
    await asyncio.wait_for(executors[1].started.wait(), timeout=1)
    gates[1].set()
    await manager.wait(second.run_id)

    assert source.freeze_calls == [1, 2]
    assert [executor.version for executor in executors] == [1, 2]


async def test_manager_shutdown_cancels_the_active_run() -> None:
    gate = asyncio.Event()
    executors: list[BlockingExecutor] = []

    def factory(invoker: FrozenRunInvoker) -> BlockingExecutor:
        assert isinstance(invoker, FrozenInvoker)
        executor = BlockingExecutor(invoker, gate)
        executors.append(executor)
        return executor

    manager = TurnRunManager(factory, settlement_handler=_settle)
    run = await manager.start((), VersionedInvoker())
    await asyncio.wait_for(executors[0].started.wait(), timeout=1)
    await manager.shutdown()

    assert run.status is RunStatus.CANCELLED
    assert manager.active_run is None


async def test_manager_keeps_slot_until_settlement_and_only_retains_safe_summary() -> None:
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def settle(_run: TurnRun) -> int:
        entered.set()
        await gate.wait()
        return 42

    manager = TurnRunManager(lambda _invoker: CompletingExecutor(), settlement_handler=settle)
    first = await manager.start((), VersionedInvoker())
    await entered.wait()

    with pytest.raises(ActiveTurnRunError):
        await manager.start((), VersionedInvoker())
    gate.set()
    summary = await manager.wait(first.run_id)

    assert summary.turn_id == 42
    assert not hasattr(summary, "map_runs")
    assert first.map_runs == {}
    second = await manager.start((), VersionedInvoker())
    with pytest.raises(KeyError):
        await manager.wait(first.run_id)
    await manager.wait(second.run_id)


async def test_manager_marks_a_successful_run_failed_when_settlement_rejects_it() -> None:
    async def fail_settlement(_run: TurnRun) -> int:
        raise RuntimeError("结算冲突")

    manager = TurnRunManager(
        lambda _invoker: CompletingExecutor(),
        settlement_handler=fail_settlement,
    )
    run = await manager.start((), VersionedInvoker())
    summary = await manager.wait(run.run_id)

    assert run.status is RunStatus.FAILED
    assert summary.status is RunStatus.FAILED
    assert summary.turn_id is None
    assert summary.error == "轮次结算失败"


async def test_manager_emits_one_success_terminal_only_after_settlement() -> None:
    timeline: list[str] = []

    async def settle(_run: TurnRun) -> int:
        timeline.append("settlement")
        return 9

    manager = TurnRunManager(
        lambda _invoker: TerminalRecordingExecutor(timeline),
        settlement_handler=settle,
    )
    run = await manager.start((), VersionedInvoker())
    summary = await manager.wait(run.run_id)

    assert summary.status is RunStatus.SUCCEEDED
    assert timeline == ["execute", "settlement", "terminal"]


class TerminalRecordingExecutor:
    def __init__(self, timeline: list[str]) -> None:
        self._timeline = timeline

    async def execute(self, run: TurnRun) -> None:
        self._timeline.append("execute")
        run.start()
        run.succeed()

    async def emit_terminal(self, run: TurnRun) -> None:
        self._timeline.append("terminal")
        run.terminal_emitted = True


class CompletingExecutor:
    async def execute(self, run: TurnRun) -> None:
        run.start()
        run.succeed()

    async def emit_terminal(self, run: TurnRun) -> None:
        return None
