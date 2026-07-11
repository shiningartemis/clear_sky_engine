"""FastAPI 应用工厂。"""

import secrets
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from app.api.application import create_application_router
from app.api.health import create_health_router
from app.config import AppConfig
from app.db.session import create_sqlite_engine
from app.security import LocalSecurity, LocalSecurityMiddleware
from app.static_site import configure_static_site


def _ignore_shutdown() -> None:
    """开发和 Schema 生成环境没有外部服务器控制器。"""


def create_app(
    config: AppConfig | None = None,
    *,
    security: LocalSecurity | None = None,
    shutdown_callback: Callable[[], None] = _ignore_shutdown,
    static_dir: Path | None = None,
) -> FastAPI:
    """创建进程内唯一应用；测试可传隔离目录，避免触碰真实用户数据。"""

    resolved_config = config or AppConfig.for_local_app_data()
    resolved_config.paths.create_directories()
    engine = create_sqlite_engine(resolved_config.paths.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        # Provider 必须共享一个连接池；关闭应用时统一释放，禁止每请求创建客户端。
        async with httpx.AsyncClient() as http_client:
            app.state.http_client = http_client
            yield
        engine.dispose()

    app = FastAPI(
        title="Clear Sky Engine",
        version=resolved_config.app_version,
        lifespan=lifespan,
    )
    app.include_router(create_health_router(engine, resolved_config.app_version))
    shutdown_token = security.shutdown_token if security else SecretStr(secrets.token_urlsafe(32))
    app.include_router(create_application_router(shutdown_token, shutdown_callback))
    if static_dir is not None:
        configure_static_site(app, static_dir)
    if security is not None:
        app.add_middleware(LocalSecurityMiddleware, security=security)
    return app
