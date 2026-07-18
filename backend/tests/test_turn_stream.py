"""轮次运行领取、流订阅和取消生命周期测试。"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from starlette.requests import ClientDisconnect
from starlette.types import Message, Scope

from app.api.turns import NdjsonStreamingResponse, create_turn_router, stream_turn_run_events
from app.character.models import Role
from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_session_factory, create_sqlite_engine
from app.story.models import Turn
from app.story.service import SettlementService, TurnHistoryRecord, TurnRoleHistoryRecord
from app.workflow.context import (
    AttributeMemoryContext,
    LocationSimulationContext,
    TurnContextSnapshot,
)
from app.workflow.executor import ProgressSink
from app.workflow.manager import FrozenRunInvoker, TurnRunManager
from app.workflow.retry import AttemptObserver, AttemptResult
from app.workflow.runtime import ProgressEvent, RunStatus, TurnRun
from app.workflow.schemas import AttributeMemoryAnalysisOutput, LocationSimulationOutput
from app.world.models import World, WorldBranch, WorldRoleMemory, WorldRoleState


async def _settle(_run: TurnRun) -> int:
    return 1


class FrozenInvoker:
    memory_max_chars = 50

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


class Invoker:
    def freeze_for_run(self) -> FrozenInvoker:
        return FrozenInvoker()


class RecordingExecutor:
    def __init__(
        self,
        _invoker: FrozenRunInvoker,
        progress_sink: ProgressSink,
    ) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self._progress_sink = progress_sink

    async def execute(self, run: TurnRun) -> None:
        run.start()
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        run.succeed()

    async def emit_terminal(self, run: TurnRun) -> None:
        event = ProgressEvent(
            run_id=run.run_id,
            kind={
                RunStatus.SUCCEEDED: "run_succeeded",
                RunStatus.FAILED: "run_failed",
                RunStatus.CANCELLED: "run_cancelled",
            }[run.status],
            location_id=None,
            node=None,
            attempt=None,
            max_attempts=3,
            retrying=False,
            completed_maps=0,
            total_maps=0,
            elapsed_ms=0,
            error=run.error if run.status is RunStatus.FAILED else None,
        )
        run.terminal_emitted = True
        await self._progress_sink(event)


class StreamingExecutor(RecordingExecutor):
    async def execute(self, run: TurnRun) -> None:
        run.start()
        self.started.set()
        await self._progress_sink(
            ProgressEvent(
                run_id=run.run_id,
                kind="node_started",
                location_id="the_home",
                node=None,
                attempt=1,
                max_attempts=3,
                retrying=False,
                completed_maps=0,
                total_maps=1,
                elapsed_ms=5,
            )
        )
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        run.succeed()


class FailingExecutor(RecordingExecutor):
    async def execute(self, run: TurnRun) -> None:
        run.start()
        raise RuntimeError("Authorization: Bearer secret-provider-key")


class CompletingStreamingExecutor(StreamingExecutor):
    async def execute(self, run: TurnRun) -> None:
        run.start()
        await self._progress_sink(
            ProgressEvent(
                run_id=run.run_id,
                kind="node_started",
                location_id="the_home",
                node=None,
                attempt=1,
                max_attempts=3,
                retrying=False,
                completed_maps=0,
                total_maps=1,
                elapsed_ms=1,
            )
        )
        run.succeed()


class HistorySource:
    def list_history(self, *, world_id: int) -> tuple[TurnHistoryRecord, ...]:
        raise RuntimeError(f"流测试不会按世界读取历史: {world_id}")

    def get_turn(self, turn_id: int) -> TurnHistoryRecord:
        assert turn_id == 9
        return TurnHistoryRecord(
            turn_id=9,
            day=1,
            time_slot="morning",
            player_intent="去学校",
            roles=(TurnRoleHistoryRecord(role_id=1, content="天出发了。", offline=False),),
            events=(),
            state_changes=(),
        )


async def test_create_keeps_run_pending_until_first_stream_claim() -> None:
    executors: list[RecordingExecutor] = []

    def factory(invoker: FrozenRunInvoker, progress_sink: ProgressSink) -> RecordingExecutor:
        executor = RecordingExecutor(invoker, progress_sink)
        executors.append(executor)
        return executor

    manager = TurnRunManager(factory, settlement_handler=_settle)

    run = await manager.create((), Invoker())

    assert run.status is RunStatus.PENDING
    assert not executors[0].started.is_set()
    subscription = await manager.claim(run.run_id)
    await asyncio.wait_for(executors[0].started.wait(), timeout=1)
    executors[0].release.set()
    terminal = await asyncio.wait_for(subscription.receive(), timeout=1)
    assert terminal.kind == "run_succeeded"
    await manager.wait(run.run_id)


@pytest.mark.parametrize("disconnect_after_claim", [False, True])
async def test_cancel_is_idempotent_for_pending_and_running_runs(
    disconnect_after_claim: bool,
) -> None:
    executors: list[RecordingExecutor] = []

    def factory(invoker: FrozenRunInvoker, progress_sink: ProgressSink) -> RecordingExecutor:
        executor = RecordingExecutor(invoker, progress_sink)
        executors.append(executor)
        return executor

    manager = TurnRunManager(factory, settlement_handler=_settle)
    run = await manager.create((), Invoker())
    subscription = await manager.claim(run.run_id) if disconnect_after_claim else None
    if disconnect_after_claim:
        await asyncio.wait_for(executors[0].started.wait(), timeout=1)

    first = await manager.cancel(run.run_id)
    second = await manager.cancel(run.run_id)

    assert first.status is RunStatus.CANCELLED
    assert second == first
    if disconnect_after_claim:
        assert executors[0].cancelled.is_set()
    if subscription is not None:
        terminal = await asyncio.wait_for(subscription.receive(), timeout=1)
        assert terminal.kind == "run_cancelled"


async def test_unclaimed_run_is_cancelled_by_injected_timeout_without_real_wait() -> None:
    timeout_reached = asyncio.Event()

    async def wait_for_claim_timeout(_seconds: float) -> None:
        await timeout_reached.wait()

    manager = TurnRunManager(
        lambda invoker, sink: RecordingExecutor(invoker, sink),
        settlement_handler=_settle,
        wait_for_claim_timeout=wait_for_claim_timeout,
    )
    run = await manager.create((), Invoker())

    timeout_reached.set()
    summary = await manager.wait(run.run_id)

    assert summary.status is RunStatus.CANCELLED
    assert manager.active_run is None


async def test_concurrent_pending_cancels_share_the_same_cleanup() -> None:
    manager = TurnRunManager(
        lambda invoker, sink: RecordingExecutor(invoker, sink),
        settlement_handler=_settle,
    )
    run = await manager.create((), Invoker())

    first, second = await asyncio.wait_for(
        asyncio.gather(manager.cancel(run.run_id), manager.cancel(run.run_id)),
        timeout=1,
    )

    assert first == second
    assert first.status is RunStatus.CANCELLED
    assert manager.active_run is None


async def test_second_stream_cannot_claim_the_same_run() -> None:
    manager = TurnRunManager(
        lambda invoker, sink: RecordingExecutor(invoker, sink),
        settlement_handler=_settle,
    )
    run = await manager.create((), Invoker())
    await manager.claim(run.run_id)

    with pytest.raises(RuntimeError, match="已被领取"):
        await manager.claim(run.run_id)

    await manager.cancel(run.run_id)


async def test_stream_yields_one_complete_ndjson_line_per_event_and_success_turn() -> None:
    executors: list[StreamingExecutor] = []

    def factory(invoker: FrozenRunInvoker, sink: ProgressSink) -> StreamingExecutor:
        executor = StreamingExecutor(invoker, sink)
        executors.append(executor)
        return executor

    manager = TurnRunManager(factory, settlement_handler=lambda _run: _return_turn_id())
    run = await manager.create((), Invoker())
    subscription = await manager.claim(run.run_id)
    stream = stream_turn_run_events(manager, HistorySource(), subscription)

    progress_line = await asyncio.wait_for(anext(stream), timeout=1)
    executors[0].release.set()
    terminal_line = await asyncio.wait_for(anext(stream), timeout=1)

    assert progress_line.endswith(b"\n")
    assert progress_line.count(b"\n") == 1
    assert json.loads(progress_line) == {
        "run_id": run.run_id,
        "kind": "node_started",
        "location_id": "the_home",
        "attempt": 1,
        "max_attempts": 3,
        "retrying": False,
        "completed_maps": 0,
        "total_maps": 1,
        "elapsed_ms": 5,
    }
    terminal = json.loads(terminal_line)
    assert terminal["kind"] == "run_succeeded"
    assert terminal["turn"]["turn_id"] == 9
    assert terminal["turn"]["roles"][0]["content"] == "天出发了。"
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


async def _return_turn_id() -> int:
    return 9


async def test_closing_stream_cancels_execution_and_skips_settlement() -> None:
    executors: list[StreamingExecutor] = []
    settlement_calls = 0

    def factory(invoker: FrozenRunInvoker, sink: ProgressSink) -> StreamingExecutor:
        executor = StreamingExecutor(invoker, sink)
        executors.append(executor)
        return executor

    async def settle(_run: TurnRun) -> int:
        nonlocal settlement_calls
        settlement_calls += 1
        return 9

    manager = TurnRunManager(factory, settlement_handler=settle)
    run = await manager.create((), Invoker())
    subscription = await manager.claim(run.run_id)
    stream = stream_turn_run_events(manager, HistorySource(), subscription)
    await asyncio.wait_for(anext(stream), timeout=1)

    waiting_for_next_event = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)
    waiting_for_next_event.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting_for_next_event

    summary = await manager.get(run.run_id)
    assert summary.status is RunStatus.CANCELLED
    assert settlement_calls == 0
    assert executors[0].cancelled.is_set()
    assert manager.active_run is None


async def test_failed_and_cancelled_stream_terminals_never_include_story_payloads() -> None:
    failed_manager = TurnRunManager(
        lambda invoker, sink: FailingExecutor(invoker, sink),
        settlement_handler=_settle,
    )
    failed_run = await failed_manager.create((), Invoker())
    failed_subscription = await failed_manager.claim(failed_run.run_id)
    failed_stream = stream_turn_run_events(failed_manager, HistorySource(), failed_subscription)

    failed = json.loads(await asyncio.wait_for(anext(failed_stream), timeout=1))

    assert failed["kind"] == "run_failed"
    assert failed["error"] == "AI 任务执行失败"
    assert "turn" not in failed
    assert "secret-provider-key" not in json.dumps(failed)

    executors: list[StreamingExecutor] = []

    def factory(invoker: FrozenRunInvoker, sink: ProgressSink) -> StreamingExecutor:
        executor = StreamingExecutor(invoker, sink)
        executors.append(executor)
        return executor

    cancelled_manager = TurnRunManager(factory, settlement_handler=_settle)
    cancelled_run = await cancelled_manager.create((), Invoker())
    cancelled_subscription = await cancelled_manager.claim(cancelled_run.run_id)
    cancelled_stream = stream_turn_run_events(
        cancelled_manager,
        HistorySource(),
        cancelled_subscription,
    )
    await asyncio.wait_for(anext(cancelled_stream), timeout=1)

    await cancelled_manager.cancel(cancelled_run.run_id)
    cancelled = json.loads(await asyncio.wait_for(anext(cancelled_stream), timeout=1))

    assert cancelled["kind"] == "run_cancelled"
    assert "turn" not in cancelled
    assert "error" not in cancelled


async def test_http_stream_uses_ndjson_media_type_and_complete_lines() -> None:
    manager = TurnRunManager(
        lambda invoker, sink: CompletingStreamingExecutor(invoker, sink),
        settlement_handler=lambda _run: _return_turn_id(),
    )
    run = await manager.create((), Invoker())

    class WorldReader:
        def get_world(self, world_id: int) -> object:
            return world_id

    class ContextSource:
        def build_current_turn_snapshot(
            self,
            *,
            world_id: int,
            player_intent: str,
        ) -> tuple[LocationSimulationContext, ...]:
            del world_id, player_intent
            return ()

    app = FastAPI()
    app.include_router(
        create_turn_router(
            WorldReader(),
            ContextSource(),
            HistorySource(),
            manager,
            Invoker,
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/api/turn-runs/{run.run_id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = response.content.splitlines(keepends=True)
    assert len(lines) == 2
    assert all(line.endswith(b"\n") and line.count(b"\n") == 1 for line in lines)


async def test_stream_disconnect_leaves_turn_attributes_memory_and_time_unchanged(
    tmp_path: Path,
) -> None:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[2] / "alembic.ini")
    session_factory = create_session_factory(create_sqlite_engine(config.paths.database_path))
    now = datetime(2026, 7, 18, tzinfo=UTC)
    with session_factory() as session:
        session.add(
            Role(
                id=1,
                name="天",
                persona="人设",
                system_prompt="提示词",
                world_book="世界书",
                base_values_json={"energy": 30},
                attribute_types_json={"energy": "integer"},
                attribute_labels_json={"energy": "精力"},
                attribute_descriptions_json={"energy": "当前精力"},
                attribute_update_rules_json={"energy": "休息后增加"},
                attribute_constraints_json={},
                attribute_allowed_operations_json={"energy": ["increment"]},
                attribute_examples_json={},
                version=1,
                created_at=now,
                updated_at=now,
            )
        )
        world = World(
            id=1,
            active_branch_id=None,
            created_at=now,
            updated_at=now,
            last_played_at=now,
        )
        session.add(world)
        session.flush()
        branch = WorldBranch(
            id=1,
            world_id=1,
            name="主分支",
            parent_branch_id=None,
            fork_turn_id=None,
            head_turn_id=None,
            day=3,
            time_slot="evening",
            current_location_id="the_home",
            state_version=4,
            created_at=now,
            updated_at=now,
        )
        session.add(branch)
        session.flush()
        world.active_branch_id = branch.id
        session.add(
            WorldRoleState(
                world_id=1,
                role_id=1,
                kind="player",
                enabled=True,
                change_values_json={"energy": 5},
                version=2,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        session.add(
            WorldRoleMemory(
                world_id=1,
                role_id=1,
                memory="旧记忆",
                version=2,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    executors: list[StreamingExecutor] = []

    def factory(invoker: FrozenRunInvoker, sink: ProgressSink) -> StreamingExecutor:
        executor = StreamingExecutor(invoker, sink)
        executors.append(executor)
        return executor

    manager = TurnRunManager(
        factory,
        settlement_handler=SettlementService(session_factory).settle,
    )
    snapshot = TurnContextSnapshot(
        world_id=1,
        branch_id=1,
        day=3,
        time_slot="evening",
        world_state_version=4,
        protagonist_role_id=1,
        world_role_versions={1: 2},
        role_definition_versions={1: 1},
        turn_positions={1: "the_home"},
        locations=(),
    )
    run = await manager.create(snapshot, Invoker())
    subscription = await manager.claim(run.run_id)
    stream = stream_turn_run_events(manager, HistorySource(), subscription)
    response = NdjsonStreamingResponse(
        stream,
        cleanup=lambda: manager.cancel(run.run_id),
    )
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/api/turn-runs/{run.run_id}/stream",
        "raw_path": b"/api/turn-runs/run/stream",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
        "state": {},
    }

    async def receive() -> Message:
        return {"type": "http.disconnect"}

    async def fail_before_body_iteration(_message: Message) -> None:
        raise OSError("连接在响应头发送时断开")

    with pytest.raises(ClientDisconnect):
        await response(scope, receive, fail_before_body_iteration)

    with session_factory() as session:
        turn_count = session.scalar(select(func.count()).select_from(Turn))
        state = session.scalar(
            select(WorldRoleState).where(
                WorldRoleState.world_id == 1,
                WorldRoleState.role_id == 1,
            )
        )
        memory = session.scalar(
            select(WorldRoleMemory).where(
                WorldRoleMemory.world_id == 1,
                WorldRoleMemory.role_id == 1,
            )
        )
        branch = session.get(WorldBranch, 1)
        assert state is not None and memory is not None and branch is not None
        assert turn_count == 0
        assert state.change_values_json == {"energy": 5}
        assert state.version == 2
        assert memory.memory == "旧记忆"
        assert memory.version == 2
        assert (branch.day, branch.time_slot, branch.state_version, branch.head_turn_id) == (
            3,
            "evening",
            4,
            None,
        )
