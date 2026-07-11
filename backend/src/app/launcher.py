"""Windows 本地生产启动器。"""

import secrets
import socket
import sqlite3
import threading
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from pydantic import SecretStr

from app.config import AppConfig
from app.db.migrations import backup_database, upgrade_database
from app.main import create_app
from app.security import LocalSecurity

BackupFunction = Callable[[Path, Path], Path | None]
UpgradeFunction = Callable[[Path, Path], None]
BrowserOpener = Callable[[str], bool]


def select_loopback_port() -> int:
    """由操作系统选择空闲端口；端口只用于随后同一进程的本地绑定。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def build_server_config(app: FastAPI, port: int) -> uvicorn.Config:
    """绑定地址是安全边界，不接受命令行覆盖为局域网地址。"""

    return uvicorn.Config(app=app, host="127.0.0.1", port=port, log_level="info")


def open_browser(port: int, opener: BrowserOpener = webbrowser.open) -> bool:
    return opener(f"http://127.0.0.1:{port}/")


def prepare_database(
    config: AppConfig,
    *,
    backup: BackupFunction = backup_database,
    upgrade: UpgradeFunction = upgrade_database,
) -> None:
    """备份必须先于迁移，升级失败时保留原始数据库副本。"""

    config.paths.create_directories()
    backup(config.paths.database_path, config.paths.backups_dir)
    alembic_ini_path = Path(__file__).parents[3] / "alembic.ini"
    upgrade(config.paths.database_path, alembic_ini_path)


def run() -> None:
    """启动一个本地服务线程并由主线程协调浏览器与安全退出。"""

    config = AppConfig.for_local_app_data()
    prepare_database(config)
    print(f"SQLite {sqlite3.sqlite_version}")

    port = select_loopback_port()
    security = LocalSecurity(port=port, shutdown_token=SecretStr(secrets.token_urlsafe(32)))
    shutdown_requested = threading.Event()
    static_dir = Path(__file__).parent / "static"
    app = create_app(
        config,
        security=security,
        shutdown_callback=shutdown_requested.set,
        static_dir=static_dir,
    )
    server = uvicorn.Server(build_server_config(app, port))
    server_thread = threading.Thread(target=server.run, name="clear-sky-uvicorn")
    server_thread.start()

    try:
        deadline = time.monotonic() + 10
        while server_thread.is_alive() and not server.started:
            if time.monotonic() >= deadline:
                raise RuntimeError("Local server did not start within 10 seconds.")
            time.sleep(0.05)

        if not server.started:
            raise RuntimeError("Local server stopped before startup completed.")
        open_browser(port)

        while server_thread.is_alive():
            if shutdown_requested.wait(0.1):
                server.should_exit = True
                break
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)


if __name__ == "__main__":
    run()
