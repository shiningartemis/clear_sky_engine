"""Windows 本地生产启动器。"""

import argparse
import secrets
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import SecretStr

from app.config import AppConfig
from app.db.migrations import backup_database, upgrade_database
from app.main import create_app
from app.resources import resource_root
from app.security import LocalSecurity

BackupFunction = Callable[[Path, Path], Path | None]
UpgradeFunction = Callable[[Path, Path], None]
BrowserOpener = Callable[[str], bool]


class LauncherArguments(argparse.Namespace):
    smoke_test: bool = False


def parse_arguments(arguments: Sequence[str]) -> LauncherArguments:
    parser = argparse.ArgumentParser(prog="ClearSkyEngine")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "Start with temporary data, verify loopback health, and exit without opening a browser."
        ),
    )
    parsed = parser.parse_args(arguments, namespace=LauncherArguments())
    return parsed


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
    alembic_ini_path = resource_root() / "alembic.ini"
    upgrade(config.paths.database_path, alembic_ini_path)


def _run_application(config: AppConfig, *, smoke_test: bool) -> None:
    """启动服务线程，并由主线程协调浏览器、自检与安全退出。"""

    prepare_database(config)
    print(f"SQLite {sqlite3.sqlite_version}")

    port = select_loopback_port()
    security = LocalSecurity(port=port, shutdown_token=SecretStr(secrets.token_urlsafe(32)))
    shutdown_requested = threading.Event()
    static_dir = resource_root() / "backend" / "src" / "app" / "static"
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
        if smoke_test:
            health_response = httpx.get(f"{security.origin}/api/health", timeout=5)
            health_response.raise_for_status()
            page_response = httpx.get(f"{security.origin}/", timeout=5)
            page_response.raise_for_status()
            if "<title>Clear Sky Engine</title>" not in page_response.text:
                raise RuntimeError("Packaged static page did not match the expected application.")
            shutdown_requested.set()
        else:
            open_browser(port)

        while server_thread.is_alive():
            if shutdown_requested.wait(0.1):
                server.should_exit = True
                break
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)


def run(*, smoke_test: bool = False) -> None:
    """冒烟模式隔离全部数据；普通模式只使用 LocalAppData。"""

    if smoke_test:
        with TemporaryDirectory(prefix="clear-sky-package-smoke-") as temporary_directory:
            _run_application(
                AppConfig.for_local_app_data(Path(temporary_directory)),
                smoke_test=True,
            )
        return
    _run_application(AppConfig.for_local_app_data(), smoke_test=False)


def main(arguments: Sequence[str] | None = None) -> None:
    parsed_arguments = parse_arguments(sys.argv[1:] if arguments is None else arguments)
    run(smoke_test=parsed_arguments.smoke_test)


if __name__ == "__main__":
    main()
