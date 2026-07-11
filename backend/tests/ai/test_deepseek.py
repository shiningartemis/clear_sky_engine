import json

import httpx
import pytest
import respx
from pydantic import SecretStr, TypeAdapter

from app.ai.contracts import ProviderConnection
from app.ai.deepseek import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL_PRESETS,
    DeepSeekProvider,
)
from app.ai.dto import (
    ChatMessage,
    ChatRequest,
    FunctionDefinition,
    ResponseFormat,
    ThinkingConfig,
    ToolDefinition,
)
from app.ai.errors import AiErrorCategory, AiProviderError
from app.ai.types import JsonValue


def connection() -> ProviderConnection:
    return ProviderConnection(
        provider_id=2,
        base_url=DEEPSEEK_BASE_URL,
        api_key=SecretStr("deepseek-test-key"),
    )


def thinking_request() -> ChatRequest:
    return ChatRequest(
        model_id="deepseek-v4-flash",
        messages=[ChatMessage(role="user", content="hello")],
        temperature=0.9,
        thinking=ThinkingConfig(type="enabled", effort="high"),
    )


def test_official_presets_only_include_current_v4_models() -> None:
    assert DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    assert [preset.remote_model for preset in DEEPSEEK_MODEL_PRESETS] == [
        "deepseek-v4-pro",
        "deepseek-v4-flash",
    ]
    assert all(preset.supports_reasoning for preset in DEEPSEEK_MODEL_PRESETS)
    assert all(preset.supports_json_output for preset in DEEPSEEK_MODEL_PRESETS)
    assert all(preset.supports_tools for preset in DEEPSEEK_MODEL_PRESETS)
    assert "deepseek-chat" not in {preset.remote_model for preset in DEEPSEEK_MODEL_PRESETS}
    assert "deepseek-reasoner" not in {preset.remote_model for preset in DEEPSEEK_MODEL_PRESETS}


@respx.mock
async def test_thinking_request_uses_official_fields_and_omits_temperature() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = TypeAdapter(dict[str, JsonValue]).validate_json(request.content)
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == "high"
        assert "temperature" not in payload
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"reasoning_content": "thought", "content": "answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8},
            },
        )

    respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=respond)
    async with httpx.AsyncClient() as client:
        response = await DeepSeekProvider(client).complete(thinking_request(), connection())

    assert response.reasoning == "thought"
    assert response.text == "answer"
    assert response.usage.total_tokens == 8


@respx.mock
async def test_stream_ignores_deepseek_keep_alive_comments() -> None:
    chunks = [
        {
            "choices": [
                {
                    "delta": {"reasoning_content": "thought", "content": "answer"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
        }
    ]
    body = (
        ": keep-alive\n\n\n"
        + "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        + "data: [DONE]\n\n"
    )
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(200, text=body)
    )
    async with httpx.AsyncClient() as client:
        events = [
            event
            async for event in DeepSeekProvider(client).stream(thinking_request(), connection())
        ]

    assert [event.kind for event in events] == [
        "reasoning_delta",
        "text_delta",
        "completed",
    ]
    assert events[-1].response is not None
    assert events[-1].response.usage.total_tokens == 4


@respx.mock
async def test_json_output_and_tool_calls_keep_common_semantics() -> None:
    request = ChatRequest(
        model_id="deepseek-v4-flash",
        messages=[ChatMessage(role="user", content="return json")],
        response_format=ResponseFormat(type="json_object"),
        tools=[
            ToolDefinition(
                function=FunctionDefinition(
                    name="lookup",
                    parameters={"type": "object", "properties": {}},
                )
            )
        ],
    )

    def respond(http_request: httpx.Request) -> httpx.Response:
        payload = TypeAdapter(dict[str, JsonValue]).validate_json(http_request.content)
        assert payload["response_format"] == {"type": "json_object"}
        assert isinstance(payload["tools"], list)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"ok":true}',
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": "{}"},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
            },
        )

    respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=respond)
    async with httpx.AsyncClient() as client:
        response = await DeepSeekProvider(client).complete(request, connection())

    assert response.text == '{"ok":true}'
    assert response.tool_calls[0].function.name == "lookup"
    assert response.finish_reason == "tool_calls"


@pytest.mark.parametrize(
    ("status_code", "category"),
    [
        (401, AiErrorCategory.AUTHENTICATION),
        (402, AiErrorCategory.INSUFFICIENT_BALANCE),
        (429, AiErrorCategory.RATE_LIMITED),
        (503, AiErrorCategory.UNAVAILABLE),
    ],
)
@respx.mock
async def test_official_error_codes_use_common_redacted_categories(
    status_code: int, category: AiErrorCategory
) -> None:
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(
            status_code,
            json={"error": {"message": "private response deepseek-test-key"}},
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(AiProviderError) as captured:
            await DeepSeekProvider(client, max_retries=0).complete(thinking_request(), connection())

    assert captured.value.category is category
    assert "deepseek-test-key" not in str(captured.value)
