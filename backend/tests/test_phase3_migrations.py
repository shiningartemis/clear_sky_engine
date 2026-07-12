from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.db.migrations import upgrade_database


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


def test_phase3_head_is_current(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    upgrade_database(database_path, Path(__file__).parents[2] / "alembic.ini")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0003_phase3_world_roles"
        )
