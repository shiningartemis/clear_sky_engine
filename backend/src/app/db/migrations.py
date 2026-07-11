"""数据库升级前备份与 Alembic 执行入口。"""

import shutil
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config


def backup_database(database_path: Path, backups_dir: Path) -> Path | None:
    """升级前复制已有数据库；不存在的空库无需制造伪备份。"""

    if not database_path.is_file():
        return None

    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backups_dir / f"{database_path.stem}-{timestamp}{database_path.suffix}"
    shutil.copy2(database_path, backup_path)
    return backup_path


def upgrade_database(database_path: Path, alembic_ini_path: Path) -> None:
    """从任意当前版本升级到 head，Schema 变化只允许从此入口进入。"""

    database_path.parent.mkdir(parents=True, exist_ok=True)
    alembic_config = Config(str(alembic_ini_path))
    alembic_config.set_main_option(
        "script_location", str(alembic_ini_path.parent / "backend" / "migrations")
    )
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    command.upgrade(alembic_config, "head")
