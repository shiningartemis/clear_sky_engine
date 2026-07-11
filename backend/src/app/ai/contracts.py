"""无业务状态 Provider 协议与注册表。"""

from collections.abc import AsyncIterator, Iterable
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.ai.dto import ChatRequest, ChatResponse, ChatStreamEvent
from app.ai.errors import UnknownProviderError
from app.ai.types import JsonValue


class ProviderConnection(BaseModel):
    """一次调用所需连接事实；SecretStr 防止密钥进入对象表示。"""

    model_config = ConfigDict(frozen=True)

    provider_id: int = Field(gt=0)
    base_url: str
    api_key: SecretStr
    options: dict[str, JsonValue] = Field(default_factory=dict)


class AiProvider(Protocol):
    provider_type: str

    async def complete(
        self, request: ChatRequest, connection: ProviderConnection
    ) -> ChatResponse: ...

    def stream(
        self, request: ChatRequest, connection: ProviderConnection
    ) -> AsyncIterator[ChatStreamEvent]: ...


class ProviderRegistry:
    """只完成 provider_type 到实例的确定性映射，不做 fallback。"""

    def __init__(self, providers: Iterable[AiProvider]) -> None:
        self._providers: dict[str, AiProvider] = {}
        for provider in providers:
            if provider.provider_type in self._providers:
                raise ValueError("Provider 类型重复注册")
            self._providers[provider.provider_type] = provider

    def get(self, provider_type: str) -> AiProvider:
        provider = self._providers.get(provider_type)
        if provider is None:
            raise UnknownProviderError("不支持的 Provider 类型")
        return provider
