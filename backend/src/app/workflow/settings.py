"""固定 AI 工作流任务的配置值、快照与业务错误。"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.types import JsonValue


class TaskKey(StrEnum):
    LOCATION_SIMULATION = "location_simulation"
    ATTRIBUTE_MEMORY_ANALYSIS = "attribute_memory_analysis"


class StructuredOutputMode(StrEnum):
    AUTO = "auto"
    NATIVE = "native"
    PROMPT = "prompt"


PROTECTED_PROVIDER_OPTION_KEYS = frozenset(
    {
        "model",
        "messages",
        "input",
        "authorization",
        "api_key",
        "base_url",
        "stream",
        "temperature",
        "max_tokens",
        "max_output_tokens",
        "thinking",
        "reasoning_effort",
        "tools",
        "tool_choice",
        "response_format",
        "json_schema",
    }
)

ReasoningEffort = Literal["high", "max"]
type FrozenJsonValue = (
    str
    | int
    | float
    | bool
    | None
    | tuple["FrozenJsonValue", ...]
    | Mapping[str, "FrozenJsonValue"]
)


class TaskSettingNotFoundError(Exception):
    """数据库缺少固定任务行，表示安装数据不完整。"""


class TaskSettingValidationError(Exception):
    """任务参数违反由程序拥有的字段或任务边界。"""


class TaskSettingConfigurationError(Exception):
    """模型选择或能力不足，当前配置不能保存或运行。"""


class TaskSettingPersistenceError(Exception):
    """持久化失败的固定安全边界，不携带 SQL、配置值或异常链。"""


class TaskSettingUpdate(BaseModel):
    """保存一个固定任务时由 API 和 Service 共用的受控值对象。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: int | None = Field(gt=0)
    temperature: float | None = Field(ge=0, le=2)
    max_output_tokens: int | None = Field(gt=0)
    reasoning_effort: ReasoningEffort | None
    timeout_seconds: int = Field(gt=0)
    extra_prompt: str
    structured_output_mode: StructuredOutputMode
    provider_options: dict[str, JsonValue]
    memory_target_chars: int | None = Field(gt=0)
    memory_max_chars: int | None = Field(gt=0)


@dataclass(frozen=True)
class TaskSettingRecord:
    """可查询的全局配置；model_id 为空仍是合法的未配置状态。"""

    task_key: TaskKey
    model_id: int | None
    temperature: float | None
    max_output_tokens: int | None
    reasoning_effort: ReasoningEffort | None
    timeout_seconds: int
    extra_prompt: str
    structured_output_mode: StructuredOutputMode
    provider_options: dict[str, JsonValue]
    memory_target_chars: int | None
    memory_max_chars: int | None
    version: int
    updated_at: datetime


@dataclass(frozen=True)
class TaskSettingSnapshot:
    """新轮次冻结的可运行配置，包含 auto 解析后的实际输出策略。"""

    task_key: TaskKey
    model_id: int
    temperature: float | None
    max_output_tokens: int | None
    reasoning_effort: ReasoningEffort | None
    timeout_seconds: int
    extra_prompt: str
    structured_output_mode: StructuredOutputMode
    provider_options: Mapping[str, FrozenJsonValue]
    memory_target_chars: int | None
    memory_max_chars: int | None
    version: int
    updated_at: datetime
    resolved_structured_output_mode: StructuredOutputMode


def normalized_provider_option_key(key: str) -> str:
    """折叠大小写及常见分隔符，避免换一种拼写绕过程序字段所有权。"""

    return "".join(character for character in key.casefold() if character.isalnum())


def conflicting_provider_option_keys(options: dict[str, JsonValue]) -> tuple[str, ...]:
    protected = {normalized_provider_option_key(key) for key in PROTECTED_PROVIDER_OPTION_KEYS}
    return tuple(sorted(key for key in options if normalized_provider_option_key(key) in protected))


def freeze_json(value: JsonValue) -> FrozenJsonValue:
    """递归冻结运行快照，防止节点在执行期间意外改写共享配置。"""

    if isinstance(value, dict):
        return freeze_json_object(value)
    if isinstance(value, list):
        return tuple(freeze_json(item) for item in value)
    return value


def freeze_json_object(value: dict[str, JsonValue]) -> Mapping[str, FrozenJsonValue]:
    """保留根节点对象类型，供运行快照获得精确的只读 Mapping。"""

    return MappingProxyType({key: freeze_json(item) for key, item in value.items()})
