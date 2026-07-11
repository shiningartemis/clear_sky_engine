"""SQLite Engine 与短生命周期同步 Session。"""

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry


def _configure_sqlite_connection(
    dbapi_connection: DBAPIConnection,
    _connection_record: ConnectionPoolEntry,
) -> None:
    """每条连接都执行安全约束，避免连接池重建后悄悄丢失 PRAGMA。"""

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = FULL")
        cursor.execute("PRAGMA busy_timeout = 5000")
    finally:
        cursor.close()


def create_sqlite_engine(database_path: Path) -> Engine:
    """创建只用于本地短事务的同步 SQLite Engine。"""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    # API Key 会作为 SQL 参数持久化；即使未来启用 SQL 日志也不得输出参数值。
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        hide_parameters=True,
    )
    event.listen(engine, "connect", _configure_sqlite_connection)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Session 由调用方用上下文管理器短暂持有，绝不跨越慢 I/O。"""

    return sessionmaker(bind=engine, class_=Session, expire_on_commit=True, autoflush=False)
