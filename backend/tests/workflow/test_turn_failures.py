"""完整轮次失败边界。

HTTP stream 首段/中途断开由 ``backend/tests/test_turn_stream.py`` 的真实 ASGI
回归覆盖；运行中设置变化由 ``test_manager.py`` 与 ``test_ai_tasks.py`` 的真实
TaskInvoker 冻结组合覆盖。本文件补足从冻结世界到执行器、结算和数据库的失败纵向边界。
"""

import asyncio
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.contracts import ProviderConnection, ProviderRegistry
from app.ai.dto import ChatRequest, ChatResponse
from app.ai.errors import AiErrorCategory, AiProviderError
from app.character.models import Role
from app.story.models import (
    StateChange,
    Turn,
    TurnEvent,
    TurnEventParticipant,
    TurnStory,
)
from app.story.service import SettlementService
from app.workflow.ai_tasks import TaskInvoker
from app.workflow.context import ContextBuilder
from app.workflow.executor import MapChainExecutor
from app.workflow.manager import TurnRunManager
from app.workflow.retry import RetryPolicy
from app.workflow.runtime import RunStatus, TurnRun, TurnRunSummary
from app.workflow.schemas import (
    AttributeMemoryAnalysisOutput,
    EventKnowledge,
    InteractionGroupOutput,
    LocationSimulationOutput,
    ObjectiveEventOutput,
)
from app.world.models import (
    CharacterLocationCandidate,
    CharacterLocationRule,
    World,
    WorldBranch,
    WorldRoleMemory,
    WorldRoleState,
)

from .test_turn_integration import (
    ASYNC_TEST_TIMEOUT_SECONDS,
    DeterministicProvider,
    JsonObject,
    build_integration_test_db,
    build_test_settings,
    no_test_wait,
    parse_json_object,
    require_json_int,
    require_json_string,
    role_objects,
)


@pytest.fixture
def integration_db(tmp_path: Path) -> sessionmaker[Session]:
    return build_integration_test_db(tmp_path)


@dataclass(frozen=True)
class DatabaseFacts:
    """失败前后的全部世界引用与轮次持久化事实，禁止用粗粒度计数掩盖替换写。"""

    worlds: tuple[tuple[object, ...], ...]
    branches: tuple[tuple[object, ...], ...]
    roles: tuple[tuple[object, ...], ...]
    role_states: tuple[tuple[object, ...], ...]
    memories: tuple[tuple[object, ...], ...]
    location_rules: tuple[tuple[object, ...], ...]
    location_candidates: tuple[tuple[object, ...], ...]
    turns: tuple[tuple[object, ...], ...]
    stories: tuple[tuple[object, ...], ...]
    events: tuple[tuple[object, ...], ...]
    participants: tuple[tuple[object, ...], ...]
    state_changes: tuple[tuple[object, ...], ...]


def _database_facts(factory: sessionmaker[Session]) -> DatabaseFacts:
    with factory() as session:
        worlds = list(session.scalars(select(World).order_by(World.id)))
        branches = list(session.scalars(select(WorldBranch).order_by(WorldBranch.id)))
        roles = list(session.scalars(select(Role).order_by(Role.id)))
        states = list(
            session.scalars(
                select(WorldRoleState).order_by(
                    WorldRoleState.world_id,
                    WorldRoleState.role_id,
                )
            )
        )
        memories = list(
            session.scalars(
                select(WorldRoleMemory).order_by(
                    WorldRoleMemory.world_id,
                    WorldRoleMemory.role_id,
                )
            )
        )
        rules = list(
            session.scalars(select(CharacterLocationRule).order_by(CharacterLocationRule.id))
        )
        candidates = list(
            session.scalars(
                select(CharacterLocationCandidate).order_by(CharacterLocationCandidate.id)
            )
        )
        turns = list(session.scalars(select(Turn).order_by(Turn.id)))
        stories = list(session.scalars(select(TurnStory).order_by(TurnStory.id)))
        events = list(session.scalars(select(TurnEvent).order_by(TurnEvent.id)))
        participants = list(
            session.scalars(
                select(TurnEventParticipant).order_by(
                    TurnEventParticipant.event_id,
                    TurnEventParticipant.role_id,
                )
            )
        )
        changes = list(session.scalars(select(StateChange).order_by(StateChange.id)))
        return DatabaseFacts(
            worlds=tuple(
                (
                    item.id,
                    item.active_branch_id,
                    item.created_at,
                    item.updated_at,
                    item.last_played_at,
                )
                for item in worlds
            ),
            branches=tuple(
                (
                    item.id,
                    item.world_id,
                    item.name,
                    item.parent_branch_id,
                    item.fork_turn_id,
                    item.head_turn_id,
                    item.day,
                    item.time_slot,
                    item.current_location_id,
                    item.state_version,
                    item.created_at,
                    item.updated_at,
                )
                for item in branches
            ),
            roles=tuple(
                (
                    item.id,
                    item.name,
                    item.persona,
                    item.system_prompt,
                    item.world_book,
                    deepcopy(item.base_values_json),
                    deepcopy(item.attribute_types_json),
                    deepcopy(item.attribute_labels_json),
                    deepcopy(item.attribute_descriptions_json),
                    deepcopy(item.attribute_update_rules_json),
                    deepcopy(item.attribute_constraints_json),
                    deepcopy(item.attribute_allowed_operations_json),
                    deepcopy(item.attribute_examples_json),
                    item.version,
                    item.created_at,
                    item.updated_at,
                )
                for item in roles
            ),
            role_states=tuple(
                (
                    item.id,
                    item.world_id,
                    item.role_id,
                    item.kind,
                    item.enabled,
                    deepcopy(item.change_values_json),
                    item.version,
                    item.created_at,
                    item.updated_at,
                )
                for item in states
            ),
            memories=tuple(
                (
                    item.id,
                    item.world_id,
                    item.role_id,
                    item.memory,
                    item.version,
                    item.created_at,
                    item.updated_at,
                )
                for item in memories
            ),
            location_rules=tuple(
                (
                    item.id,
                    item.world_id,
                    item.role_id,
                    item.weekday_mask,
                    item.time_slot,
                    item.mode,
                    item.priority,
                    item.enabled,
                )
                for item in rules
            ),
            location_candidates=tuple(
                (item.id, item.rule_id, item.location_id, item.weight) for item in candidates
            ),
            turns=tuple(
                (
                    item.id,
                    item.world_id,
                    item.branch_id,
                    item.parent_turn_id,
                    item.day,
                    item.time_slot,
                    item.player_intent,
                    deepcopy(item.objective_events_json),
                    deepcopy(item.state_after_json),
                    deepcopy(item.ai_execution_meta_json),
                    item.created_at,
                )
                for item in turns
            ),
            stories=tuple(
                (item.id, item.turn_id, item.role_id, item.content, item.sort_order)
                for item in stories
            ),
            events=tuple(
                (
                    item.id,
                    item.turn_id,
                    item.location_id,
                    item.event_type,
                    deepcopy(item.fact_json),
                    item.created_at,
                )
                for item in events
            ),
            participants=tuple(
                (
                    item.event_id,
                    item.role_id,
                    item.knowledge_level,
                    item.perspective_notes,
                )
                for item in participants
            ),
            state_changes=tuple(
                (
                    item.id,
                    item.turn_id,
                    item.event_id,
                    item.role_id,
                    item.attribute_key,
                    item.operation,
                    deepcopy(item.old_value_json),
                    deepcopy(item.operand_json),
                    deepcopy(item.new_value_json),
                    item.reason,
                )
                for item in changes
            ),
        )


def _with_incremented_branch_state_version(facts: DatabaseFacts) -> DatabaseFacts:
    branches: list[tuple[object, ...]] = []
    for branch in facts.branches:
        state_version = branch[9]
        assert isinstance(state_version, int)
        branches.append((*branch[:9], state_version + 1, *branch[10:]))
    return replace(facts, branches=tuple(branches))


async def _wait_for_summary(manager: TurnRunManager, run_id: str) -> TurnRunSummary:
    try:
        return await asyncio.wait_for(
            manager.wait(run_id),
            timeout=ASYNC_TEST_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        pytest.fail("失败轮次未在短超时内终止, 可能发生并发死锁")


def _manager(
    factory: sessionmaker[Session],
    provider: DeterministicProvider,
    *,
    settlement_handler: Callable[[TurnRun], Awaitable[int]] | None = None,
) -> tuple[TurnRunManager, TaskInvoker]:
    invoker = TaskInvoker(
        build_test_settings(),
        ProviderRegistry([provider]),
        RetryPolicy(backoff_seconds=0, sleep=no_test_wait),
    )
    settlement = SettlementService(factory)
    manager = TurnRunManager(
        lambda frozen, sink: MapChainExecutor(frozen, progress_sink=sink),
        settlement_handler=settlement_handler or settlement.settle,
    )
    return manager, invoker


class CrossRoleProvider(DeterministicProvider):
    async def complete(
        self,
        request: ChatRequest,
        connection: ProviderConnection,
    ) -> ChatResponse:
        response = await super().complete(request, connection)
        raw = request.messages[-1].content
        assert raw is not None
        context = parse_json_object(raw)
        location_id = require_json_string(context.get("location_id"), "地点 ID")
        if location_id == "the_home" and "day" in context:
            payload = LocationSimulationOutput.model_validate_json(response.text)
            invalid_payload = payload.model_copy(
                update={
                    "groups": [
                        InteractionGroupOutput(
                            group_id="cross-map",
                            role_ids=[1, 2, 4],
                        )
                    ]
                }
            )
            return response.model_copy(update={"text": invalid_payload.model_dump_json()})
        return response


class DuplicateCrossMapEventProvider(DeterministicProvider):
    @staticmethod
    def _location_output(context: JsonObject) -> LocationSimulationOutput:
        output = DeterministicProvider._location_output(context)
        location_id = require_json_string(context.get("location_id"), "地点 ID")
        roles = role_objects(context)
        if not roles:
            raise AssertionError("地点上下文必须至少包含一个角色")
        role_id = require_json_int(roles[0].get("role_id"), "角色 ID")
        group_id = "player-alone" if location_id == "the_home" else f"group-{location_id}"
        event = ObjectiveEventOutput(
            event_key="same-across-maps",
            group_id=group_id,
            event_type="local",
            fact={"location": location_id},
            knowledge=[
                EventKnowledge(
                    role_id=role_id,
                    level="observer",
                    perspective_notes="",
                )
            ],
        )
        chronicles = [
            chronicle.model_copy(
                update={
                    "known_event_keys": (
                        ["same-across-maps"] if chronicle.role_id == role_id else []
                    )
                }
            )
            for chronicle in output.chronicles
        ]
        return output.model_copy(update={"events": [event], "chronicles": chronicles})

    @staticmethod
    def _attribute_output(context: JsonObject) -> AttributeMemoryAnalysisOutput:
        output = DeterministicProvider._attribute_output(context)
        roles = [role.model_copy(update={"attribute_update_intents": []}) for role in output.roles]
        return output.model_copy(update={"roles": roles})


class AuthenticationFailureProvider(DeterministicProvider):
    async def complete(
        self,
        request: ChatRequest,
        connection: ProviderConnection,
    ) -> ChatResponse:
        raw = request.messages[-1].content
        assert raw is not None
        context = parse_json_object(raw)
        location_id = require_json_string(context.get("location_id"), "地点 ID")
        if location_id == "the_home" and "day" in context:
            self.location_calls["the_home"] = self.location_calls.get("the_home", 0) + 1
            raise AiProviderError(
                category=AiErrorCategory.AUTHENTICATION,
                message="包含不应外泄的厂商正文",
                retryable=False,
            )
        return await super().complete(request, connection)


class BlockingProvider(DeterministicProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def complete(
        self,
        request: ChatRequest,
        connection: ProviderConnection,
    ) -> ChatResponse:
        del request, connection
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("取消后不得恢复 Provider 调用")


@pytest.mark.parametrize(
    ("provider", "expected_home_attempts"),
    [
        (CrossRoleProvider(), 3),
        (AuthenticationFailureProvider(), 1),
    ],
)
async def test_invalid_cross_map_role_retries_but_nonretryable_error_stops_once(
    integration_db: sessionmaker[Session],
    provider: DeterministicProvider,
    expected_home_attempts: int,
) -> None:
    """可重试边界恰好三次；认证失败只调用一次，二者都不能留下部分结果。"""

    before = _database_facts(integration_db)
    snapshot = ContextBuilder(integration_db).build_current_turn_snapshot(
        world_id=1,
        player_intent="尝试跨地图互动",
    )
    manager, invoker = _manager(integration_db, provider)
    run = await manager.create(snapshot, invoker)
    await manager.claim(run.run_id)
    summary = await _wait_for_summary(manager, run.run_id)

    assert summary.status is RunStatus.FAILED
    assert provider.location_calls["the_home"] == expected_home_attempts
    assert _database_facts(integration_db) == before


async def test_duplicate_event_key_across_maps_is_rejected_at_atomic_settlement(
    integration_db: sessionmaker[Session],
) -> None:
    provider = DuplicateCrossMapEventProvider()
    before = _database_facts(integration_db)
    snapshot = ContextBuilder(integration_db).build_current_turn_snapshot(
        world_id=1,
        player_intent="观察多地事件",
    )
    manager, invoker = _manager(integration_db, provider)
    run = await manager.create(snapshot, invoker)
    await manager.claim(run.run_id)
    summary = await _wait_for_summary(manager, run.run_id)

    assert summary.status is RunStatus.FAILED
    assert provider.location_calls == {"the_home": 1, "the_dungeon": 1, "the_school": 1}
    assert _database_facts(integration_db) == before


async def test_cancelled_slow_provider_discards_all_outputs_and_releases_run(
    integration_db: sessionmaker[Session],
) -> None:
    provider = BlockingProvider()
    before = _database_facts(integration_db)
    snapshot = ContextBuilder(integration_db).build_current_turn_snapshot(
        world_id=1,
        player_intent="等待后取消",
    )
    manager, invoker = _manager(integration_db, provider)
    run = await manager.create(snapshot, invoker)
    await manager.claim(run.run_id)
    try:
        await asyncio.wait_for(
            provider.started.wait(),
            timeout=ASYNC_TEST_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        pytest.fail("取消测试的 Provider 未及时进入慢调用")

    try:
        summary = await asyncio.wait_for(
            manager.cancel(run.run_id),
            timeout=ASYNC_TEST_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        pytest.fail("取消后轮次未及时清理")

    assert summary.status is RunStatus.CANCELLED
    assert manager.active_run is None
    assert _database_facts(integration_db) == before


async def test_state_version_conflict_after_ai_success_rolls_back_the_whole_turn(
    integration_db: sessionmaker[Session],
) -> None:
    provider = DeterministicProvider()
    before = _database_facts(integration_db)
    snapshot = ContextBuilder(integration_db).build_current_turn_snapshot(
        world_id=1,
        player_intent="冻结后世界发生变化",
    )
    settlement = SettlementService(integration_db)

    async def conflict_then_settle(run: TurnRun) -> int:
        with integration_db() as session:
            branch = session.get(WorldBranch, 1)
            assert branch is not None
            branch.state_version += 1
            session.commit()
        return await settlement.settle(run)

    manager, invoker = _manager(
        integration_db,
        provider,
        settlement_handler=conflict_then_settle,
    )
    run = await manager.create(snapshot, invoker)
    await manager.claim(run.run_id)
    summary = await _wait_for_summary(manager, run.run_id)

    assert summary.status is RunStatus.FAILED
    after = _database_facts(integration_db)
    assert after == _with_incremented_branch_state_version(before)
    with integration_db() as session:
        branch = session.get(WorldBranch, 1)
        assert branch is not None
        assert branch.state_version == snapshot.world_state_version + 1
