from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, event, inspect, text
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import ConnectionPoolEntry

from app.db.migrations import upgrade_database
from app.db.session import create_sqlite_engine


def _alembic_config(database_path: Path) -> Config:
    alembic_ini = Path(__file__).parents[2] / "alembic.ini"
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(alembic_ini.parent / "backend" / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return config


def _enable_foreign_keys(
    dbapi_connection: DBAPIConnection,
    _connection_record: ConnectionPoolEntry,
) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()


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


def _insert_world(connection: Connection, world_id: int, branch_id: int) -> None:
    connection.execute(
        text(
            """
            INSERT INTO world (id, active_branch_id, created_at, updated_at, last_played_at)
            VALUES (:world_id, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ),
        {"world_id": world_id},
    )
    connection.execute(
        text(
            """
            INSERT INTO world_branch (
                id, world_id, name, parent_branch_id, fork_turn_id, head_turn_id,
                day, time_slot, current_location_id, state_version, created_at, updated_at
            ) VALUES (
                :branch_id, :world_id, 'main', NULL, NULL, NULL,
                1, 'morning', 'the_home', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ),
        {"branch_id": branch_id, "world_id": world_id},
    )
    connection.execute(
        text("UPDATE world SET active_branch_id = :branch_id WHERE id = :world_id"),
        {"branch_id": branch_id, "world_id": world_id},
    )


def _insert_world_role(
    connection: Connection,
    state_id: int,
    world_id: int,
    role_id: int,
    kind: str,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO world_role_state (
                id, world_id, role_id, kind, enabled, change_values_json,
                version, created_at, updated_at
            ) VALUES (
                :state_id, :world_id, :role_id, :kind, 1, '{}',
                1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        ),
        {"state_id": state_id, "world_id": world_id, "role_id": role_id, "kind": kind},
    )


def _seed_linked_phase3_data(connection: Connection) -> None:
    for role_id in range(1, 5):
        _insert_role(connection, role_id, f"role-{role_id}")
    _insert_world(connection, 1, 10)
    _insert_world(connection, 2, 20)
    _insert_world_role(connection, 100, 1, 1, "player")
    _insert_world_role(connection, 101, 1, 2, "npc")
    _insert_world_role(connection, 200, 2, 3, "player")
    connection.execute(
        text(
            """
            INSERT INTO character_location_rule (
                id, world_id, role_id, weekday_mask, time_slot, mode, priority, enabled
            ) VALUES (1000, 1, 2, 1, 'morning', 'fixed', 1, 1)
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO character_location_candidate (id, rule_id, location_id, weight)
            VALUES (10000, 1000, 'the_home', 1)
            """
        )
    )


def test_phase3_schema_has_required_tables_and_unique_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)

    assert {
        "role",
        "world",
        "world_branch",
        "world_role_state",
        "character_location_rule",
        "character_location_candidate",
    }.issubset(inspector.get_table_names())
    branch_columns = {column["name"] for column in inspector.get_columns("world_branch")}
    assert {"parent_branch_id", "fork_turn_id", "head_turn_id"}.issubset(branch_columns)
    unique_sets = {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints("world_role_state")
    }
    assert ("world_id", "role_id") in unique_sets


def test_phase3_database_upgrades_to_current_head(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0004_merged_turn_loop"
        )


def test_phase3_schema_has_exact_checks_indexes_and_foreign_keys(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    inspector = inspect(create_sqlite_engine(database_path))

    expected_checks = {
        "world_branch": {
            "ck_world_branch_day",
            "ck_world_branch_time_slot",
            "ck_world_branch_current_location",
        },
        "world_role_state": {"ck_world_role_state_kind"},
        "character_location_rule": {
            "ck_location_rule_weekday_mask",
            "ck_location_rule_mode",
        },
        "character_location_candidate": {"ck_location_candidate_weight"},
    }
    for table_name, check_names in expected_checks.items():
        assert {item["name"] for item in inspector.get_check_constraints(table_name)} == check_names

    player_index = next(
        item
        for item in inspector.get_indexes("world_role_state")
        if item["name"] == "uq_world_role_state_player"
    )
    assert player_index["unique"] == 1
    assert player_index["column_names"] == ["world_id"]
    assert "dialect_options" in player_index
    assert str(player_index["dialect_options"]["sqlite_where"]) == "kind = 'player'"

    expected_foreign_keys = {
        "world": {(("active_branch_id",), ("world_branch", ("id",)), "RESTRICT")},
        "world_branch": {
            (("world_id",), ("world", ("id",)), "CASCADE"),
            (("parent_branch_id",), ("world_branch", ("id",)), "RESTRICT"),
        },
        "world_role_state": {
            (("world_id",), ("world", ("id",)), "CASCADE"),
            (("role_id",), ("role", ("id",)), "RESTRICT"),
        },
        "character_location_rule": {
            (
                ("world_id", "role_id"),
                ("world_role_state", ("world_id", "role_id")),
                "CASCADE",
            )
        },
        "character_location_candidate": {
            (("rule_id",), ("character_location_rule", ("id",)), "CASCADE")
        },
    }
    for table_name, expected in expected_foreign_keys.items():
        reflected_foreign_keys = inspector.get_foreign_keys(table_name)
        actual: set[tuple[tuple[str, ...], tuple[str, tuple[str, ...]], str]] = set()
        for item in reflected_foreign_keys:
            assert "options" in item
            actual.add(
                (
                    tuple(item["constrained_columns"]),
                    (item["referred_table"], tuple(item["referred_columns"])),
                    item["options"]["ondelete"],
                )
            )
        assert actual == expected


def test_phase3_constraints_reject_invalid_and_cross_world_data(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    engine = create_sqlite_engine(database_path)
    with engine.begin() as connection:
        _seed_linked_phase3_data(connection)

        invalid_statements = [
            """
            INSERT INTO world_branch (
                id, world_id, name, day, time_slot, current_location_id,
                state_version, created_at, updated_at
            ) VALUES (11, 1, 'bad-day', 0, 'morning', 'the_home', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            """
            INSERT INTO world_branch (
                id, world_id, name, day, time_slot, current_location_id,
                state_version, created_at, updated_at
            ) VALUES (12, 1, 'bad-time', 1, 'dawn', 'the_home', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            """
            INSERT INTO world_branch (
                id, world_id, name, day, time_slot, current_location_id,
                state_version, created_at, updated_at
            ) VALUES (13, 1, 'bad-location', 1, 'morning', 'unknown', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            """
            INSERT INTO world_role_state (
                id, world_id, role_id, kind, enabled, change_values_json,
                version, created_at, updated_at
            ) VALUES (102, 1, 4, 'observer', 1, '{}', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            """
            INSERT INTO character_location_rule (
                id, world_id, role_id, weekday_mask, time_slot, mode, priority, enabled
            ) VALUES (1001, 1, 2, 0, 'morning', 'fixed', 1, 1)
            """,
            """
            INSERT INTO character_location_rule (
                id, world_id, role_id, weekday_mask, time_slot, mode, priority, enabled
            ) VALUES (1002, 1, 2, 1, 'morning', 'scripted', 1, 1)
            """,
            """
            INSERT INTO character_location_candidate (id, rule_id, location_id, weight)
            VALUES (10001, 1000, 'the_school', 0)
            """,
            """
            INSERT INTO world_role_state (
                id, world_id, role_id, kind, enabled, change_values_json,
                version, created_at, updated_at
            ) VALUES (103, 1, 4, 'player', 1, '{}', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            """
            INSERT INTO character_location_rule (
                id, world_id, role_id, weekday_mask, time_slot, mode, priority, enabled
            ) VALUES (1003, 1, 3, 1, 'morning', 'fixed', 1, 1)
            """,
            """
            INSERT INTO character_location_candidate (id, rule_id, location_id, weight)
            VALUES (10002, 1000, 'the_home', 2)
            """,
        ]
        for statement in invalid_statements:
            with pytest.raises(IntegrityError):
                connection.execute(text(statement))


def test_phase3_ondelete_actions_are_enforced(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    engine = create_sqlite_engine(database_path)
    with engine.begin() as connection:
        _seed_linked_phase3_data(connection)

        with pytest.raises(IntegrityError):
            connection.execute(text("DELETE FROM role WHERE id = 2"))
        with pytest.raises(IntegrityError):
            connection.execute(text("DELETE FROM world_branch WHERE id = 10"))

        connection.execute(text("DELETE FROM world_role_state WHERE id = 101"))
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM character_location_rule WHERE id = 1000")
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM character_location_candidate WHERE id = 10000")
            ).scalar_one()
            == 0
        )


def test_phase3_downgrade_with_linked_data_and_foreign_keys_enabled(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    engine = create_sqlite_engine(database_path)
    with engine.begin() as connection:
        _seed_linked_phase3_data(connection)
    engine.dispose()

    event.listen(Engine, "connect", _enable_foreign_keys)
    try:
        command.downgrade(_alembic_config(database_path), "0002_ai_providers")
    finally:
        event.remove(Engine, "connect", _enable_foreign_keys)

    engine = create_sqlite_engine(database_path)
    assert {
        "role",
        "world",
        "world_branch",
        "world_role_state",
        "character_location_rule",
        "character_location_candidate",
    }.isdisjoint(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0002_ai_providers"
        )
