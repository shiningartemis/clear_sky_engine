"""固定 AI 节点的安全请求构建、结构校验与重试调用。"""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import fields, is_dataclass
from time import monotonic
from typing import Protocol, cast

from pydantic import BaseModel, ValidationError

from app.ai.contracts import ProviderConnection, ProviderRegistry
from app.ai.dto import ChatMessage, ChatRequest, ChatResponse, ResponseFormat, ThinkingConfig
from app.ai.errors import AiErrorCategory, AiProviderError
from app.ai.service import ModelRecord, ProviderConnectionRecord, RunnableTaskSettingsBundle
from app.ai.types import JsonValue
from app.workflow.context import AttributeMemoryContext, LocationSimulationContext
from app.workflow.definitions import ATTRIBUTE_MEMORY_ANALYSIS, LOCATION_SIMULATION, TaskDefinition
from app.workflow.retry import AttemptObserver, AttemptResult, RetryPolicy
from app.workflow.schemas import (
    AttributeMemoryAnalysisOutput,
    LocationSimulationOutput,
    OutputBoundaryError,
    validate_attribute_memory_output,
    validate_location_simulation_output,
)
from app.workflow.settings import FrozenJsonValue, TaskKey, TaskSettingSnapshot

LOGGER = logging.getLogger(__name__)


class TaskInvocationSettings(Protocol):
    """调用前读取一次已冻结配置所需的最小设置边界。"""

    def get_runnable_task_setting(self, task_key: TaskKey) -> TaskSettingSnapshot: ...

    def get_model(self, model_id: int) -> ModelRecord: ...

    def get_provider_connection(self, provider_id: int) -> ProviderConnectionRecord: ...

    def freeze_runnable_tasks(self) -> RunnableTaskSettingsBundle: ...


def _thaw_json(value: object) -> JsonValue:
    """冻结快照只在请求边界解冻为 JSON，禁止把可写引用传入重试闭包。"""

    if isinstance(value, Mapping):
        items = cast("Mapping[object, object]", value).items()
        return {str(key): _thaw_json(item) for key, item in items}
    if isinstance(value, tuple):
        items = cast("tuple[object, ...]", value)
        return [_thaw_json(item) for item in items]
    if value is None or type(value) in {str, int, float, bool}:
        return cast("JsonValue", value)
    raise TypeError("冻结 Provider 参数包含非 JSON 值")


def _thaw_json_object(value: Mapping[str, FrozenJsonValue]) -> dict[str, JsonValue]:
    """任务配置规定 Provider 参数根节点为对象，保留未知厂商字段的顶层结构。"""

    return {key: _thaw_json(item) for key, item in value.items()}


def _context_json(value: object) -> JsonValue:
    """只序列化 ContextBuilder 冻结对象，避免扩大 AI 可见的数据范围。"""

    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _context_json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        items = cast("Mapping[object, object]", value).items()
        return {str(key): _context_json(item) for key, item in items}
    if isinstance(value, tuple):
        items = cast("tuple[object, ...]", value)
        return [_context_json(item) for item in items]
    if value is None or type(value) in {str, int, float, bool}:
        return cast("JsonValue", value)
    raise TypeError("AI 上下文包含未声明的值类型")


def _schema_constraint(output_model: type[BaseModel]) -> str:
    schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False, sort_keys=True)
    return f"必须只输出符合以下 JSON Schema 的 JSON 对象: {schema}"


class TaskInvoker:
    """将冻结上下文调用为严格输出；每个节点只通过一个 RetryPolicy 计数。"""

    def __init__(
        self,
        settings: TaskInvocationSettings,
        registry: ProviderRegistry,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._retry_policy = retry_policy or RetryPolicy()

    def freeze_for_run(self) -> TaskInvoker:
        """在慢 I/O 开始前冻结所有节点配置，保证保存操作只对下一轮生效。"""

        return TaskInvoker(
            self._settings.freeze_runnable_tasks(),
            self._registry,
            self._retry_policy,
        )

    @property
    def memory_max_chars(self) -> int:
        """只从运行前冻结 bundle 读取上限，结算期间不得再次访问数据库配置。"""

        snapshot = self._settings.get_runnable_task_setting(ATTRIBUTE_MEMORY_ANALYSIS.task_key)
        return self._require_memory_max_chars(snapshot)

    async def invoke_location(
        self,
        context: LocationSimulationContext,
        *,
        on_attempt: AttemptObserver | None = None,
    ) -> AttemptResult[LocationSimulationOutput]:
        return await self._invoke(
            definition=LOCATION_SIMULATION,
            context=context,
            on_attempt=on_attempt,
            parse_and_validate=lambda response, _snapshot: validate_location_simulation_output(
                self._parse_output(LocationSimulationOutput, response),
                expected_location_id=context.location_id,
                expected_role_ids={role.role_id for role in context.roles},
            ),
        )

    async def invoke_attribute_memory(
        self,
        context: AttributeMemoryContext,
        *,
        on_attempt: AttemptObserver | None = None,
    ) -> AttemptResult[AttributeMemoryAnalysisOutput]:
        event_keys_by_role = {
            role.role_id: {event.event_key for event in role.known_events} for role in context.roles
        }
        return await self._invoke(
            definition=ATTRIBUTE_MEMORY_ANALYSIS,
            context=context,
            on_attempt=on_attempt,
            parse_and_validate=lambda response, snapshot: validate_attribute_memory_output(
                self._parse_output(AttributeMemoryAnalysisOutput, response),
                expected_location_id=context.location_id,
                expected_role_ids={role.role_id for role in context.roles},
                valid_event_keys_by_role=event_keys_by_role,
                memory_max_chars=self._require_memory_max_chars(snapshot),
            ),
        )

    @staticmethod
    def _require_memory_max_chars(snapshot: TaskSettingSnapshot) -> int:
        """属性任务的固定配置缺少摘要上限时，拒绝开始任何外部调用。"""

        if snapshot.memory_max_chars is None:
            raise RuntimeError("属性与记忆任务缺少记忆摘要硬上限")
        return snapshot.memory_max_chars

    async def _invoke[OutputT](
        self,
        *,
        definition: TaskDefinition,
        context: object,
        on_attempt: AttemptObserver | None,
        parse_and_validate: Callable[[ChatResponse, TaskSettingSnapshot], OutputT],
    ) -> AttemptResult[OutputT]:
        snapshot = self._settings.get_runnable_task_setting(definition.task_key)
        model = self._settings.get_model(snapshot.model_id)
        connection_record = self._settings.get_provider_connection(model.provider_id)
        request = self._build_request(definition, context, snapshot, model)
        connection = ProviderConnection(
            provider_id=connection_record.provider_id,
            base_url=connection_record.base_url,
            api_key=connection_record.api_key,
            options=connection_record.options,
        )
        provider = self._registry.get(connection_record.provider_type)

        async def operation(attempt: int) -> OutputT:
            started = monotonic()
            response: ChatResponse | None = None
            try:
                async with asyncio.timeout(snapshot.timeout_seconds):
                    response = await provider.complete(request, connection)
                validated = parse_and_validate(response, snapshot)
            except OutputBoundaryError:
                error = AiProviderError(
                    category=AiErrorCategory.INVALID_RESPONSE,
                    message="AI 任务返回的结构化输出违反程序边界",
                    retryable=True,
                )
                self._log_attempt(
                    definition.task_key, model.id, attempt, started, error.category, response
                )
                raise error from None
            except TimeoutError:
                error = AiProviderError(
                    category=AiErrorCategory.TIMEOUT,
                    message="AI 任务调用超时",
                    retryable=True,
                )
                self._log_attempt(
                    definition.task_key, model.id, attempt, started, error.category, None
                )
                raise error from None
            except AiProviderError as error:
                self._log_attempt(
                    definition.task_key, model.id, attempt, started, error.category, response
                )
                raise
            self._log_attempt(
                definition.task_key,
                model.id,
                attempt,
                started,
                None,
                response,
            )
            return validated

        return await self._retry_policy.run(operation, on_attempt=on_attempt)

    @staticmethod
    def _build_request(
        definition: TaskDefinition,
        context: object,
        snapshot: TaskSettingSnapshot,
        model: ModelRecord,
    ) -> ChatRequest:
        system_parts = [definition.system_prompt]
        if snapshot.extra_prompt:
            system_parts.append(snapshot.extra_prompt)
        if snapshot.resolved_structured_output_mode.value == "prompt":
            system_parts.append(_schema_constraint(definition.output_model))
        thinking = (
            ThinkingConfig(type="enabled", effort=snapshot.reasoning_effort)
            if snapshot.reasoning_effort is not None
            else None
        )
        response_format = ResponseFormat(
            type=(
                "json_object"
                if snapshot.resolved_structured_output_mode.value == "native"
                else "text"
            )
        )
        return ChatRequest(
            model_id=model.remote_model,
            messages=[
                ChatMessage(role="system", content="\n\n".join(system_parts)),
                ChatMessage(
                    role="user",
                    content=json.dumps(
                        _context_json(context), ensure_ascii=False, separators=(",", ":")
                    ),
                ),
            ],
            temperature=snapshot.temperature,
            max_output_tokens=snapshot.max_output_tokens,
            thinking=thinking,
            response_format=response_format,
            provider_options=_thaw_json_object(snapshot.provider_options),
        )

    @staticmethod
    def _parse_output[OutputT: BaseModel](
        output_model: type[OutputT], response: ChatResponse
    ) -> OutputT:
        try:
            return output_model.model_validate_json(response.text)
        except ValidationError, ValueError:
            raise AiProviderError(
                category=AiErrorCategory.INVALID_RESPONSE,
                message="AI 任务返回的结构化输出无效",
                retryable=True,
            ) from None

    @staticmethod
    def _log_attempt(
        task_key: TaskKey,
        model_id: int,
        attempt: int,
        started: float,
        error_category: AiErrorCategory | None,
        response: ChatResponse | None,
    ) -> None:
        duration_ms = int((monotonic() - started) * 1000)
        if error_category is not None:
            if response is None:
                LOGGER.info(
                    "AI 节点完成 task_key=%s model_id=%s attempt=%s duration_ms=%s "
                    "result_category=%s",
                    task_key,
                    model_id,
                    attempt,
                    duration_ms,
                    error_category.value,
                )
                return
            LOGGER.info(
                "AI 节点完成 task_key=%s model_id=%s attempt=%s duration_ms=%s result_category=%s "
                "input_tokens=%s output_tokens=%s total_tokens=%s",
                task_key,
                model_id,
                attempt,
                duration_ms,
                error_category.value,
                response.usage.input_tokens,
                response.usage.output_tokens,
                response.usage.total_tokens,
            )
            return
        if response is None:
            raise RuntimeError("成功日志缺少 AI 响应")
        LOGGER.info(
            "AI 节点完成 task_key=%s model_id=%s attempt=%s duration_ms=%s result_category=success "
            "input_tokens=%s output_tokens=%s total_tokens=%s",
            task_key,
            model_id,
            attempt,
            duration_ms,
            response.usage.input_tokens,
            response.usage.output_tokens,
            response.usage.total_tokens,
        )
