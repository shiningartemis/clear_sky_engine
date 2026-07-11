import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from pydantic import SecretStr, TypeAdapter

from app.ai.contracts import ProviderConnection
from app.ai.dto import (
    ChatMessage,
    ChatRequest,
    FunctionDefinition,
    ResponseFormat,
    ThinkingConfig,
    ToolDefinition,
)
from app.ai.errors import AiErrorCategory, AiProviderError
from app.ai.openai_compatible import OpenAICompatibleProvider
from app.ai.types import JsonValue


class FailingAfterChunkStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield (b'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}\n\n')
        raise httpx.ReadError("connection lost after output")


class CancellingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        raise asyncio.CancelledError


def make_request() -> ChatRequest:
    return ChatRequest(
        model_id="model-a",
        messages=[ChatMessage(role="user", content="return json")],
        temperature=0.4,
        max_output_tokens=64,
        thinking=ThinkingConfig(type="enabled", effort="high"),
        response_format=ResponseFormat(type="json_object"),
        tools=[
            ToolDefinition(
                function=FunctionDefinition(
                    name="lookup",
                    description="Lookup a value",
                    parameters={"type": "object", "properties": {}},
                )
            )
        ],
        provider_options={"seed": 7},
    )


def make_connection() -> ProviderConnection:
    return ProviderConnection(
        provider_id=9,
        base_url="https://provider.test/v1/",
        api_key=SecretStr("test-api-key"),
    )


@respx.mock
async def test_complete_preserves_text_reasoning_tools_finish_and_usage() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        payload = TypeAdapter(dict[str, JsonValue]).validate_json(request.content)
        assert request.headers["Authorization"] == "Bearer test-api-key"
        assert payload["response_format"] == {"type": "json_object"}
        assert payload["max_tokens"] == 64
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == "high"
        assert payload["seed"] == 7
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"ok": true}',
                            "reasoning_content": "checked",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"value":1}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
            },
        )

    respx.post("https://provider.test/v1/chat/completions").mock(side_effect=respond)
    async with httpx.AsyncClient() as client:
        response = await OpenAICompatibleProvider(client).complete(
            make_request(), make_connection()
        )

    assert response.text == '{"ok": true}'
    assert response.reasoning == "checked"
    assert response.tool_calls[0].function.name == "lookup"
    assert response.finish_reason == "tool_calls"
    assert response.usage.total_tokens == 10


@respx.mock
async def test_stream_ignores_keep_alive_and_assembles_fragmented_output() -> None:
    chunks = [
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_content": "think ",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"'},
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_content": "done",
                        "content": '{"ok":',
                        "tool_calls": [
                            {"index": 0, "function": {"name": "", "arguments": 'value":1}'}}
                        ],
                    },
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [{"delta": {"content": "true}"}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
        },
    ]
    body = (
        ": keep-alive\n\n"
        + "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
        + "data: [DONE]\n\n"
    )
    respx.post("https://provider.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )
    async with httpx.AsyncClient() as client:
        events = [
            event
            async for event in OpenAICompatibleProvider(client).stream(
                make_request(), make_connection()
            )
        ]

    assert [event.kind for event in events] == [
        "reasoning_delta",
        "tool_call_delta",
        "reasoning_delta",
        "text_delta",
        "tool_call_delta",
        "text_delta",
        "completed",
    ]
    completed = events[-1].response
    assert completed is not None
    assert completed.text == '{"ok":true}'
    assert completed.reasoning == "think done"
    assert completed.tool_calls[0].function.arguments == '{"value":1}'
    assert completed.usage.total_tokens == 10


@respx.mock
async def test_complete_retries_one_transient_error_before_output() -> None:
    route = respx.post("https://provider.test/v1/chat/completions").mock(
        side_effect=[
            httpx.ConnectError("temporary"),
            httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            ),
        ]
    )
    async with httpx.AsyncClient() as client:
        response = await OpenAICompatibleProvider(client).complete(
            make_request(), make_connection()
        )

    assert response.text == "ok"
    assert route.call_count == 2


@respx.mock
async def test_stream_does_not_retry_after_emitting_output() -> None:
    route = respx.post("https://provider.test/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(
                200,
                stream=FailingAfterChunkStream(),
                headers={"content-type": "text/event-stream"},
            ),
            httpx.Response(200, text="data: [DONE]\n\n"),
        ]
    )
    async with httpx.AsyncClient() as client:
        stream = OpenAICompatibleProvider(client).stream(make_request(), make_connection())
        first = await anext(stream)
        with pytest.raises(AiProviderError) as captured:
            await anext(stream)

    assert first.kind == "text_delta"
    assert captured.value.category is AiErrorCategory.NETWORK
    assert route.call_count == 1


async def test_cancellation_propagates_without_retry_or_conversion() -> None:
    transport = CancellingTransport()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(asyncio.CancelledError):
            await OpenAICompatibleProvider(client).complete(make_request(), make_connection())

    assert transport.calls == 1


@pytest.mark.parametrize(
    ("status_code", "category", "retryable"),
    [
        (400, AiErrorCategory.INVALID_REQUEST, False),
        (401, AiErrorCategory.AUTHENTICATION, False),
        (402, AiErrorCategory.INSUFFICIENT_BALANCE, False),
        (429, AiErrorCategory.RATE_LIMITED, True),
        (503, AiErrorCategory.UNAVAILABLE, True),
    ],
)
@respx.mock
async def test_error_mapping_is_consistent_and_redacted(
    status_code: int, category: AiErrorCategory, retryable: bool
) -> None:
    route = respx.post("https://provider.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            status_code,
            json={"error": {"message": "sensitive upstream body test-api-key"}},
        )
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(AiProviderError) as captured:
            await OpenAICompatibleProvider(client, max_retries=0).complete(
                make_request(), make_connection()
            )

    assert captured.value.category is category
    assert captured.value.retryable is retryable
    assert captured.value.__context__ is None
    assert "test-api-key" not in str(captured.value)
    assert route.call_count == 1
