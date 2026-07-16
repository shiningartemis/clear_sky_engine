"""FastAPI 应用工厂。"""

import secrets
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from pydantic import SecretStr

from app.ai.contracts import ProviderRegistry
from app.ai.deepseek import DeepSeekProvider
from app.ai.openai_compatible import OpenAICompatibleProvider
from app.ai.service import AiSettingsService
from app.api.ai_tasks import create_ai_task_router, safe_request_validation_error
from app.api.application import create_application_router
from app.api.assets import create_asset_router
from app.api.health import create_health_router
from app.api.providers import create_provider_router
from app.api.roles import create_role_router
from app.api.worlds import create_world_router
from app.character.service import RoleService
from app.config import AppConfig
from app.db.session import create_session_factory, create_sqlite_engine
from app.resources import resource_root
from app.resources.bootstrap import ensure_default_maps
from app.resources.catalog import ResourceCatalog
from app.security import LocalSecurity, LocalSecurityMiddleware
from app.static_site import configure_static_site
from app.world.service import WorldService


def _ignore_shutdown() -> None:
    """开发和 Schema 生成环境没有外部服务器控制器。"""


def create_app(
    config: AppConfig | None = None,
    *,
    security: LocalSecurity | None = None,
    shutdown_callback: Callable[[], None] = _ignore_shutdown,
    static_dir: Path | None = None,
    resource_directory: Path | None = None,
) -> FastAPI:
    """创建进程内唯一应用；测试可传隔离目录，避免触碰真实用户数据。"""

    resolved_config = config or AppConfig.for_local_app_data()
    resolved_config.paths.create_directories()
    runtime_root = resource_directory or resource_root()
    default_maps_dir = (
        runtime_root / "backend" / "src" / "app" / "resources" / "default_content" / "maps"
    )
    ensure_default_maps(default_maps_dir, resolved_config.paths.maps_dir)
    resource_catalog = ResourceCatalog(
        resolved_config.paths.maps_dir,
        resolved_config.paths.characters_dir,
        default_maps_dir,
    )
    engine = create_sqlite_engine(resolved_config.paths.database_path)
    session_factory = create_session_factory(engine)
    ai_settings_service = AiSettingsService(session_factory)
    role_service = RoleService(session_factory, resource_catalog)
    world_service = WorldService(session_factory, resource_catalog)
    provider_registry: ProviderRegistry | None = None

    def get_provider_registry() -> ProviderRegistry:
        if provider_registry is None:
            raise RuntimeError("ProviderRegistry 尚未初始化")
        return provider_registry

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        nonlocal provider_registry
        # Provider 必须共享一个连接池；关闭应用时统一释放，禁止每请求创建客户端。
        async with httpx.AsyncClient() as http_client:
            app.state.http_client = http_client
            provider_registry = ProviderRegistry(
                [OpenAICompatibleProvider(http_client), DeepSeekProvider(http_client)]
            )
            yield
            provider_registry = None
        engine.dispose()

    app = FastAPI(
        title="Clear Sky Engine",
        version=resolved_config.app_version,
        lifespan=lifespan,
    )
    # 默认 422 会回显原始 input；全局剥离它，避免任何 DTO 错误泄漏 API Key。
    app.add_exception_handler(RequestValidationError, safe_request_validation_error)
    app.include_router(create_health_router(engine, resolved_config.app_version))
    app.include_router(create_provider_router(ai_settings_service, get_provider_registry))
    app.include_router(create_ai_task_router(ai_settings_service))
    app.include_router(create_role_router(role_service))
    app.include_router(create_world_router(world_service))
    app.include_router(create_asset_router(resource_catalog))
    shutdown_token = security.shutdown_token if security else SecretStr(secrets.token_urlsafe(32))
    app.include_router(create_application_router(shutdown_token, shutdown_callback))
    if static_dir is not None:
        configure_static_site(app, static_dir)
    if security is not None:
        app.add_middleware(LocalSecurityMiddleware, security=security)
    return app
