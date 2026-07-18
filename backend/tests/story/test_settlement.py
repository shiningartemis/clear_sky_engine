"""成功轮次原子结算测试。"""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.attribute import AttributeUpdateIntent
from app.character.models import Role
from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_session_factory, create_sqlite_engine
from app.main import create_app
from app.story.models import StateChange, Turn, TurnEvent, TurnStory
from app.story.service import SettlementConflictError, SettlementService
from app.story.store import StoryStore
from app.workflow.context import (
    LocationSimulationContext,
    RoleSimulationContext,
    TurnContextSnapshot,
)
from app.workflow.runtime import RunStatus, TurnRun
from app.workflow.schemas import (
    AttributeMemoryAnalysisOutput,
    EventKnowledge,
    InteractionGroupOutput,
    LocationSimulationOutput,
    ObjectiveEventOutput,
    RoleAttributeMemoryOutput,
    RoleChronicleOutput,
)
from app.world.models import World, WorldBranch, WorldRoleMemory, WorldRoleState
from app.world.store import WorldStore

NOW = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)


def _role(role_id: int, name: str) -> Role:
    return Role(
        id=role_id,
        name=name,
        persona=f"{name}人设",
        system_prompt=f"{name}提示词",
        world_book=f"{name}世界书",
        base_values_json={"level": 10},
        attribute_types_json={"level": "integer"},
        attribute_labels_json={"level": "等级"},
        attribute_descriptions_json={"level": "当前等级"},
        attribute_update_rules_json={"level": "明确成长时更新"},
        attribute_constraints_json={"level": {"minimum": 0, "maximum": 99}},
        attribute_allowed_operations_json={"level": ["increment", "replace"]},
        attribute_examples_json={},
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[3] / "alembic.ini")
    factory = create_session_factory(create_sqlite_engine(config.paths.database_path))
    with factory() as session:
        session.add_all([_role(1, "主角"), _role(2, "同行者"), _role(3, "离线者")])
        for world_id in (1, 2):
            world = World(
                id=world_id,
                active_branch_id=None,
                created_at=NOW,
                updated_at=NOW,
                last_played_at=NOW,
            )
            session.add(world)
            session.flush()
            branch = WorldBranch(
                id=world_id,
                world_id=world_id,
                name="主分支",
                parent_branch_id=None,
                fork_turn_id=None,
                head_turn_id=None,
                day=1,
                time_slot="morning",
                current_location_id="the_home",
                state_version=7,
                created_at=NOW,
                updated_at=NOW,
            )
            session.add(branch)
            session.flush()
            world.active_branch_id = branch.id
            for role_id, kind in ((1, "player"), (2, "npc"), (3, "npc")):
                session.add(
                    WorldRoleState(
                        world_id=world_id,
                        role_id=role_id,
                        kind=kind,
                        enabled=True,
                        change_values_json={},
                        version=3,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            session.flush()
            for role_id in (1, 2, 3):
                session.add(
                    WorldRoleMemory(
                        world_id=world_id,
                        role_id=role_id,
                        memory="异世界记忆" if world_id == 2 else "",
                        version=1,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
        session.commit()
    return factory


def _role_context(role_id: int, *, player: bool = False) -> RoleSimulationContext:
    return RoleSimulationContext(
        role_id=role_id,
        name="主角" if player else "同行者",
        persona="人设",
        system_prompt="提示词",
        world_book="世界书",
        effective_attributes=MappingProxyType({"level": 10}),
        attribute_update_rules=MappingProxyType({"level": "明确成长时更新"}),
        attribute_version=3,
        long_term_memory="",
        recent_turns=(),
    )


def _snapshot(*, state_version: int = 7, time_slot: str = "morning") -> TurnContextSnapshot:
    location = LocationSimulationContext(
        location_id="the_home",
        day=1,
        time_slot=time_slot,
        player_intent="探索庭院",
        roles=(_role_context(1, player=True), _role_context(2)),
    )
    return TurnContextSnapshot(
        world_id=1,
        branch_id=1,
        day=1,
        time_slot=time_slot,
        world_state_version=state_version,
        protagonist_role_id=1,
        world_role_versions=MappingProxyType({1: 3, 2: 3, 3: 3}),
        role_definition_versions=MappingProxyType({1: 1, 2: 1, 3: 1}),
        turn_positions=MappingProxyType({1: "the_home", 2: "the_home", 3: "offline"}),
        locations=(location,),
    )


def _successful_run(
    *,
    state_version: int = 7,
    time_slot: str = "morning",
    update_second_role: bool = True,
) -> TurnRun:
    snapshot = _snapshot(state_version=state_version, time_slot=time_slot)
    run = TurnRun.create(snapshot, memory_max_chars=50)
    chain = run.map_runs["the_home"]
    chain.location_output = LocationSimulationOutput(
        location_id="the_home",
        groups=[InteractionGroupOutput(group_id="pair", role_ids=[1, 2])],
        events=[
            ObjectiveEventOutput(
                event_key="found_key",
                group_id="pair",
                event_type="discovery",
                fact={"summary": "两人发现一把钥匙"},
                knowledge=[
                    EventKnowledge(role_id=1, level="participant"),
                    EventKnowledge(role_id=2, level="participant"),
                ],
            )
        ],
        chronicles=[
            RoleChronicleOutput(
                role_id=1,
                content="主角在庭院发现钥匙。",
                known_event_keys=["found_key"],
            ),
            RoleChronicleOutput(
                role_id=2,
                content="同行者见证了发现。",
                known_event_keys=["found_key"],
            ),
        ],
    )
    second_intents = (
        [
            AttributeUpdateIntent(
                role_id=2,
                attribute_key="level",
                operation="increment",
                value=2,
                reason="完成探索",
                source_event_id="found_key",
                expected_version=3,
            )
        ]
        if update_second_role
        else []
    )
    chain.attribute_output = AttributeMemoryAnalysisOutput(
        location_id="the_home",
        roles=[
            RoleAttributeMemoryOutput(
                role_id=1,
                attribute_update_intents=[],
                memory_append="记住庭院钥匙",
            ),
            RoleAttributeMemoryOutput(
                role_id=2,
                attribute_update_intents=second_intents,
                memory_append="与主角找到钥匙",
            ),
        ],
    )
    chain.status = RunStatus.SUCCEEDED
    run.status = RunStatus.SUCCEEDED
    return run


def _counts(session: Session) -> tuple[int, int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(Turn)) or 0,
        session.scalar(select(func.count()).select_from(TurnStory)) or 0,
        session.scalar(select(func.count()).select_from(TurnEvent)) or 0,
        session.scalar(select(func.count()).select_from(StateChange)) or 0,
    )


async def test_success_settles_story_event_attributes_memory_and_time_once(
    session_factory: sessionmaker[Session],
) -> None:
    turn_id = await SettlementService(session_factory, clock=lambda: NOW).settle(_successful_run())

    with session_factory() as session:
        branch = session.get(WorldBranch, 1)
        state = session.scalar(
            select(WorldRoleState).where(
                WorldRoleState.world_id == 1,
                WorldRoleState.role_id == 2,
            )
        )
        memories = list(
            session.scalars(
                select(WorldRoleMemory)
                .where(WorldRoleMemory.world_id == 1)
                .order_by(WorldRoleMemory.role_id)
            )
        )
        turn = session.get(Turn, turn_id)
        change = session.scalar(select(StateChange).where(StateChange.turn_id == turn_id))
        assert branch is not None and state is not None and turn is not None and change is not None
        assert _counts(session) == (1, 2, 1, 1)
        assert (branch.day, branch.time_slot, branch.state_version, branch.head_turn_id) == (
            1,
            "midday",
            8,
            turn_id,
        )
        assert state.change_values_json == {"level": 2}
        assert state.version == 4
        assert [item.memory for item in memories] == [
            "记住庭院钥匙",
            "与主角找到钥匙",
            "",
        ]
        assert [item.version for item in memories] == [2, 2, 1]
        assert change.event_id is not None
        assert change.old_value_json == 10
        assert change.new_value_json == 12
        assert turn.state_after_json["turn_positions"] == {
            "1": "the_home",
            "2": "the_home",
            "3": "offline",
        }


async def test_no_attribute_change_still_appends_memory_and_later_uses_separator(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        memories = list(
            session.scalars(select(WorldRoleMemory).where(WorldRoleMemory.world_id == 1))
        )
        for memory in memories:
            memory.memory = f"旧记忆{memory.role_id}"
        session.commit()

    await SettlementService(session_factory, clock=lambda: NOW).settle(
        _successful_run(update_second_role=False)
    )

    with session_factory() as session:
        memories = list(
            session.scalars(
                select(WorldRoleMemory)
                .where(WorldRoleMemory.world_id == 1)
                .order_by(WorldRoleMemory.role_id)
            )
        )
        assert [item.memory for item in memories] == [
            "旧记忆1__记住庭院钥匙",
            "旧记忆2__与主角找到钥匙",
            "旧记忆3",
        ]
        assert _counts(session)[3] == 0


async def test_consecutive_intents_record_each_real_attribute_transition(
    session_factory: sessionmaker[Session],
) -> None:
    run = _successful_run()
    chain = run.map_runs["the_home"]
    chain.attribute_output = AttributeMemoryAnalysisOutput(
        location_id="the_home",
        roles=[
            RoleAttributeMemoryOutput(
                role_id=1,
                attribute_update_intents=[],
                memory_append="记住庭院钥匙",
            ),
            RoleAttributeMemoryOutput(
                role_id=2,
                attribute_update_intents=[
                    AttributeUpdateIntent(
                        role_id=2,
                        attribute_key="level",
                        operation="increment",
                        value=1,
                        reason="先解开机关",
                        source_event_id="found_key",
                        expected_version=3,
                    ),
                    AttributeUpdateIntent(
                        role_id=2,
                        attribute_key="level",
                        operation="increment",
                        value=2,
                        reason="再开启密室",
                        source_event_id="found_key",
                        expected_version=3,
                    ),
                ],
                memory_append="连续完成探索",
            ),
        ],
    )

    turn_id = await SettlementService(session_factory, clock=lambda: NOW).settle(run)

    with session_factory() as session:
        changes = list(
            session.scalars(
                select(StateChange).where(StateChange.turn_id == turn_id).order_by(StateChange.id)
            )
        )
        assert [
            (item.old_value_json, item.operand_json, item.new_value_json) for item in changes
        ] == [(10, 1, 11), (11, 2, 13)]


async def test_settlement_keeps_same_role_isolated_between_worlds(
    session_factory: sessionmaker[Session],
) -> None:
    await SettlementService(session_factory, clock=lambda: NOW).settle(_successful_run())

    with session_factory() as session:
        other_state = session.scalar(
            select(WorldRoleState).where(
                WorldRoleState.world_id == 2,
                WorldRoleState.role_id == 2,
            )
        )
        other_memory = session.scalar(
            select(WorldRoleMemory).where(
                WorldRoleMemory.world_id == 2,
                WorldRoleMemory.role_id == 2,
            )
        )
        assert other_state is not None and other_memory is not None
        assert other_state.change_values_json == {}
        assert other_state.version == 3
        assert other_memory.memory == "异世界记忆"
        assert other_memory.version == 1


def _raise_failure(message: str) -> Callable[..., None]:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(message)

    return fail


@pytest.mark.parametrize(
    ("target", "method", "message"),
    [
        (StoryStore, "add_story", "故事写入失败"),
        (StoryStore, "add_event", "事件写入失败"),
    ],
)
async def test_story_or_event_failure_rolls_back_everything(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    target: type[StoryStore],
    method: str,
    message: str,
) -> None:
    monkeypatch.setattr(target, method, _raise_failure(message))

    with pytest.raises(RuntimeError, match=message):
        await SettlementService(session_factory, clock=lambda: NOW).settle(_successful_run())

    _assert_unchanged(session_factory)


@pytest.mark.parametrize(
    ("method", "message"),
    [
        ("save_role_state", "第二角色属性失败"),
        ("save_role_memory", "第二角色记忆失败"),
    ],
)
async def test_second_role_write_failure_rolls_back_everything(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    message: str,
) -> None:
    original = getattr(WorldStore, method)
    calls = 0

    def fail_second(store: WorldStore, item: WorldRoleState | WorldRoleMemory) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError(message)
        original(store, item)

    monkeypatch.setattr(WorldStore, method, fail_second)

    with pytest.raises(RuntimeError, match=message):
        await SettlementService(session_factory, clock=lambda: NOW).settle(_successful_run())

    _assert_unchanged(session_factory)


async def test_branch_version_conflict_writes_nothing(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        branch = session.get(WorldBranch, 1)
        assert branch is not None
        branch.state_version = 8
        session.commit()

    with pytest.raises(SettlementConflictError, match="版本"):
        await SettlementService(session_factory, clock=lambda: NOW).settle(_successful_run())

    with session_factory() as session:
        assert _counts(session) == (0, 0, 0, 0)
        branch = session.get(WorldBranch, 1)
        assert branch is not None
        assert (branch.day, branch.time_slot, branch.state_version) == (1, "morning", 8)


async def test_offline_role_version_change_rejects_the_whole_turn(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        offline = session.scalar(
            select(WorldRoleState).where(
                WorldRoleState.world_id == 1,
                WorldRoleState.role_id == 3,
            )
        )
        assert offline is not None
        offline.version += 1
        session.commit()

    with pytest.raises(SettlementConflictError, match=r"角色.*版本"):
        await SettlementService(session_factory, clock=lambda: NOW).settle(_successful_run())

    with session_factory() as session:
        assert _counts(session) == (0, 0, 0, 0)
        branch = session.get(WorldBranch, 1)
        assert branch is not None
        assert (branch.day, branch.time_slot, branch.state_version) == (1, "morning", 7)


@pytest.mark.parametrize("role_id", [2, 3])
async def test_role_definition_change_rejects_the_whole_turn(
    session_factory: sessionmaker[Session],
    role_id: int,
) -> None:
    with session_factory() as session:
        role = session.get(Role, role_id)
        assert role is not None
        role.base_values_json = {"level": 20}
        role.version += 1
        session.commit()

    with pytest.raises(SettlementConflictError, match="角色定义版本"):
        await SettlementService(session_factory, clock=lambda: NOW).settle(_successful_run())

    _assert_unchanged(session_factory)


async def test_commit_failure_rolls_back_everything(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_commit = Session.commit

    def fail_commit(session: Session) -> None:
        session.rollback()
        raise RuntimeError("提交前失败")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="提交前失败"):
        await SettlementService(session_factory, clock=lambda: NOW).settle(_successful_run())
    monkeypatch.setattr(Session, "commit", original_commit)

    _assert_unchanged(session_factory)


async def test_tampered_memory_over_frozen_limit_rolls_back_everything(
    session_factory: sessionmaker[Session],
) -> None:
    run = _successful_run()
    chain = run.map_runs["the_home"]
    assert chain.attribute_output is not None
    chain.attribute_output = AttributeMemoryAnalysisOutput(
        location_id="the_home",
        roles=[
            RoleAttributeMemoryOutput(
                role_id=1,
                attribute_update_intents=[],
                memory_append="篡" * 51,
            ),
            chain.attribute_output.roles[1],
        ],
    )

    with pytest.raises(ValueError, match="超过硬上限"):
        await SettlementService(session_factory, clock=lambda: NOW).settle(run)

    _assert_unchanged(session_factory)


def _assert_unchanged(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        assert _counts(session) == (0, 0, 0, 0)
        branch = session.get(WorldBranch, 1)
        assert branch is not None
        assert (branch.day, branch.time_slot, branch.state_version, branch.head_turn_id) == (
            1,
            "morning",
            7,
            None,
        )
        states = list(
            session.scalars(
                select(WorldRoleState)
                .where(WorldRoleState.world_id == 1)
                .order_by(WorldRoleState.role_id)
            )
        )
        memories = list(
            session.scalars(
                select(WorldRoleMemory)
                .where(WorldRoleMemory.world_id == 1)
                .order_by(WorldRoleMemory.role_id)
            )
        )
        assert [item.change_values_json for item in states] == [{}, {}, {}]
        assert [item.version for item in states] == [3, 3, 3]
        assert [item.memory for item in memories] == ["", "", ""]
        assert [item.version for item in memories] == [1, 1, 1]


async def test_app_lifespan_injects_the_real_settlement_handler(tmp_path: Path) -> None:
    app = create_app(AppConfig.for_local_app_data(tmp_path))

    async with app.router.lifespan_context(app):
        service = app.state.settlement_service
        manager = app.state.turn_run_manager
        assert isinstance(service, SettlementService)
        assert manager._settlement_handler == service.settle
