"""DeepSeek 官方 Provider 的最小专有适配。"""

from dataclasses import dataclass

import httpx

from app.ai.dto import ChatRequest
from app.ai.openai_compatible import OpenAICompatibleProvider
from app.ai.types import JsonValue

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


@dataclass(frozen=True)
class DeepSeekModelPreset:
    display_name: str
    remote_model: str
    supports_reasoning: bool = True
    supports_json_output: bool = True
    supports_tools: bool = True


DEEPSEEK_MODEL_PRESETS = (
    DeepSeekModelPreset(display_name="DeepSeek V4 Pro", remote_model="deepseek-v4-pro"),
    DeepSeekModelPreset(display_name="DeepSeek V4 Flash", remote_model="deepseek-v4-flash"),
)


class DeepSeekProvider(OpenAICompatibleProvider):
    """复用兼容协议，只覆盖 DeepSeek 明确不同的请求行为。"""

    provider_type = "deepseek"

    def __init__(self, http_client: httpx.AsyncClient, *, max_retries: int = 1) -> None:
        super().__init__(http_client, max_retries=max_retries)

    def _payload(self, request: ChatRequest, *, stream: bool) -> dict[str, JsonValue]:
        payload = super()._payload(request, stream=stream)
        if request.thinking is not None and request.thinking.type == "enabled":
            # DeepSeek thinking 模式明确忽略采样温度，避免向用户制造参数生效的假象。
            payload.pop("temperature", None)
        return payload
