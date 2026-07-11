"""跨 Provider 一致的请求、响应与流事件 DTO。"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.types import JsonValue


class FunctionCall(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    arguments: str


class ToolCall(BaseModel):
    id: Annotated[str, Field(min_length=1)]
    type: Literal["function"] = "function"
    function: FunctionCall
    index: int | None = Field(default=None, ge=0)


class FunctionDefinition(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    description: str | None = None
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    strict: bool | None = None


class ToolDefinition(BaseModel):
    type: Literal["function"] = "function"
    function: FunctionDefinition


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=lambda: list[ToolCall]())
    tool_call_id: str | None = None


class ThinkingConfig(BaseModel):
    type: Literal["enabled", "disabled"]
    effort: Literal["high", "max"] | None = None


class ResponseFormat(BaseModel):
    type: Literal["text", "json_object"] = "text"


class TokenUsage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ChatRequest(BaseModel):
    """provider_options 只承载厂商参数，连接信息必须走独立安全边界。"""

    model_config = ConfigDict(frozen=True)

    model_id: Annotated[str, Field(min_length=1)]
    messages: Annotated[list[ChatMessage], Field(min_length=1)]
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, gt=0)
    thinking: ThinkingConfig | None = None
    tools: list[ToolDefinition] = Field(default_factory=lambda: list[ToolDefinition]())
    response_format: ResponseFormat = Field(default_factory=ResponseFormat)
    provider_options: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("provider_options")
    @classmethod
    def reject_sensitive_provider_options(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        blocked = {"apikey", "authorization", "baseurl", "token", "secret"}
        for key in value:
            normalized = key.casefold().replace("_", "").replace("-", "")
            if normalized in blocked:
                raise ValueError("provider_options 不得包含连接或密钥字段")
        return value


class ChatResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    reasoning: str | None
    tool_calls: list[ToolCall]
    finish_reason: str | None
    usage: TokenUsage
    provider_id: int = Field(gt=0)
    model_id: Annotated[str, Field(min_length=1)]


class ChatStreamEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["text_delta", "reasoning_delta", "tool_call_delta", "completed"]
    text_delta: str | None = None
    reasoning_delta: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=lambda: list[ToolCall]())
    response: ChatResponse | None = None
