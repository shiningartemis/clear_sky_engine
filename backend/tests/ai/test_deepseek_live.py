"""DeepSeek 真实付费集成；只记录能力结果与 token usage。"""

import json

import httpx
import pytest

from app.ai.deepseek import DeepSeekProvider
from app.ai.dto import (
    ChatMessage,
    ChatRequest,
    FunctionDefinition,
    ResponseFormat,
    ThinkingConfig,
    ToolDefinition,
)

from .live_config import load_live_model

FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"


def record_result(model: str, capability: str, input_tokens: int, output_tokens: int) -> None:
    """仅输出安全台账，不输出 Prompt、正文、reasoning 或密钥。"""

    print(
        json.dumps(
            {
                "provider": "deepseek",
                "model": model,
                "capability": capability,
                "result": "passed",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            ensure_ascii=False,
        )
    )


@pytest.mark.live_ai
async def test_live_normal_completion() -> None:
    settings = load_live_model(FLASH_MODEL)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await DeepSeekProvider(client).complete(
            ChatRequest(
                model_id=settings.model_id,
                messages=[ChatMessage(role="user", content="Reply with exactly OK.")],
                max_output_tokens=16,
                thinking=ThinkingConfig(type="disabled"),
            ),
            settings.connection,
        )

    assert bool(response.text.strip()), "普通响应应包含文本"
    record_result(
        FLASH_MODEL,
        "normal",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )


@pytest.mark.live_ai
async def test_live_streaming_completion() -> None:
    settings = load_live_model(FLASH_MODEL)
    completed = None
    async with httpx.AsyncClient(timeout=120) as client:
        async for event in DeepSeekProvider(client).stream(
            ChatRequest(
                model_id=settings.model_id,
                messages=[ChatMessage(role="user", content="Reply with exactly OK.")],
                max_output_tokens=16,
                thinking=ThinkingConfig(type="disabled"),
            ),
            settings.connection,
        ):
            if event.kind == "completed":
                completed = event.response

    assert completed is not None, "流式调用应产生 completed 终态"
    assert bool(completed.text.strip()), "流式终态应包含文本"
    record_result(
        FLASH_MODEL,
        "streaming",
        completed.usage.input_tokens,
        completed.usage.output_tokens,
    )


@pytest.mark.live_ai
async def test_live_thinking_reasoning() -> None:
    settings = load_live_model(FLASH_MODEL)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await DeepSeekProvider(client).complete(
            ChatRequest(
                model_id=settings.model_id,
                messages=[ChatMessage(role="user", content="Which is larger: 9.11 or 9.8?")],
                max_output_tokens=96,
                thinking=ThinkingConfig(type="enabled", effort="high"),
            ),
            settings.connection,
        )

    assert bool(response.reasoning), "thinking 模式应返回 reasoning_content"
    assert bool(response.text.strip()), "thinking 模式应返回最终文本"
    record_result(
        FLASH_MODEL,
        "thinking",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )


@pytest.mark.live_ai
async def test_live_json_output() -> None:
    settings = load_live_model(FLASH_MODEL)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await DeepSeekProvider(client).complete(
            ChatRequest(
                model_id=settings.model_id,
                messages=[
                    ChatMessage(
                        role="user",
                        content='Return JSON matching this example: {"ok": true}',
                    )
                ],
                max_output_tokens=48,
                thinking=ThinkingConfig(type="disabled"),
                response_format=ResponseFormat(type="json_object"),
            ),
            settings.connection,
        )

    parsed = json.loads(response.text)
    assert isinstance(parsed, dict), "JSON Output 应返回 JSON 对象"
    record_result(
        FLASH_MODEL,
        "json_output",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )


@pytest.mark.live_ai
async def test_live_tool_calls() -> None:
    settings = load_live_model(FLASH_MODEL)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await DeepSeekProvider(client).complete(
            ChatRequest(
                model_id=settings.model_id,
                messages=[ChatMessage(role="user", content="Call get_date now.")],
                max_output_tokens=64,
                thinking=ThinkingConfig(type="disabled"),
                tools=[
                    ToolDefinition(
                        function=FunctionDefinition(
                            name="get_date",
                            description="Get the current date",
                            parameters={"type": "object", "properties": {}},
                        )
                    )
                ],
                provider_options={
                    "tool_choice": {
                        "type": "function",
                        "function": {"name": "get_date"},
                    }
                },
            ),
            settings.connection,
        )

    assert response.tool_calls, "Tool Calls 应返回至少一个调用"
    assert response.tool_calls[0].function.name == "get_date"
    record_result(
        FLASH_MODEL,
        "tool_calls",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )


@pytest.mark.live_ai
async def test_live_pro_connectivity() -> None:
    settings = load_live_model(PRO_MODEL)
    async with httpx.AsyncClient(timeout=120) as client:
        response = await DeepSeekProvider(client).complete(
            ChatRequest(
                model_id=settings.model_id,
                messages=[ChatMessage(role="user", content="Reply with exactly OK.")],
                max_output_tokens=16,
                thinking=ThinkingConfig(type="disabled"),
            ),
            settings.connection,
        )

    assert bool(response.text.strip()), "Pro 普通响应应包含文本"
    record_result(
        PRO_MODEL,
        "connectivity",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
