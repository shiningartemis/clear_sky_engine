"""从本机应用数据库解析 DeepSeek 真实测试配置。"""

from dataclasses import dataclass
from pathlib import Path

from app.ai.contracts import ProviderConnection
from app.ai.service import AiSettingsConfigurationError, AiSettingsService
from app.config import AppConfig
from app.db.session import create_session_factory, create_sqlite_engine


@dataclass(frozen=True)
class LiveModelSettings:
    connection: ProviderConnection
    model_id: str


class LiveAiConfigurationError(RuntimeError):
    """真实测试配置不可用；错误文本不得携带数据库值或密钥。"""


def load_live_model(remote_model: str, database_path: Path | None = None) -> LiveModelSettings:
    """只解析唯一启用的官方配置，不做模型 fallback。"""

    resolved_path = database_path or AppConfig.for_local_app_data().paths.database_path
    if not resolved_path.is_file():
        raise LiveAiConfigurationError("本机应用数据库不存在, 真实 AI 集成未验证")

    engine = create_sqlite_engine(resolved_path)
    try:
        service = AiSettingsService(create_session_factory(engine))
        providers = [
            item
            for item in service.list_providers()
            if item.name == "DeepSeek Official"
            and item.provider_type == "deepseek"
            and item.enabled
        ]
        if len(providers) != 1:
            raise LiveAiConfigurationError("启用的 DeepSeek Official 配置不唯一")
        provider = providers[0]
        models = [
            item
            for item in service.list_models(provider.id)
            if item.remote_model == remote_model and item.enabled
        ]
        if len(models) != 1:
            raise LiveAiConfigurationError("目标 DeepSeek 模型未启用")
        try:
            record = service.get_provider_connection(provider.id)
        except AiSettingsConfigurationError:
            raise LiveAiConfigurationError("DeepSeek Official 缺少 API Key") from None
        return LiveModelSettings(
            connection=ProviderConnection(
                provider_id=record.provider_id,
                base_url=record.base_url,
                api_key=record.api_key,
                options=record.options,
            ),
            model_id=models[0].remote_model,
        )
    finally:
        engine.dispose()
