from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.db.migrations import backup_database, upgrade_database


def test_backup_database_copies_an_existing_database(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "app.db"
    backups_dir = tmp_path / "backups"
    database_path.parent.mkdir(parents=True)
    database_path.write_bytes(b"database-content")

    backup_path = backup_database(database_path, backups_dir)

    assert backup_path is not None
    assert backup_path.parent == backups_dir
    assert backup_path.name.startswith("app-")
    assert backup_path.suffix == ".db"
    assert backup_path.read_bytes() == b"database-content"


def test_backup_database_skips_a_missing_database(tmp_path: Path) -> None:
    backup_path = backup_database(tmp_path / "missing.db", tmp_path / "backups")

    assert backup_path is None


def test_empty_database_upgrades_to_alembic_head(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    alembic_ini = Path(__file__).parents[2] / "alembic.ini"

    upgrade_database(database_path, alembic_ini)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    assert "alembic_version" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0003_phase3_world_roles"
        )


def test_existing_initial_database_upgrades_to_current_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    alembic_ini = Path(__file__).parents[2] / "alembic.ini"
    alembic_config = Config(str(alembic_ini))
    alembic_config.set_main_option(
        "script_location", str(alembic_ini.parent / "backend" / "migrations")
    )
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(alembic_config, "0001_initial")

    upgrade_database(database_path, alembic_ini)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    assert {"ai_provider", "ai_model"}.issubset(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "0003_phase3_world_roles"
        )
