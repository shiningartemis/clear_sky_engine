"""OpenAI-compatible 普通与 SSE 流式 Provider。"""

from collections.abc import AsyncIterator

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.ai.contracts import ProviderConnection
from app.ai.dto import (
    ChatRequest,
    ChatResponse,
    ChatStreamEvent,
    FunctionCall,
    TokenUsage,
    ToolCall,
    ToolCallDelta,
)
from app.ai.errors import AiErrorCategory, AiProviderError
from app.ai.streaming import ToolCallAccumulator
from app.ai.types import JsonValue


class _WireFunction(BaseModel):
    name: str = ""
    arguments: str = ""


class _WireToolCall(BaseModel):
    id: str | None = None
    type: str | None = None
    function: _WireFunction = Field(default_factory=_WireFunction)
    index: int | None = None


class _WireMessage(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[_WireToolCall] = Field(default_factory=lambda: list[_WireToolCall]())


class _WireChoice(BaseModel):
    message: _WireMessage
    finish_reason: str | None = None


class _WireDeltaChoice(BaseModel):
    delta: _WireMessage
    finish_reason: str | None = None


class _WireUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class _WireResponse(BaseModel):
    choices: list[_WireChoice]
    usage: _WireUsage = Field(default_factory=_WireUsage)


class _WireChunk(BaseModel):
    choices: list[_WireDeltaChoice] = Field(default_factory=lambda: list[_WireDeltaChoice]())
    usage: _WireUsage | None = None


class OpenAICompatibleProvider:
    """复用应用级客户端；每次 complete 或 stream 只发出一次传输请求。"""

    provider_type = "openai_compatible"

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client

    def _payload(self, request: ChatRequest, *, stream: bool) -> dict[str, JsonValue]:
        messages: list[JsonValue] = []
        for message in request.messages:
            item: dict[str, JsonValue] = {"role": message.role, "content": message.content}
            if message.reasoning_content is not None:
                item["reasoning_content"] = message.reasoning_content
            if message.tool_call_id is not None:
                item["tool_call_id"] = message.tool_call_id
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": call.type,
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in message.tool_calls
                ]
            messages.append(item)

        payload: dict[str, JsonValue] = {
            "model": request.model_id,
            "messages": messages,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.thinking is not None:
            payload["thinking"] = {"type": request.thinking.type}
            if request.thinking.effort is not None:
                payload["reasoning_effort"] = request.thinking.effort
        if request.tools:
            payload["tools"] = [
                {
                    "type": tool.type,
                    "function": {
                        "name": tool.function.name,
                        "description": tool.function.description,
                        "parameters": tool.function.parameters,
                        "strict": tool.function.strict,
                    },
                }
                for tool in request.tools
            ]
        if request.response_format.type != "text":
            payload["response_format"] = {"type": request.response_format.type}
        payload.update(request.provider_options)
        return payload

    @staticmethod
    def _headers(connection: ProviderConnection) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {connection.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _url(connection: ProviderConnection) -> str:
        return f"{connection.base_url.rstrip('/')}/chat/completions"

    @staticmethod
    def _status_error(status_code: int) -> AiProviderError:
        if status_code == 401:
            category, message, retryable = (
                AiErrorCategory.AUTHENTICATION,
                "Provider 认证失败",
                False,
            )
        elif status_code == 403:
            category, message, retryable = (
                AiErrorCategory.PERMISSION,
                "Provider 权限不足",
                False,
            )
        elif status_code == 402:
            category, message, retryable = (
                AiErrorCategory.INSUFFICIENT_BALANCE,
                "Provider 余额不足",
                False,
            )
        elif status_code == 429:
            category, message, retryable = (
                AiErrorCategory.RATE_LIMITED,
                "Provider 请求过于频繁",
                True,
            )
        elif status_code >= 500:
            category, message, retryable = (
                AiErrorCategory.UNAVAILABLE,
                "Provider 服务暂时不可用",
                True,
            )
        else:
            category, message, retryable = (
                AiErrorCategory.INVALID_REQUEST,
                "Provider 拒绝了请求",
                False,
            )
        return AiProviderError(
            category=category,
            message=message,
            retryable=retryable,
            status_code=status_code,
        )

    @staticmethod
    def _transport_error(error_type: type[httpx.HTTPError]) -> AiProviderError:
        if issubclass(error_type, httpx.TimeoutException):
            return AiProviderError(
                category=AiErrorCategory.TIMEOUT,
                message="Provider 请求超时",
                retryable=True,
            )
        return AiProviderError(
            category=AiErrorCategory.NETWORK,
            message="Provider 网络连接失败",
            retryable=True,
        )

    @staticmethod
    def _invalid_response() -> AiProviderError:
        return AiProviderError(
            category=AiErrorCategory.INVALID_RESPONSE,
            message="Provider 返回了无效响应",
            retryable=False,
        )

    @staticmethod
    def _usage(usage: _WireUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
        )

    @staticmethod
    def _tool_calls(items: list[_WireToolCall]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for item in items:
            if not item.id or not item.function.name:
                raise ValueError("Tool Call 缺少 id 或函数名")
            calls.append(
                ToolCall(
                    id=item.id,
                    function=FunctionCall(
                        name=item.function.name,
                        arguments=item.function.arguments,
                    ),
                    index=item.index,
                )
            )
        return calls

    def _parse_response(
        self, response: httpx.Response, request: ChatRequest, connection: ProviderConnection
    ) -> ChatResponse | AiProviderError:
        try:
            wire = _WireResponse.model_validate_json(response.content)
            choice = wire.choices[0]
            calls = self._tool_calls(choice.message.tool_calls)
        except IndexError, ValidationError, ValueError:
            return self._invalid_response()
        return ChatResponse(
            text=choice.message.content or "",
            reasoning=choice.message.reasoning_content,
            tool_calls=calls,
            finish_reason=choice.finish_reason,
            usage=self._usage(wire.usage),
            provider_id=connection.provider_id,
            model_id=request.model_id,
        )

    async def complete(self, request: ChatRequest, connection: ProviderConnection) -> ChatResponse:
        try:
            response = await self._http_client.post(
                self._url(connection),
                headers=self._headers(connection),
                json=self._payload(request, stream=False),
            )
        except httpx.HTTPError as error:
            raise self._transport_error(type(error)) from None
        if response.status_code >= 400:
            raise self._status_error(response.status_code)
        parsed = self._parse_response(response, request, connection)
        if isinstance(parsed, AiProviderError):
            raise parsed
        return parsed

    async def stream(
        self, request: ChatRequest, connection: ProviderConnection
    ) -> AsyncIterator[ChatStreamEvent]:
        stream_error: AiProviderError | None = None
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls = ToolCallAccumulator()
        usage = _WireUsage()
        finish_reason: str | None = None
        saw_done = False
        try:
            async with self._http_client.stream(
                "POST",
                self._url(connection),
                headers=self._headers(connection),
                json=self._payload(request, stream=True),
            ) as response:
                if response.status_code >= 400:
                    stream_error = self._status_error(response.status_code)
                else:
                    async for line in response.aiter_lines():
                        stripped = line.strip()
                        if not stripped or stripped.startswith(":"):
                            continue
                        if not stripped.startswith("data:"):
                            stream_error = self._invalid_response()
                            break
                        data = stripped.removeprefix("data:").strip()
                        if data == "[DONE]":
                            saw_done = True
                            break
                        try:
                            chunk = _WireChunk.model_validate_json(data)
                        except ValidationError:
                            stream_error = self._invalid_response()
                            break
                        if chunk.usage is not None:
                            usage = chunk.usage
                        if not chunk.choices:
                            continue
                        choice = chunk.choices[0]
                        finish_reason = choice.finish_reason or finish_reason
                        delta = choice.delta
                        if delta.reasoning_content:
                            reasoning_parts.append(delta.reasoning_content)
                            yield ChatStreamEvent(
                                kind="reasoning_delta",
                                reasoning_delta=delta.reasoning_content,
                            )
                        if delta.content:
                            text_parts.append(delta.content)
                            yield ChatStreamEvent(kind="text_delta", text_delta=delta.content)
                        for wire_call in delta.tool_calls:
                            if wire_call.index is None:
                                stream_error = self._invalid_response()
                                break
                            call_delta = ToolCallDelta(
                                index=wire_call.index,
                                id=wire_call.id,
                                type="function" if wire_call.type == "function" else None,
                                name_delta=wire_call.function.name,
                                arguments_delta=wire_call.function.arguments,
                            )
                            tool_calls.add(call_delta)
                            yield ChatStreamEvent(
                                kind="tool_call_delta", tool_call_deltas=[call_delta]
                            )
                        if stream_error is not None:
                            break
        except httpx.HTTPError as error:
            stream_error = self._transport_error(type(error))

        if stream_error is not None:
            raise stream_error
        if not saw_done:
            raise self._invalid_response()
        try:
            completed_calls = tool_calls.finish()
        except ValueError:
            raise self._invalid_response() from None
        yield ChatStreamEvent(
            kind="completed",
            response=ChatResponse(
                text="".join(text_parts),
                reasoning="".join(reasoning_parts) or None,
                tool_calls=completed_calls,
                finish_reason=finish_reason,
                usage=self._usage(usage),
                provider_id=connection.provider_id,
                model_id=request.model_id,
            ),
        )
