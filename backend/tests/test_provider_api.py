from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.ai.service import AiSettingsConflictError, AiSettingsService
from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_session_factory, create_sqlite_engine
from app.main import create_app


@asynccontextmanager
async def provider_client(tmp_path: Path) -> AsyncGenerator[AsyncClient]:
    config = AppConfig.for_local_app_data(tmp_path)
    alembic_ini = Path(__file__).parents[2] / "alembic.ini"
    upgrade_database(config.paths.database_path, alembic_ini)
    app = create_app(config)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        yield client


async def test_provider_crud_never_returns_api_key(tmp_path: Path) -> None:
    async with provider_client(tmp_path) as client:
        created = await client.post(
            "/api/providers",
            json={
                "name": "Primary",
                "provider_type": "openai_compatible",
                "base_url": "https://example.test/v1",
                "api_key": "secret-create-key",
                "enabled": True,
                "extra": {"organization": "example"},
            },
        )
        assert created.status_code == 201
        provider = created.json()
        assert provider["has_api_key"] is True
        assert "api_key" not in provider
        assert "secret-create-key" not in created.text

        listed = await client.get("/api/providers")
        assert listed.status_code == 200
        assert listed.json() == [provider]
        assert "secret-create-key" not in listed.text

        replaced = await client.patch(
            f"/api/providers/{provider['id']}", json={"api_key": "secret-replacement-key"}
        )
        assert replaced.status_code == 200
        assert replaced.json()["has_api_key"] is True
        assert "secret-replacement-key" not in replaced.text

        cleared = await client.patch(f"/api/providers/{provider['id']}", json={"api_key": None})
        assert cleared.status_code == 200
        assert cleared.json()["has_api_key"] is False

        deleted = await client.delete(f"/api/providers/{provider['id']}")
        assert deleted.status_code == 204
        missing = await client.get(f"/api/providers/{provider['id']}")
        assert missing.status_code == 404


async def test_model_crud_and_provider_delete_cascade(tmp_path: Path) -> None:
    async with provider_client(tmp_path) as client:
        provider_response = await client.post(
            "/api/providers",
            json={
                "name": "DeepSeek",
                "provider_type": "deepseek",
                "base_url": "https://api.deepseek.com",
                "enabled": True,
            },
        )
        provider_id = provider_response.json()["id"]
        created = await client.post(
            "/api/models",
            json={
                "provider_id": provider_id,
                "display_name": "DeepSeek V4 Pro",
                "remote_model": "deepseek-v4-pro",
                "capabilities": {"reasoning": True, "tools": True},
                "defaults": {"temperature": 0.7},
                "enabled": True,
            },
        )
        assert created.status_code == 201
        model = created.json()

        listed = await client.get("/api/models", params={"provider_id": provider_id})
        assert listed.status_code == 200
        assert listed.json() == [model]

        updated = await client.patch(
            f"/api/models/{model['id']}", json={"display_name": "DeepSeek V4 Pro Updated"}
        )
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "DeepSeek V4 Pro Updated"

        deleted_provider = await client.delete(f"/api/providers/{provider_id}")
        assert deleted_provider.status_code == 204
        assert (await client.get("/api/models", params={"provider_id": provider_id})).json() == []


async def test_conflicts_roll_back_without_leaking_api_key(tmp_path: Path) -> None:
    async with provider_client(tmp_path) as client:
        payload = {
            "name": "Primary",
            "provider_type": "openai_compatible",
            "base_url": "https://example.test/v1",
            "api_key": "never-log-this-key",
            "enabled": True,
        }
        first = await client.post("/api/providers", json=payload)
        assert first.status_code == 201

        duplicate = await client.post("/api/providers", json=payload)
        assert duplicate.status_code == 409
        assert "never-log-this-key" not in duplicate.text

        listed = await client.get("/api/providers")
        assert len(listed.json()) == 1


def test_conflict_exception_drops_sensitive_database_context(tmp_path: Path) -> None:
    config = AppConfig.for_local_app_data(tmp_path)
    alembic_ini = Path(__file__).parents[2] / "alembic.ini"
    upgrade_database(config.paths.database_path, alembic_ini)
    engine = create_sqlite_engine(config.paths.database_path)
    service = AiSettingsService(create_session_factory(engine))
    service.create_provider(
        name="Primary",
        provider_type="openai_compatible",
        base_url="https://example.test/v1",
        api_key="first-secret",
        enabled=True,
        extra={},
    )

    try:
        service.create_provider(
            name="Primary",
            provider_type="openai_compatible",
            base_url="https://example.test/v1",
            api_key="sensitive-conflict-secret",
            enabled=True,
            extra={},
        )
    except AiSettingsConflictError as error:
        assert error.__context__ is None
        assert "sensitive-conflict-secret" not in str(error)
    else:
        raise AssertionError("重复 Provider 应产生脱敏的业务冲突")
