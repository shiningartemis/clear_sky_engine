import sqlite3
from pathlib import Path
from typing import cast

import httpx
from httpx import ASGITransport, AsyncClient

from app.config import AppConfig
from app.main import create_app


async def test_health_reports_application_database_and_sqlite_version(tmp_path: Path) -> None:
    config = AppConfig.for_local_app_data(tmp_path)
    app = create_app(config)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        response = await client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "status": "ok",
        "app_version": "0.1.0",
        "database": "ok",
        "sqlite_version": sqlite3.sqlite_version,
    }


async def test_application_owns_one_http_client_for_its_lifetime(tmp_path: Path) -> None:
    config = AppConfig.for_local_app_data(tmp_path)
    app = create_app(config)

    async with app.router.lifespan_context(app):
        http_client = cast(httpx.AsyncClient, app.state.http_client)
        assert http_client.is_closed is False

    assert http_client.is_closed is True
