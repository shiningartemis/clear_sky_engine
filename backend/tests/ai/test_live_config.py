"""真实 AI 测试配置只从隔离 SQLite 读取，且错误不得泄露密钥。"""

from pathlib import Path

import pytest

from app.ai.deepseek import DEEPSEEK_BASE_URL
from app.ai.service import AiSettingsService
from app.db.migrations import upgrade_database
from app.db.session import create_session_factory, create_sqlite_engine

from .live_config import LiveAiConfigurationError, load_live_model


def create_service(database_path: Path) -> AiSettingsService:
    alembic_ini = Path(__file__).parents[3] / "alembic.ini"
    upgrade_database(database_path, alembic_ini)
    engine = create_sqlite_engine(database_path)
    return AiSettingsService(create_session_factory(engine))


def create_deepseek_settings(
    database_path: Path, *, provider_enabled: bool = True, create_model: bool = True
) -> tuple[AiSettingsService, int]:
    service = create_service(database_path)
    provider = service.create_provider(
        name="DeepSeek Official",
        provider_type="deepseek",
        base_url=DEEPSEEK_BASE_URL,
        api_key="test-secret",
        enabled=provider_enabled,
        extra={},
    )
    if create_model:
        service.create_model(
            provider_id=provider.id,
            display_name="DeepSeek V4 Flash",
            remote_model="deepseek-v4-flash",
            capabilities={},
            enabled=True,
        )
    return service, provider.id


def test_loads_enabled_deepseek_model_from_database(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    _service, provider_id = create_deepseek_settings(database_path)

    settings = load_live_model("deepseek-v4-flash", database_path)

    assert settings.model_id == "deepseek-v4-flash"
    assert settings.connection.provider_id == provider_id
    assert settings.connection.base_url == DEEPSEEK_BASE_URL
    assert settings.connection.api_key.get_secret_value() == "test-secret"


def test_rejects_disabled_provider_without_leaking_secret(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    create_deepseek_settings(database_path, provider_enabled=False)

    with pytest.raises(LiveAiConfigurationError) as captured:
        load_live_model("deepseek-v4-flash", database_path)

    assert "DeepSeek Official" in str(captured.value)
    assert "test-secret" not in str(captured.value)


def test_rejects_missing_model_without_leaking_secret(tmp_path: Path) -> None:
    database_path = tmp_path / "app.db"
    create_deepseek_settings(database_path, create_model=False)

    with pytest.raises(LiveAiConfigurationError) as captured:
        load_live_model("deepseek-v4-flash", database_path)

    assert "模型未启用" in str(captured.value)
    assert "test-secret" not in str(captured.value)
