from importlib import import_module
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.migrations import upgrade_database
from app.db.models import Base
from app.db.session import create_sqlite_engine

NEW_TABLES = {
    "ai_task_setting",
    "world_role_memory",
    "turn",
    "turn_story",
    "turn_event",
    "turn_event_participant",
    "state_change",
}


def _alembic_config(database_path: Path) -> Config:
    alembic_ini = Path(__file__).parents[2] / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(alembic_ini.parent / "backend" / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return config


def _insert_role(connection: Connection, role_id: int, name: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO role (
                id, name, persona, system_prompt, world_book,
                base_values_json, attribute_types_json, attribute_labels_json,
                attribute_descriptions_json, attribute_update_rules_json,
                attribute_constraints_json, attribute_allowed_operations_json,
                attribute_examples_json, version, created_at, updated_at
            ) VALUES (
                :id, :name, '', '', '', '{}', '{}', '{}', '{}', '{}', '{}', '{}', '{}',
                1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ),
        {"id": role_id, "name": name},
    )


def _seed_phase3_data(connection: Connection, *, legacy_model_defaults: bool = True) -> None:
    connection.execute(
        text(
            """
            INSERT INTO ai_provider (
                id, name, provider_type, base_url, api_key, enabled, extra_json
            ) VALUES (
                1, 'Primary', 'openai_compatible', 'https://example.test/v1',
                'secret', 1, '{"region": "test"}'
            )
            """
        )
    )
    if legacy_model_defaults:
        connection.execute(
            text(
                """
                INSERT INTO ai_model (
                    id, provider_id, display_name, remote_model,
                    capabilities_json, defaults_json, enabled
                ) VALUES (
                    1, 1, 'Model A', 'model-a',
                    '{"json_output": true}', '{"temperature": 0.7}', 1
                )
                """
            )
        )
    else:
        connection.execute(
            text(
                """
                INSERT INTO ai_model (
                    id, provider_id, display_name, remote_model, capabilities_json, enabled
                ) VALUES (
                    1, 1, 'Model A', 'model-a', '{"json_output": true}', 1
                )
                """
            )
        )
    _insert_role(connection, 1, "天")
    _insert_role(connection, 2, "莫莉莉")
    connection.execute(
        text(
            """
            INSERT INTO world (id, active_branch_id, created_at, updated_at, last_played_at)
            VALUES (1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO world_branch (
                id, world_id, name, parent_branch_id, fork_turn_id, head_turn_id,
                day, time_slot, current_location_id, state_version, created_at, updated_at
            ) VALUES (
                1, 1, '主分支', NULL, NULL, NULL,
                1, 'morning', 'the_home', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )
    )
    connection.execute(text("UPDATE world SET active_branch_id = 1 WHERE id = 1"))
    connection.execute(
        text(
            """
            INSERT INTO world_role_state (
                id, world_id, role_id, kind, enabled, change_values_json,
                version, created_at, updated_at
            ) VALUES
                (1, 1, 1, 'player', 1, '{}', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                (2, 1, 2, 'npc', 1, '{}', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
    )


def _foreign_key_shape(database_path: Path, table_name: str) -> set[tuple[object, ...]]:
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        return {
            (
                tuple(item["constrained_columns"]),
                item["referred_table"],
                tuple(item["referred_columns"]),
                item.get("options", {}).get("ondelete"),
            )
            for item in inspect(engine).get_foreign_keys(table_name)
        }
    finally:
        engine.dispose()


def test_phase45_empty_database_upgrades_to_required_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"

    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert table_names >= NEW_TABLES
    assert {"turn_run", "turn_task_run"}.isdisjoint(table_names)
    assert "defaults_json" not in {column["name"] for column in inspector.get_columns("ai_model")}
    assert {item["name"] for item in inspector.get_unique_constraints("world_role_memory")} == {
        "uq_world_role_memory_world_role"
    }
    assert {item["name"] for item in inspector.get_unique_constraints("turn_story")} == {
        "uq_turn_story_turn_role"
    }
    assert {item["name"] for item in inspector.get_unique_constraints("turn")} == {
        "uq_turn_world_branch_id"
    }
    assert {item["name"] for item in inspector.get_unique_constraints("turn_event")} == {
        "uq_turn_event_turn_id_id"
    }
    assert inspector.get_pk_constraint("turn_event_participant")["constrained_columns"] == [
        "event_id",
        "role_id",
    ]
    engine.dispose()

    assert _foreign_key_shape(database_path, "world_role_memory") == {
        (("world_id", "role_id"), "world_role_state", ("world_id", "role_id"), "CASCADE")
    }
    assert _foreign_key_shape(database_path, "turn") == {
        (("world_id",), "world", ("id",), "CASCADE"),
        (("world_id", "branch_id"), "world_branch", ("world_id", "id"), "CASCADE"),
        (("parent_turn_id",), "turn", ("id",), "SET NULL"),
        (
            ("world_id", "branch_id", "parent_turn_id"),
            "turn",
            ("world_id", "branch_id", "id"),
            None,
        ),
    }
    assert _foreign_key_shape(database_path, "turn_story") == {
        (("turn_id",), "turn", ("id",), "CASCADE"),
        (("role_id",), "role", ("id",), "RESTRICT"),
    }
    assert _foreign_key_shape(database_path, "turn_event") == {
        (("turn_id",), "turn", ("id",), "CASCADE")
    }
    assert _foreign_key_shape(database_path, "turn_event_participant") == {
        (("event_id",), "turn_event", ("id",), "CASCADE"),
        (("role_id",), "role", ("id",), "RESTRICT"),
    }
    assert _foreign_key_shape(database_path, "state_change") == {
        (("turn_id",), "turn", ("id",), "CASCADE"),
        (("event_id",), "turn_event", ("id",), "SET NULL"),
        (("turn_id", "event_id"), "turn_event", ("turn_id", "id"), None),
        (("role_id",), "role", ("id",), "RESTRICT"),
    }


def test_phase45_upgrade_preserves_phase3_data_and_backfills_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "0003_phase3_world_roles")
    engine = create_sqlite_engine(database_path)
    with engine.begin() as connection:
        _seed_phase3_data(connection)
    engine.dispose()

    command.upgrade(config, "head")

    engine = create_sqlite_engine(database_path)
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT id, provider_id, display_name, remote_model, capabilities_json, enabled "
                "FROM ai_model"
            )
        ).one() == (1, 1, "Model A", "model-a", '{"json_output": true}', 1)
        assert connection.execute(text("SELECT id, name, api_key FROM ai_provider")).one() == (
            1,
            "Primary",
            "secret",
        )
        assert connection.execute(text("SELECT id, name FROM role ORDER BY id")).all() == [
            (1, "天"),
            (2, "莫莉莉"),
        ]
        assert connection.execute(text("SELECT id, active_branch_id FROM world")).one() == (1, 1)
        assert connection.execute(
            text(
                "SELECT world_id, role_id, memory, version FROM world_role_memory ORDER BY role_id"
            )
        ).all() == [(1, 1, "", 1), (1, 2, "", 1)]
        task_rows = connection.execute(
            text(
                "SELECT task_key, model_id, structured_output_mode, provider_options_json, "
                "memory_target_chars, memory_max_chars, version "
                "FROM ai_task_setting ORDER BY task_key"
            )
        ).all()
        assert task_rows == [
            ("attribute_memory_analysis", None, "auto", "{}", 20, 50, 1),
            ("location_simulation", None, "auto", "{}", None, None, 1),
        ]
    engine.dispose()


def test_phase45_downgrade_can_upgrade_again_without_losing_phase3_data(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "0003_phase3_world_roles")
    engine = create_sqlite_engine(database_path)
    with engine.begin() as connection:
        _seed_phase3_data(connection)
    engine.dispose()
    command.upgrade(config, "head")

    command.downgrade(config, "0003_phase3_world_roles")
    downgraded = create_engine(f"sqlite:///{database_path.as_posix()}")
    downgraded_inspector = inspect(downgraded)
    assert NEW_TABLES.isdisjoint(downgraded_inspector.get_table_names())
    assert "defaults_json" in {
        column["name"] for column in downgraded_inspector.get_columns("ai_model")
    }
    downgraded.dispose()

    command.upgrade(config, "head")
    engine = create_sqlite_engine(database_path)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM ai_provider")).scalar_one() == "Primary"
        assert (
            connection.execute(text("SELECT remote_model FROM ai_model")).scalar_one() == "model-a"
        )
        assert connection.execute(text("SELECT COUNT(*) FROM world_role_memory")).scalar_one() == 2
    engine.dispose()


def test_phase45_database_constraints_and_cascades_are_enforced(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    engine = create_sqlite_engine(database_path)
    with engine.begin() as connection:
        _seed_phase3_data(connection, legacy_model_defaults=False)
        connection.execute(
            text(
                "INSERT INTO world_role_memory "
                "(world_id, role_id, memory, version, created_at, updated_at) "
                "SELECT world_id, role_id, '', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "FROM world_role_state"
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ai_task_setting "
                "(task_key, model_id, timeout_seconds, extra_prompt, structured_output_mode, "
                "provider_options_json, version, updated_at) "
                "VALUES ('unknown', NULL, 120, '', 'auto', '{}', 1, CURRENT_TIMESTAMP)"
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ai_task_setting SET memory_target_chars = 51, memory_max_chars = 50 "
                "WHERE task_key = 'attribute_memory_analysis'"
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO world_role_memory "
                "(world_id, role_id, memory, version, created_at, updated_at) "
                "VALUES (1, 1, '', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO world_role_memory "
                "(world_id, role_id, memory, version, created_at, updated_at) "
                "VALUES (1, 999, '', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM world_role_state WHERE world_id = 1 AND role_id = 2"))
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM world_role_memory WHERE world_id = 1 AND role_id = 2")
            ).scalar_one()
            == 0
        )
        connection.execute(text("DELETE FROM world WHERE id = 1"))
        assert connection.execute(text("SELECT COUNT(*) FROM world_role_memory")).scalar_one() == 0
    engine.dispose()


def test_phase45_turn_checks_and_delete_actions_are_enforced(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    engine = create_sqlite_engine(database_path)
    with engine.begin() as connection:
        _seed_phase3_data(connection, legacy_model_defaults=False)
        _insert_role(connection, 4, "历史见证者")
        connection.execute(
            text("UPDATE ai_task_setting SET model_id = 1 WHERE task_key = 'location_simulation'")
        )
        connection.execute(
            text(
                """
                INSERT INTO turn (
                    id, world_id, branch_id, parent_turn_id, day, time_slot, player_intent,
                    objective_events_json, state_after_json, ai_execution_meta_json, created_at
                ) VALUES (
                    1, 1, 1, NULL, 1, 'morning', '观察', '[]', '{}', '{}', CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO turn_story (id, turn_id, role_id, content, sort_order)
                VALUES
                    (1, 1, 1, '天观察四周。', 0),
                    (2, 1, 4, '见证者看见了这一幕。', 1)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO turn_event (id, turn_id, location_id, event_type, fact_json, created_at)
                VALUES (1, 1, 'the_home', 'observation', '{}', CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO turn (
                    id, world_id, branch_id, parent_turn_id, day, time_slot, player_intent,
                    objective_events_json, state_after_json, ai_execution_meta_json, created_at
                ) VALUES (
                    2, 1, 1, 1, 1, 'midday', '继续观察', '[]', '{}', '{}', CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO turn_event_participant (
                    event_id, role_id, knowledge_level, perspective_notes
                ) VALUES (1, 1, 'participant', '')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO state_change (
                    id, turn_id, event_id, role_id, attribute_key, operation,
                    old_value_json, operand_json, new_value_json, reason
                ) VALUES (1, 1, 1, 1, 'level', 'replace', '1', '2', '2', '观察所得')
                """
            )
        )

    invalid_updates = (
        "UPDATE turn SET day = 0 WHERE id = 1",
        "UPDATE turn SET time_slot = 'dawn' WHERE id = 1",
        "UPDATE turn_story SET sort_order = -1 WHERE id = 1",
        "UPDATE turn_event SET location_id = 'offline' WHERE id = 1",
        "UPDATE turn_event_participant SET knowledge_level = 'omniscient' WHERE event_id = 1",
        "UPDATE state_change SET operation = 'multiply' WHERE id = 1",
    )
    for statement in invalid_updates:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text(statement))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO turn_story (turn_id, role_id, content, sort_order)
                VALUES (1, 1, '重复纪事', 1)
                """
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM ai_model WHERE id = 1"))
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text("DELETE FROM role WHERE id = 4"))

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM turn_event WHERE id = 1"))
        assert (
            connection.execute(text("SELECT COUNT(*) FROM turn_event_participant")).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT event_id FROM state_change WHERE id = 1")
            ).scalar_one_or_none()
            is None
        )
        connection.execute(text("DELETE FROM turn WHERE id = 1"))
        assert connection.execute(text("SELECT COUNT(*) FROM turn_story")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM state_change")).scalar_one() == 0
        assert (
            connection.execute(
                text("SELECT parent_turn_id FROM turn WHERE id = 2")
            ).scalar_one_or_none()
            is None
        )
        connection.execute(
            text(
                """
                INSERT INTO turn_story (id, turn_id, role_id, content, sort_order)
                VALUES (2, 2, 1, '天再次观察。', 0)
                """
            )
        )
        connection.execute(text("UPDATE world SET active_branch_id = NULL WHERE id = 1"))
        connection.execute(text("DELETE FROM world WHERE id = 1"))
        assert connection.execute(text("SELECT COUNT(*) FROM turn")).scalar_one() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM turn_story")).scalar_one() == 0
    engine.dispose()


def test_phase45_orm_models_expose_the_persistent_contract() -> None:
    for module_name in ("app.workflow.models", "app.story.models"):
        import_module(module_name)
    import_module("app.ai.models")
    import_module("app.world.models")

    assert set(Base.metadata.tables) >= NEW_TABLES
    assert "defaults_json" not in Base.metadata.tables["ai_model"].columns
    memory = Base.metadata.tables["world_role_memory"]
    assert {constraint.name for constraint in memory.constraints} >= {
        "ck_world_role_memory_version",
        "uq_world_role_memory_world_role",
    }
    assert memory.c.memory.default is not None
    assert memory.c.version.default is not None
    state_change = Base.metadata.tables["state_change"]
    assert state_change.c.old_value_json.nullable is False
    assert state_change.c.operand_json.nullable is False
    assert state_change.c.new_value_json.nullable is False


def test_phase45_rejects_cross_world_branch_parent_and_event_links(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    engine = create_sqlite_engine(database_path)
    with engine.begin() as connection:
        _seed_phase3_data(connection, legacy_model_defaults=False)
        _insert_role(connection, 3, "安可儿")
        connection.execute(
            text(
                """
                INSERT INTO world (id, active_branch_id, created_at, updated_at, last_played_at)
                VALUES (2, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO world_branch (
                    id, world_id, name, parent_branch_id, fork_turn_id, head_turn_id,
                    day, time_slot, current_location_id, state_version, created_at, updated_at
                ) VALUES (
                    2, 2, '主分支', NULL, NULL, NULL,
                    1, 'morning', 'the_home', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(text("UPDATE world SET active_branch_id = 2 WHERE id = 2"))
        connection.execute(
            text(
                """
                INSERT INTO world_role_state (
                    id, world_id, role_id, kind, enabled, change_values_json,
                    version, created_at, updated_at
                ) VALUES (
                    3, 2, 3, 'player', 1, '{}', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO turn (
                    id, world_id, branch_id, parent_turn_id, day, time_slot, player_intent,
                    objective_events_json, state_after_json, ai_execution_meta_json, created_at
                ) VALUES
                    (1, 1, 1, NULL, 1, 'morning', '等待', '[]', '{}', '{}', CURRENT_TIMESTAMP),
                    (2, 2, 2, NULL, 1, 'morning', '等待', '[]', '{}', '{}', CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO turn_event (id, turn_id, location_id, event_type, fact_json, created_at)
                VALUES (1, 1, 'the_home', 'observation', '{}', CURRENT_TIMESTAMP)
                """
            )
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO turn (
                    world_id, branch_id, parent_turn_id, day, time_slot, player_intent,
                    objective_events_json, state_after_json, ai_execution_meta_json, created_at
                ) VALUES (
                    1, 2, NULL, 1, 'morning', '跨世界分支', '[]', '{}', '{}', CURRENT_TIMESTAMP
                )
                """
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO turn (
                    world_id, branch_id, parent_turn_id, day, time_slot, player_intent,
                    objective_events_json, state_after_json, ai_execution_meta_json, created_at
                ) VALUES (
                    1, 1, 2, 1, 'morning', '跨世界父轮次', '[]', '{}', '{}', CURRENT_TIMESTAMP
                )
                """
            )
        )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO state_change (
                    turn_id, event_id, role_id, attribute_key, operation,
                    old_value_json, operand_json, new_value_json, reason
                ) VALUES (
                    2, 1, 3, 'level', 'replace', '1', '2', '2', '跨轮次事件'
                )
                """
            )
        )
    engine.dispose()
