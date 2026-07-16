from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.main import create_app


@asynccontextmanager
async def ai_task_client(
    tmp_path: Path,
    *,
    raise_app_exceptions: bool = True,
) -> AsyncGenerator[AsyncClient]:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[2] / "alembic.ini")
    app = create_app(config)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
            base_url="http://testserver",
        ) as client,
    ):
        yield client


async def _create_model(
    client: AsyncClient,
    *,
    enabled: bool = True,
    json_output: bool = True,
) -> int:
    provider = await client.post(
        "/api/providers",
        json={
            "name": "Primary",
            "provider_type": "openai_compatible",
            "base_url": "https://example.test/v1",
        },
    )
    model = await client.post(
        "/api/models",
        json={
            "provider_id": provider.json()["id"],
            "display_name": "Model A",
            "remote_model": "model-a",
            "capabilities": {"json_output": json_output},
            "enabled": enabled,
        },
    )
    return model.json()["id"]


def _payload(
    model_id: int | None,
    *,
    mode: str = "auto",
    provider_options: object | None = None,
) -> dict[str, object]:
    return {
        "model_id": model_id,
        "temperature": 0.7,
        "max_output_tokens": 512,
        "reasoning_effort": "high",
        "timeout_seconds": 90,
        "extra_prompt": "只输出必要内容",
        "structured_output_mode": mode,
        "provider_options": {} if provider_options is None else provider_options,
        "memory_target_chars": None,
        "memory_max_chars": None,
    }


async def test_list_returns_exactly_two_fixed_settings_even_without_models(tmp_path: Path) -> None:
    async with ai_task_client(tmp_path) as client:
        response = await client.get("/api/ai-task-settings")

    assert response.status_code == 200
    settings = response.json()
    assert [item["task_key"] for item in settings] == [
        "location_simulation",
        "attribute_memory_analysis",
    ]
    assert settings[0]["model_id"] is None
    assert settings[0]["version"] == 1
    assert settings[1]["memory_target_chars"] == 20
    assert settings[1]["memory_max_chars"] == 50


async def test_put_updates_one_setting_and_returns_incremented_version(tmp_path: Path) -> None:
    async with ai_task_client(tmp_path) as client:
        model_id = await _create_model(client)
        response = await client.put(
            "/api/ai-task-settings/location_simulation",
            json=_payload(model_id, provider_options={"seed": 7}),
        )
        listed = await client.get("/api/ai-task-settings")

    assert response.status_code == 200
    assert response.json()["task_key"] == "location_simulation"
    assert response.json()["version"] == 2
    assert response.json()["provider_options"] == {"seed": 7}
    assert listed.json()[0] == response.json()
    assert listed.json()[1]["version"] == 1


async def test_put_rejects_invalid_ranges_and_non_object_provider_options(tmp_path: Path) -> None:
    async with ai_task_client(tmp_path) as client:
        bad_temperature = _payload(None)
        bad_temperature["temperature"] = 2.1
        temperature_response = await client.put(
            "/api/ai-task-settings/location_simulation", json=bad_temperature
        )
        json_response = await client.put(
            "/api/ai-task-settings/location_simulation",
            json=_payload(None, provider_options=["not-an-object"]),
        )

    assert temperature_response.status_code == 422
    assert json_response.status_code == 422


async def test_put_requires_every_setting_field_even_when_nullable(tmp_path: Path) -> None:
    async with ai_task_client(tmp_path) as client:
        missing_model = _payload(None)
        del missing_model["model_id"]
        model_response = await client.put(
            "/api/ai-task-settings/location_simulation", json=missing_model
        )
        missing_memory_bound = _payload(None)
        del missing_memory_bound["memory_target_chars"]
        memory_response = await client.put(
            "/api/ai-task-settings/location_simulation", json=missing_memory_bound
        )

    assert model_response.status_code == 422
    assert memory_response.status_code == 422


async def test_put_rejects_unknown_task_and_unavailable_model(tmp_path: Path) -> None:
    async with ai_task_client(tmp_path) as client:
        unknown_task = await client.put("/api/ai-task-settings/unknown", json=_payload(None))
        missing_model = await client.put(
            "/api/ai-task-settings/location_simulation", json=_payload(999)
        )
        disabled_model_id = await _create_model(client, enabled=False)
        disabled_model = await client.put(
            "/api/ai-task-settings/location_simulation", json=_payload(disabled_model_id)
        )

    assert unknown_task.status_code == 422
    assert missing_model.status_code == 409
    assert missing_model.json()["detail"] == "模型不存在"
    assert disabled_model.status_code == 409
    assert disabled_model.json()["detail"] == "模型未启用"


async def test_put_reports_normalized_protected_provider_option(tmp_path: Path) -> None:
    async with ai_task_client(tmp_path) as client:
        model_id = await _create_model(client)
        response = await client.put(
            "/api/ai-task-settings/location_simulation",
            json=_payload(model_id, provider_options={"MAX-OUTPUT-TOKENS": 10}),
        )

    assert response.status_code == 409
    assert "MAX-OUTPUT-TOKENS" in response.json()["detail"]


async def test_task_setting_errors_never_echo_api_key_like_values(tmp_path: Path) -> None:
    secret = "sk-review-secret-never-return"
    async with ai_task_client(tmp_path) as client:
        model_id = await _create_model(client)
        conflict = await client.put(
            "/api/ai-task-settings/location_simulation",
            json=_payload(model_id, provider_options={"API Key": secret}),
        )
        invalid_root = await client.put(
            "/api/ai-task-settings/location_simulation",
            json=_payload(model_id, provider_options=[secret]),
        )
        listed = await client.get("/api/ai-task-settings")

    assert conflict.status_code == 409
    assert "API Key" in conflict.json()["detail"]
    assert secret not in conflict.text
    assert invalid_root.status_code == 422
    assert secret not in invalid_root.text
    assert secret not in listed.text


async def test_native_mode_rejects_model_without_json_output(tmp_path: Path) -> None:
    async with ai_task_client(tmp_path) as client:
        model_id = await _create_model(client, json_output=False)
        response = await client.put(
            "/api/ai-task-settings/location_simulation",
            json=_payload(model_id, mode="native"),
        )

    assert response.status_code == 409
    assert "原生 JSON" in response.json()["detail"]


async def test_task_setting_commit_failure_returns_safe_http_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-secret-api-commit"
    async with ai_task_client(tmp_path, raise_app_exceptions=False) as client:
        model_id = await _create_model(client)

        def fail_commit(_session: Session) -> None:
            raise IntegrityError(
                "UPDATE ai_task_setting SET provider_options_json = ?",
                {"provider_options_json": secret},
                RuntimeError("database failure"),
            )

        monkeypatch.setattr(Session, "commit", fail_commit)
        response = await client.put(
            "/api/ai-task-settings/location_simulation",
            json=_payload(model_id, provider_options={"vendor_secret": secret}),
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "AI 任务设置保存失败"}
    assert secret not in response.text
