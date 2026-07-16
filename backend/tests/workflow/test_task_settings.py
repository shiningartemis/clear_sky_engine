from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.service import AiSettingsService
from app.ai.types import JsonValue
from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_session_factory, create_sqlite_engine
from app.workflow.settings import (
    StructuredOutputMode,
    TaskKey,
    TaskSettingConfigurationError,
    TaskSettingUpdate,
    TaskSettingValidationError,
)


@pytest.fixture
def service(tmp_path: Path) -> AiSettingsService:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[3] / "alembic.ini")
    engine = create_sqlite_engine(config.paths.database_path)
    return AiSettingsService(create_session_factory(engine))


def _create_model(
    service: AiSettingsService,
    *,
    enabled: bool = True,
    json_output: bool = True,
) -> int:
    provider = service.create_provider(
        name="Primary",
        provider_type="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-only-key",
        enabled=True,
        extra={},
    )
    model = service.create_model(
        provider_id=provider.id,
        display_name="Model A",
        remote_model="model-a",
        capabilities={"json_output": json_output},
        enabled=enabled,
    )
    return model.id


def _update(
    model_id: int | None,
    *,
    mode: StructuredOutputMode = StructuredOutputMode.AUTO,
    provider_options: dict[str, JsonValue] | None = None,
    memory_target_chars: int | None = None,
    memory_max_chars: int | None = None,
) -> TaskSettingUpdate:
    return TaskSettingUpdate(
        model_id=model_id,
        temperature=0.7,
        max_output_tokens=512,
        reasoning_effort="high",
        timeout_seconds=90,
        extra_prompt="只输出必要内容",
        structured_output_mode=mode,
        provider_options=provider_options or {},
        memory_target_chars=memory_target_chars,
        memory_max_chars=memory_max_chars,
    )


def _type_name(value: object) -> str:
    return type(value).__name__


def test_fixed_task_settings_have_stable_defaults(service: AiSettingsService) -> None:
    settings = service.list_task_settings()

    assert [item.task_key for item in settings] == [
        TaskKey.LOCATION_SIMULATION,
        TaskKey.ATTRIBUTE_MEMORY_ANALYSIS,
    ]
    assert settings[0].model_id is None
    assert settings[0].memory_target_chars is None
    assert settings[0].memory_max_chars is None
    assert settings[1].memory_target_chars == 20
    assert settings[1].memory_max_chars == 50
    assert all(item.version == 1 for item in settings)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", -0.01),
        ("temperature", 2.01),
        ("max_output_tokens", 0),
        ("timeout_seconds", 0),
        ("reasoning_effort", "medium"),
        ("memory_target_chars", 0),
        ("memory_max_chars", 0),
    ],
)
def test_task_setting_value_ranges_are_validated(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "model_id": None,
        "temperature": 0.7,
        "max_output_tokens": 512,
        "reasoning_effort": "high",
        "timeout_seconds": 90,
        "extra_prompt": "",
        "structured_output_mode": "auto",
        "provider_options": {},
        "memory_target_chars": 20,
        "memory_max_chars": 50,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        TaskSettingUpdate.model_validate(payload)


def test_provider_options_root_must_be_an_object() -> None:
    payload = _update(None).model_dump()
    payload["provider_options"] = ["not", "an", "object"]

    with pytest.raises(ValidationError):
        TaskSettingUpdate.model_validate(payload)


@pytest.mark.parametrize("task_key", ["unknown", "LOCATION_SIMULATION"])
def test_task_key_is_a_fixed_enum(task_key: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(TaskKey).validate_python(task_key)


def test_model_must_exist_and_be_enabled(service: AiSettingsService) -> None:
    with pytest.raises(TaskSettingConfigurationError, match="模型不存在"):
        service.update_task_setting(TaskKey.LOCATION_SIMULATION, _update(999))

    disabled_model_id = _create_model(service, enabled=False)
    with pytest.raises(TaskSettingConfigurationError, match="模型未启用"):
        service.update_task_setting(TaskKey.LOCATION_SIMULATION, _update(disabled_model_id))


def test_task_specific_memory_bounds_are_enforced(service: AiSettingsService) -> None:
    model_id = _create_model(service)

    with pytest.raises(TaskSettingValidationError, match="记忆字数"):
        service.update_task_setting(
            TaskKey.ATTRIBUTE_MEMORY_ANALYSIS,
            _update(model_id, memory_target_chars=51, memory_max_chars=50),
        )
    with pytest.raises(TaskSettingValidationError, match="记忆字数"):
        service.update_task_setting(
            TaskKey.ATTRIBUTE_MEMORY_ANALYSIS,
            _update(model_id, memory_target_chars=None, memory_max_chars=None),
        )
    with pytest.raises(TaskSettingValidationError, match="不得包含记忆字数"):
        service.update_task_setting(
            TaskKey.LOCATION_SIMULATION,
            _update(model_id, memory_target_chars=20, memory_max_chars=50),
        )


@pytest.mark.parametrize(
    "key",
    [
        "model",
        "MAX-OUTPUT-TOKENS",
        "Api_Key",
        "API Key",
        "api.key",
        "responseFormat",
        "Authorization",
    ],
)
def test_protected_provider_options_are_rejected_after_normalization(
    service: AiSettingsService,
    key: str,
) -> None:
    model_id = _create_model(service)

    with pytest.raises(TaskSettingValidationError) as captured:
        service.update_task_setting(
            TaskKey.LOCATION_SIMULATION,
            _update(model_id, provider_options={key: 1}),
        )

    assert key in str(captured.value)


def test_unknown_provider_options_are_preserved_and_version_increments(
    service: AiSettingsService,
) -> None:
    model_id = _create_model(service)
    provider_options: dict[str, JsonValue] = {
        "seed": 7,
        "vendor_extension": {"mode": "strict"},
    }

    saved = service.update_task_setting(
        TaskKey.LOCATION_SIMULATION,
        _update(model_id, provider_options=provider_options),
    )
    reloaded = service.get_task_setting(TaskKey.LOCATION_SIMULATION)

    assert saved.version == 2
    assert reloaded.version == 2
    assert reloaded.provider_options == provider_options


def test_native_mode_requires_model_json_output_capability(service: AiSettingsService) -> None:
    model_id = _create_model(service, json_output=False)

    with pytest.raises(TaskSettingConfigurationError, match="原生 JSON"):
        service.update_task_setting(
            TaskKey.LOCATION_SIMULATION,
            _update(model_id, mode=StructuredOutputMode.NATIVE),
        )


@pytest.mark.parametrize(
    ("json_output", "configured", "resolved"),
    [
        (True, StructuredOutputMode.AUTO, StructuredOutputMode.NATIVE),
        (False, StructuredOutputMode.AUTO, StructuredOutputMode.PROMPT),
        (True, StructuredOutputMode.PROMPT, StructuredOutputMode.PROMPT),
    ],
)
def test_runnable_snapshot_resolves_structured_output_without_model_fallback(
    service: AiSettingsService,
    json_output: bool,
    configured: StructuredOutputMode,
    resolved: StructuredOutputMode,
) -> None:
    model_id = _create_model(service, json_output=json_output)
    service.update_task_setting(
        TaskKey.LOCATION_SIMULATION,
        _update(model_id, mode=configured),
    )

    snapshot = service.get_runnable_task_setting(TaskKey.LOCATION_SIMULATION)

    assert snapshot.model_id == model_id
    assert snapshot.structured_output_mode is configured
    assert snapshot.resolved_structured_output_mode is resolved


def test_missing_model_can_be_read_but_not_frozen_as_runnable(
    service: AiSettingsService,
) -> None:
    assert service.get_task_setting(TaskKey.LOCATION_SIMULATION).model_id is None

    with pytest.raises(TaskSettingConfigurationError, match="尚未选择模型"):
        service.get_runnable_task_setting(TaskKey.LOCATION_SIMULATION)


def test_runnable_snapshot_is_unchanged_by_later_saves(service: AiSettingsService) -> None:
    model_id = _create_model(service)
    service.update_task_setting(
        TaskKey.LOCATION_SIMULATION,
        _update(model_id, provider_options={"seed": 7}),
    )
    snapshot = service.get_runnable_task_setting(TaskKey.LOCATION_SIMULATION)

    service.update_task_setting(
        TaskKey.LOCATION_SIMULATION,
        _update(model_id, provider_options={"seed": 9}),
    )

    assert snapshot.version == 2
    assert snapshot.provider_options == {"seed": 7}


def test_runnable_snapshot_provider_options_are_deeply_immutable(
    service: AiSettingsService,
) -> None:
    model_id = _create_model(service)
    service.update_task_setting(
        TaskKey.LOCATION_SIMULATION,
        _update(
            model_id,
            provider_options={
                "seed": 7,
                "vendor_extension": {"mode": "strict"},
                "stop_sequences": ["END"],
            },
        ),
    )

    snapshot = service.get_runnable_task_setting(TaskKey.LOCATION_SIMULATION)

    assert _type_name(snapshot.provider_options) == "mappingproxy"
    nested = snapshot.provider_options["vendor_extension"]
    assert isinstance(nested, Mapping)
    assert _type_name(nested) == "mappingproxy"
    sequence = snapshot.provider_options["stop_sequences"]
    assert isinstance(sequence, tuple)


def test_task_setting_commit_failure_rolls_back_and_drops_sensitive_context(
    service: AiSettingsService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_id = _create_model(service)
    secret = "sk-secret-service-commit"
    rollbacks: list[bool] = []
    original_rollback = Session.rollback

    def fail_commit(_session: Session) -> None:
        raise IntegrityError(
            "UPDATE ai_task_setting SET provider_options_json = ?",
            {"provider_options_json": secret},
            RuntimeError("database failure"),
        )

    def record_rollback(session: Session) -> None:
        rollbacks.append(True)
        original_rollback(session)

    monkeypatch.setattr(Session, "commit", fail_commit)
    monkeypatch.setattr(Session, "rollback", record_rollback)

    with pytest.raises(Exception) as captured:
        service.update_task_setting(
            TaskKey.LOCATION_SIMULATION,
            _update(
                model_id,
                provider_options={"vendor_secret": secret},
            ).model_copy(
                update={"extra_prompt": f"sensitive prompt {secret}"},
            ),
        )

    assert type(captured.value).__name__ == "TaskSettingPersistenceError"
    assert str(captured.value) == "AI 任务设置保存失败"
    assert captured.value.__context__ is None
    assert captured.value.__cause__ is None
    assert secret not in str(captured.value)
    assert rollbacks == [True]
