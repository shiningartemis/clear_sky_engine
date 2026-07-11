from pathlib import Path

from sqlalchemy import text

from app.config import AppPaths
from app.db.session import create_session_factory, create_sqlite_engine


def test_sqlite_connections_enable_required_pragmas(tmp_path: Path) -> None:
    paths = AppPaths.from_local_app_data(tmp_path)
    paths.create_directories()
    engine = create_sqlite_engine(paths.database_path)

    with engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        synchronous = connection.execute(text("PRAGMA synchronous")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()

    assert foreign_keys == 1
    assert journal_mode == "wal"
    assert synchronous == 2
    assert busy_timeout == 5000


def test_session_factory_uses_short_expiring_sessions(tmp_path: Path) -> None:
    paths = AppPaths.from_local_app_data(tmp_path)
    paths.create_directories()
    engine = create_sqlite_engine(paths.database_path)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1
        assert session.expire_on_commit is True
