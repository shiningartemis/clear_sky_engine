from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.config import AppConfig
from app.main import create_app
from app.security import LocalSecurity


async def test_production_security_accepts_only_the_current_loopback_host(tmp_path: Path) -> None:
    security = LocalSecurity(port=43123, shutdown_token=SecretStr("test-shutdown-token"))
    app = create_app(AppConfig.for_local_app_data(tmp_path), security=security)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url=security.origin) as client,
    ):
        accepted = await client.get("/api/health")
        rejected = await client.get("/api/health", headers={"Host": "localhost:43123"})

    assert accepted.status_code == 200
    assert rejected.status_code == 400


async def test_mutating_requests_require_the_exact_same_origin(tmp_path: Path) -> None:
    security = LocalSecurity(port=43124, shutdown_token=SecretStr("test-shutdown-token"))
    app = create_app(AppConfig.for_local_app_data(tmp_path), security=security)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url=security.origin) as client,
    ):
        missing = await client.post("/api/app/shutdown")
        foreign = await client.post(
            "/api/app/shutdown",
            headers={"Origin": "http://127.0.0.1:9999"},
        )

    assert missing.status_code == 403
    assert foreign.status_code == 403


async def test_shutdown_requires_random_token_and_notifies_launcher(tmp_path: Path) -> None:
    security = LocalSecurity(port=43125, shutdown_token=SecretStr("test-shutdown-token"))
    shutdown_requested = False

    def request_shutdown() -> None:
        nonlocal shutdown_requested
        shutdown_requested = True

    app = create_app(
        AppConfig.for_local_app_data(tmp_path),
        security=security,
        shutdown_callback=request_shutdown,
    )
    origin_header = {"Origin": security.origin}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url=security.origin) as client,
    ):
        rejected = await client.post("/api/app/shutdown", headers=origin_header)
        accepted = await client.post(
            "/api/app/shutdown",
            headers={
                **origin_header,
                "X-Clear-Sky-Shutdown-Token": security.shutdown_token.get_secret_value(),
            },
        )

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {"status": "shutting_down"}
    assert shutdown_requested is True
