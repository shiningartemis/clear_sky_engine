import socket
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from app.config import AppConfig
from app.launcher import build_server_config, open_browser, prepare_database, select_loopback_port


def test_select_loopback_port_returns_an_available_port() -> None:
    port = select_loopback_port()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_server_config_is_always_bound_to_loopback() -> None:
    server_config = build_server_config(FastAPI(), 43126)

    assert server_config.host == "127.0.0.1"
    assert server_config.port == 43126


def test_open_browser_uses_the_current_loopback_origin() -> None:
    opened_urls: list[str] = []

    def record_url(url: str) -> bool:
        opened_urls.append(url)
        return True

    result = open_browser(43127, opener=record_url)

    assert result is True
    assert opened_urls == ["http://127.0.0.1:43127/"]


def test_prepare_database_backs_up_before_upgrading(tmp_path: Path) -> None:
    config = AppConfig.for_local_app_data(tmp_path)
    config.paths.create_directories()
    config.paths.database_path.write_bytes(b"existing-database")
    operations: list[str] = []

    def backup(database_path: Path, backups_dir: Path) -> Path:
        assert database_path == config.paths.database_path
        assert backups_dir == config.paths.backups_dir
        operations.append("backup")
        return backups_dir / "backup.db"

    def upgrade(database_path: Path, alembic_ini_path: Path) -> None:
        assert database_path == config.paths.database_path
        assert alembic_ini_path.name == "alembic.ini"
        operations.append("upgrade")

    backup_function: Callable[[Path, Path], Path | None] = backup
    prepare_database(config, backup=backup_function, upgrade=upgrade)

    assert operations == ["backup", "upgrade"]
