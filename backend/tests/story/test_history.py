"""轮次历史的稳定排序与角色隔离查询测试。"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.character.models import Role
from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_session_factory, create_sqlite_engine
from app.story.models import StateChange, Turn, TurnEvent, TurnStory
from app.story.service import OFFLINE_STORY_CONTENT, SettlementService
from app.story.store import StoryStore
from app.world.models import World, WorldBranch, WorldRoleState

NOW = datetime(2026, 7, 18, tzinfo=UTC)


def _role(role_id: int, name: str) -> Role:
    return Role(
        id=role_id,
        name=name,
        persona="人设",
        system_prompt="提示词",
        world_book="世界书",
        base_values_json={},
        attribute_types_json={},
        attribute_labels_json={},
        attribute_descriptions_json={},
        attribute_update_rules_json={},
        attribute_constraints_json={},
        attribute_allowed_operations_json={},
        attribute_examples_json={},
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def history_factory(tmp_path: Path) -> sessionmaker[Session]:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[3] / "alembic.ini")
    factory = create_session_factory(create_sqlite_engine(config.paths.database_path))
    with factory() as session:
        session.add_all([_role(10, "主角"), _role(2, "较早 NPC"), _role(30, "离线 NPC")])
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
            day=2,
            time_slot="morning",
            current_location_id="the_home",
            state_version=3,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(branch)
        session.flush()
        world.active_branch_id = 1
        for role_id, kind in ((10, "player"), (2, "npc"), (30, "npc")):
            session.add(
                WorldRoleState(
                    world_id=1,
                    role_id=role_id,
                    kind=kind,
                    enabled=True,
                    change_values_json={},
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        parent_id: int | None = None
        for turn_id in (1, 2):
            turn = Turn(
                id=turn_id,
                world_id=1,
                branch_id=1,
                parent_turn_id=parent_id,
                day=turn_id,
                time_slot="morning",
                player_intent=f"意图 {turn_id}",
                objective_events_json=[{"event_type": "notice", "summary": f"事件 {turn_id}"}],
                state_after_json={
                    **({"protagonist_role_id": 10} if turn_id == 2 else {}),
                    "turn_positions": {
                        "10": "the_home",
                        "2": "the_home",
                        "30": "offline",
                    },
                    "after": {"day": turn_id, "time_slot": "midday"},
                },
                ai_execution_meta_json={},
                created_at=NOW,
            )
            session.add(turn)
            session.flush()
            session.add_all(
                [
                    TurnStory(
                        turn_id=turn_id,
                        role_id=10,
                        content=f"主角纪事 {turn_id}",
                        sort_order=0,
                    ),
                    TurnStory(
                        turn_id=turn_id,
                        role_id=2,
                        content=f"NPC 纪事 {turn_id}",
                        sort_order=1,
                    ),
                ]
            )
            event = TurnEvent(
                turn_id=turn_id,
                location_id="the_home",
                event_type="notice",
                fact_json={"summary": f"事件 {turn_id}"},
                created_at=NOW,
            )
            session.add(event)
            session.flush()
            session.add(
                StateChange(
                    turn_id=turn_id,
                    event_id=event.id,
                    role_id=2,
                    attribute_key="mood",
                    operation="replace",
                    old_value_json="平静",
                    operand_json="振奋",
                    new_value_json="振奋",
                    reason="听到通知",
                )
            )
            parent_id = turn_id
        branch.head_turn_id = 2
        session.commit()
    return factory


def test_history_is_newest_first_and_roles_are_player_then_stable_role_id(
    history_factory: sessionmaker[Session],
) -> None:
    history = SettlementService(history_factory, clock=lambda: NOW).list_history(world_id=1)

    assert [turn.turn_id for turn in history] == [2, 1]
    assert [[role.role_id for role in turn.roles] for turn in history] == [
        [10, 2, 30],
        [10, 2, 30],
    ]
    newest = history[0]
    assert [role.content for role in newest.roles] == [
        "主角纪事 2",
        "NPC 纪事 2",
        OFFLINE_STORY_CONTENT,
    ]
    assert newest.roles[-1].offline is True
    assert newest.events[0].fact == {"summary": "事件 2"}
    assert newest.state_changes[0].new_value == "振奋"
    assert history[1].roles[0].content == "主角纪事 1"
    assert history[1].events[0].fact == {"summary": "事件 1"}


def test_recent_five_effective_turns_only_count_turn_story(
    history_factory: sessionmaker[Session],
) -> None:
    with history_factory() as session:
        parent_id = 2
        for turn_id in range(3, 9):
            turn = Turn(
                id=turn_id,
                world_id=1,
                branch_id=1,
                parent_turn_id=parent_id,
                day=turn_id,
                time_slot="morning",
                player_intent=f"意图 {turn_id}",
                objective_events_json=[],
                state_after_json={"turn_positions": {"10": "offline"}},
                ai_execution_meta_json={},
                created_at=NOW,
            )
            session.add(turn)
            session.flush()
            if turn_id != 6:
                session.add(
                    TurnStory(
                        turn_id=turn_id,
                        role_id=10,
                        content=f"主角纪事 {turn_id}",
                        sort_order=0,
                    )
                )
            parent_id = turn_id
        session.commit()

        recent = StoryStore(session).list_recent_role_turns(
            world_id=1,
            branch_id=1,
            role_id=10,
        )

    assert [item.turn_id for item in recent] == [3, 4, 5, 7, 8]


def test_history_uses_turn_facts_after_current_role_membership_changes(
    history_factory: sessionmaker[Session],
) -> None:
    with history_factory() as session:
        old_player = session.get(WorldRoleState, 1)
        current_npc = session.get(WorldRoleState, 2)
        removed_npc = session.get(WorldRoleState, 3)
        assert old_player is not None and current_npc is not None and removed_npc is not None
        old_player.kind = "npc"
        old_player.enabled = False
        current_npc.kind = "player"
        session.delete(removed_npc)
        session.commit()

    history = SettlementService(history_factory, clock=lambda: NOW).list_history(world_id=1)

    assert [[role.role_id for role in turn.roles] for turn in history] == [
        [10, 2, 30],
        [10, 2, 30],
    ]
    assert history[0].roles[-1].content == OFFLINE_STORY_CONTENT
