"""轮次状态冻结与角色知识隔离测试。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.character.models import Role
from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_session_factory, create_sqlite_engine
from app.game.locations import OFFLINE, RolePresence
from app.story.models import Turn, TurnEvent, TurnEventParticipant, TurnStory
from app.workflow.context import ContextBuilder, ContextBuildError
from app.workflow.definitions import ATTRIBUTE_MEMORY_ANALYSIS
from app.workflow.schemas import (
    EventKnowledge,
    InteractionGroupOutput,
    LocationSimulationOutput,
    ObjectiveEventOutput,
    RoleChronicleOutput,
)
from app.world.models import World, WorldBranch, WorldRoleMemory, WorldRoleState

NOW = datetime(2026, 7, 17, tzinfo=UTC)


def _role(role_id: int, name: str) -> Role:
    return Role(
        id=role_id,
        name=name,
        persona=f"{name} 的人设",
        system_prompt=f"{name} 的提示词",
        world_book=f"{name} 的世界书",
        base_values_json={"level": 10},
        attribute_types_json={"level": "integer"},
        attribute_labels_json={"level": "等级"},
        attribute_descriptions_json={"level": "当前等级"},
        attribute_update_rules_json={"level": "只有明确成长才更新"},
        attribute_constraints_json={},
        attribute_allowed_operations_json={"level": ["replace", "increment"]},
        attribute_examples_json={},
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[3] / "alembic.ini")
    engine = create_sqlite_engine(config.paths.database_path)
    factory = create_session_factory(engine)

    with factory() as session:
        session.add_all(
            [
                _role(1, "主角"),
                _role(2, "同图 NPC"),
                _role(3, "异地图 NPC"),
                _role(4, "离线 NPC"),
            ]
        )
        world = World(
            id=1,
            active_branch_id=None,
            created_at=NOW,
            updated_at=NOW,
            last_played_at=NOW,
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
            day=8,
            time_slot="morning",
            current_location_id="the_home",
            state_version=8,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(branch)
        session.flush()
        world.active_branch_id = branch.id
        for role_id, kind, changes in (
            (1, "player", {"level": 2}),
            (2, "npc", {}),
            (3, "npc", {}),
            (4, "npc", {}),
        ):
            session.add(
                WorldRoleState(
                    world_id=1,
                    role_id=role_id,
                    kind=kind,
                    enabled=True,
                    change_values_json=changes,
                    version=3,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        session.flush()
        full_memory = "开端__" + "完整长期记忆" * 200
        for role_id in range(1, 5):
            session.add(
                WorldRoleMemory(
                    world_id=1,
                    role_id=role_id,
                    memory=full_memory if role_id == 1 else f"角色 {role_id} 的长期记忆",
                    version=2,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )

        parent_turn_id: int | None = None
        for turn_id in range(1, 8):
            turn = Turn(
                id=turn_id,
                world_id=1,
                branch_id=1,
                parent_turn_id=parent_turn_id,
                day=turn_id,
                time_slot="morning",
                player_intent=f"意图 {turn_id}",
                objective_events_json=[],
                state_after_json={},
                ai_execution_meta_json={},
                created_at=NOW,
            )
            session.add(turn)
            session.flush()
            # 第 2 轮主角没有 turn_story，表示当轮 offline，不应占用最近 5 个有效轮次。
            if turn_id != 2:
                session.add(
                    TurnStory(
                        turn_id=turn_id,
                        role_id=1,
                        content=f"主角自己的纪事 {turn_id}",
                        sort_order=0,
                    )
                )
            session.add(
                TurnStory(
                    turn_id=turn_id,
                    role_id=2,
                    content=f"绝不能泄露给主角的 NPC 纪事 {turn_id}",
                    sort_order=1,
                )
            )
            parent_turn_id = turn_id

        public_event = TurnEvent(
            turn_id=7,
            location_id="the_home",
            event_type="announcement",
            fact_json={"summary": "钟楼发布了公开通知"},
            created_at=NOW,
        )
        session.add(public_event)
        session.flush()
        session.add_all(
            [
                TurnEventParticipant(
                    event_id=public_event.id,
                    role_id=1,
                    knowledge_level="public",
                    perspective_notes="所有人都能听见",
                ),
                TurnEventParticipant(
                    event_id=public_event.id,
                    role_id=2,
                    knowledge_level="participant",
                    perspective_notes="在钟楼旁",
                ),
            ]
        )
        session.commit()
    return factory


def _presences() -> tuple[RolePresence, ...]:
    return (
        RolePresence(role_id=1, kind="player", location_id="the_home"),
        RolePresence(role_id=2, kind="npc", location_id="the_home"),
        RolePresence(role_id=3, kind="npc", location_id="the_school"),
        RolePresence(role_id=4, kind="npc", location_id=OFFLINE),
    )


def test_snapshot_isolates_maps_and_player_intent(
    session_factory: sessionmaker[Session],
) -> None:
    snapshot = ContextBuilder(session_factory).build_turn_snapshot(
        world_id=1,
        branch_id=1,
        day=8,
        time_slot="morning",
        player_intent="准备拜访同图 NPC",
        presences=_presences(),
    )

    contexts = {item.location_id: item for item in snapshot.locations}
    assert [role.role_id for role in contexts["the_home"].roles] == [1, 2]
    assert [role.role_id for role in contexts["the_school"].roles] == [3]
    assert contexts["the_home"].player_intent == "准备拜访同图 NPC"
    assert contexts["the_school"].player_intent is None
    assert 4 not in {role.role_id for item in snapshot.locations for role in item.roles}
    assert dict(snapshot.turn_positions) == {
        1: "the_home",
        2: "the_home",
        3: "the_school",
        4: OFFLINE,
    }
    assert snapshot.world_state_version == 8


def test_snapshot_rejects_time_that_differs_from_frozen_branch(
    session_factory: sessionmaker[Session],
) -> None:
    with pytest.raises(ContextBuildError, match="时间与分支事实不一致"):
        ContextBuilder(session_factory).build_turn_snapshot(
            world_id=1,
            branch_id=1,
            day=9,
            time_slot="night",
            player_intent="使用过期页面提交",
            presences=_presences(),
        )


def test_role_context_contains_only_own_history_and_public_knowledge(
    session_factory: sessionmaker[Session],
) -> None:
    snapshot = ContextBuilder(session_factory).build_turn_snapshot(
        world_id=1,
        branch_id=1,
        day=8,
        time_slot="morning",
        player_intent="继续行动",
        presences=_presences(),
    )
    protagonist = snapshot.locations[0].roles[0]

    assert protagonist.long_term_memory == "开端__" + "完整长期记忆" * 200
    assert [item.turn_id for item in protagonist.recent_turns] == [3, 4, 5, 6, 7]
    assert protagonist.recent_turns[0].own_chronicle == "主角自己的纪事 3"
    combined = repr(protagonist.recent_turns)
    assert "绝不能泄露给主角" not in combined
    assert "钟楼发布了公开通知" in combined
    assert protagonist.effective_attributes == {"level": 12}
    assert protagonist.attribute_update_rules == {"level": "只有明确成长才更新"}


def test_offline_turn_does_not_count_but_solo_story_does(
    session_factory: sessionmaker[Session],
) -> None:
    snapshot = ContextBuilder(session_factory).build_turn_snapshot(
        world_id=1,
        branch_id=1,
        day=8,
        time_slot="morning",
        player_intent="继续行动",
        presences=_presences(),
    )
    recent_ids = [item.turn_id for item in snapshot.locations[0].roles[0].recent_turns]

    # 第 3 轮只有该角色自己的短纪事，仍是有效轮次；第 2 轮无 turn_story，因此不计数。
    assert recent_ids == [3, 4, 5, 6, 7]


def _attribute_simulation() -> LocationSimulationOutput:
    return LocationSimulationOutput(
        location_id="the_home",
        groups=[InteractionGroupOutput(group_id="pair", role_ids=[1, 2])],
        events=[
            ObjectiveEventOutput(
                event_key="protagonist_private",
                group_id="pair",
                event_type="reflection",
                fact={
                    "summary": "只有主角知道的想法",
                    "nested": {"details": ["原始细节"]},
                },
                knowledge=[EventKnowledge(role_id=1, level="participant")],
            ),
            ObjectiveEventOutput(
                event_key="npc_private",
                group_id="pair",
                event_type="reflection",
                fact={"summary": "只有 NPC 知道的秘密"},
                knowledge=[EventKnowledge(role_id=2, level="participant")],
            ),
            ObjectiveEventOutput(
                event_key="shared_notice",
                group_id="pair",
                event_type="announcement",
                fact={"summary": "两人都听见了通知"},
                knowledge=[
                    EventKnowledge(
                        role_id=1,
                        level="observer",
                        perspective_notes="主角只听见了前半句",
                    ),
                    EventKnowledge(
                        role_id=2,
                        level="observer",
                        perspective_notes="NPC 私下听见了完整内容",
                    ),
                ],
            ),
        ],
        chronicles=[
            RoleChronicleOutput(
                role_id=1,
                content="我想起了自己的计划。",
                known_event_keys=["protagonist_private", "shared_notice"],
            ),
            RoleChronicleOutput(
                role_id=2,
                content="我保守着不告诉主角的秘密。",
                known_event_keys=["npc_private", "shared_notice"],
            ),
        ],
    )


def test_attribute_memory_context_is_partitioned_into_isolated_role_fragments(
    session_factory: sessionmaker[Session],
) -> None:
    snapshot = ContextBuilder(session_factory).build_turn_snapshot(
        world_id=1,
        branch_id=1,
        day=8,
        time_slot="morning",
        player_intent="继续行动",
        presences=_presences(),
    )
    home = next(item for item in snapshot.locations if item.location_id == "the_home")
    simulation = _attribute_simulation()

    context = ContextBuilder.build_attribute_memory_context(home, simulation)

    assert context.location_id == "the_home"
    assert [item.role_id for item in context.roles] == [1, 2]
    protagonist_fragment = context.roles[0]
    assert protagonist_fragment.chronicle.content == "我想起了自己的计划。"
    assert [item.event_key for item in protagonist_fragment.known_events] == [
        "protagonist_private",
        "shared_notice",
    ]
    assert [item.role_id for item in protagonist_fragment.known_events[1].knowledge] == [1]
    assert protagonist_fragment.effective_attributes == {"level": 12}
    assert not hasattr(context, "events")
    assert "不告诉主角的秘密" not in repr(protagonist_fragment)
    assert "只有 NPC 知道的秘密" not in repr(protagonist_fragment)
    assert "NPC 私下听见了完整内容" not in repr(protagonist_fragment)
    assert "长期记忆" not in repr(context)
    assert "异地图" not in repr(context)


def test_attribute_memory_context_deeply_freezes_location_output(
    session_factory: sessionmaker[Session],
) -> None:
    snapshot = ContextBuilder(session_factory).build_turn_snapshot(
        world_id=1,
        branch_id=1,
        day=8,
        time_slot="morning",
        player_intent="继续行动",
        presences=_presences(),
    )
    home = next(item for item in snapshot.locations if item.location_id == "the_home")
    simulation = _attribute_simulation()

    context = ContextBuilder.build_attribute_memory_context(home, simulation)
    simulation.groups[0].role_ids.append(99)
    simulation.events[0].knowledge.append(EventKnowledge(role_id=2, level="told"))
    simulation.events[0].fact["summary"] = "被修改"
    nested = simulation.events[0].fact["nested"]
    assert isinstance(nested, dict)
    details = nested["details"]
    assert isinstance(details, list)
    details.append("被修改的细节")
    simulation.chronicles[0].known_event_keys.append("npc_private")

    assert context.groups[0].role_ids == (1, 2)
    assert context.roles[0].known_events[0].knowledge[0].role_id == 1
    assert len(context.roles[0].known_events[0].knowledge) == 1
    assert context.roles[0].known_events[0].fact["summary"] == "只有主角知道的想法"
    frozen_nested = context.roles[0].known_events[0].fact["nested"]
    assert repr(frozen_nested) == "mappingproxy({'details': ('原始细节',)})"
    assert context.roles[0].chronicle.known_event_keys == (
        "protagonist_private",
        "shared_notice",
    )
    assert context.roles[0].chronicle is not simulation.chronicles[0]


def test_attribute_memory_definition_forbids_cross_fragment_references() -> None:
    assert "每个角色输出只能使用该角色自身片段" in ATTRIBUTE_MEMORY_ANALYSIS.system_prompt
    assert "禁止跨角色片段引用" in ATTRIBUTE_MEMORY_ANALYSIS.system_prompt
