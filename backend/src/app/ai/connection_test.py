"""Provider 连接测试编排，不保留 Prompt 或响应正文。"""

from dataclasses import dataclass

from app.ai.contracts import ProviderConnection, ProviderRegistry
from app.ai.dto import ChatMessage, ChatRequest, ThinkingConfig, TokenUsage
from app.ai.errors import AiErrorCategory, AiProviderError
from app.ai.service import (
    AiSettingsConfigurationError,
    AiSettingsService,
)
from app.ai.types import JsonValue


@dataclass(frozen=True)
class ConnectionTestResult:
    success: bool
    provider_type: str
    remote_model: str
    capabilities: dict[str, JsonValue]
    diagnostic: str
    error_category: AiErrorCategory | None
    usage: TokenUsage | None


class ConnectionTestService:
    """数据库读取在调用前完成，等待 AI 时不持有 Session 或事务。"""

    def __init__(self, settings: AiSettingsService) -> None:
        self._settings = settings

    async def test(
        self,
        *,
        registry: ProviderRegistry,
        provider_id: int,
        model_id: int,
    ) -> ConnectionTestResult:
        provider = self._settings.get_provider_connection(provider_id)
        model = self._settings.get_model(model_id)
        if model.provider_id != provider_id:
            raise AiSettingsConfigurationError("模型不属于指定 Provider")

        thinking = ThinkingConfig(type="disabled") if provider.provider_type == "deepseek" else None
        request = ChatRequest(
            model_id=model.remote_model,
            messages=[ChatMessage(role="user", content="Reply with OK.")],
            max_output_tokens=16,
            thinking=thinking,
        )
        connection = ProviderConnection(
            provider_id=provider.provider_id,
            base_url=provider.base_url,
            api_key=provider.api_key,
            options=provider.options,
        )
        try:
            response = await registry.get(provider.provider_type).complete(request, connection)
        except AiProviderError as error:
            return ConnectionTestResult(
                success=False,
                provider_type=provider.provider_type,
                remote_model=model.remote_model,
                capabilities=model.capabilities,
                diagnostic=str(error),
                error_category=error.category,
                usage=None,
            )
        return ConnectionTestResult(
            success=True,
            provider_type=provider.provider_type,
            remote_model=model.remote_model,
            capabilities=model.capabilities,
            diagnostic="连接成功",
            error_category=None,
            usage=response.usage,
        )
