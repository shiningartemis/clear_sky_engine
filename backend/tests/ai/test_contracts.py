from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr, ValidationError

from app.ai.contracts import AiProvider, ProviderConnection, ProviderRegistry
from app.ai.dto import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
    FunctionCall,
    ResponseFormat,
    ThinkingConfig,
    TokenUsage,
    ToolCall,
)
from app.ai.errors import AiErrorCategory, AiProviderError, UnknownProviderError


class StubProvider:
    provider_type = "stub"

    async def complete(self, request: ChatRequest, connection: ProviderConnection) -> ChatResponse:
        return ChatResponse(
            text=request.messages[-1].content or "",
            reasoning=None,
            tool_calls=[],
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            provider_id=connection.provider_id,
            model_id=request.model_id,
        )

    async def stream(
        self, request: ChatRequest, connection: ProviderConnection
    ) -> AsyncIterator[ChatStreamEvent]:
        yield ChatStreamEvent(kind="text_delta", text_delta="ok")


def test_request_and_response_preserve_common_provider_semantics() -> None:
    request = ChatRequest(
        model_id="model-a",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.7,
        max_output_tokens=128,
        thinking=ThinkingConfig(type="enabled", effort="high"),
        response_format=ResponseFormat(type="json_object"),
        provider_options={"seed": 7},
    )
    tool_call = ToolCall(
        id="call-1",
        function=FunctionCall(name="lookup", arguments='{"value": 1}'),
    )
    response = ChatResponse(
        text='{"ok": true}',
        reasoning="checked",
        tool_calls=[tool_call],
        finish_reason="tool_calls",
        usage=TokenUsage(input_tokens=4, output_tokens=6, total_tokens=10),
        provider_id=3,
        model_id=request.model_id,
    )

    assert request.thinking == ThinkingConfig(type="enabled", effort="high")
    assert request.response_format.type == "json_object"
    assert response.reasoning == "checked"
    assert response.tool_calls == [tool_call]
    assert response.usage.total_tokens == 10


@pytest.mark.parametrize(
    "sensitive_key",
    ["api_key", "authorization", "base_url", "token", "secret"],
)
def test_provider_options_reject_connection_and_secret_fields(sensitive_key: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            model_id="model-a",
            messages=[ChatMessage(role="user", content="hello")],
            provider_options={sensitive_key: "must-not-pass"},
        )


def test_registry_maps_provider_type_without_fallback() -> None:
    provider: AiProvider = StubProvider()
    registry = ProviderRegistry([provider])

    assert registry.get("stub") is provider
    with pytest.raises(UnknownProviderError, match="不支持的 Provider 类型"):
        registry.get("missing")


def test_connection_masks_key_and_errors_only_expose_safe_diagnostics() -> None:
    connection = ProviderConnection(
        provider_id=4,
        base_url="https://example.test/v1",
        api_key=SecretStr("sensitive-key"),
    )
    error = AiProviderError(
        category=AiErrorCategory.AUTHENTICATION,
        message="Provider 认证失败",
        retryable=False,
        status_code=401,
    )

    assert "sensitive-key" not in repr(connection)
    assert "sensitive-key" not in repr(error)
    assert error.category is AiErrorCategory.AUTHENTICATION
    assert error.retryable is False
