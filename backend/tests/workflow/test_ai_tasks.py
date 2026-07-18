import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.ai.contracts import ProviderConnection, ProviderRegistry
from app.ai.dto import ChatRequest, ChatResponse, ChatStreamEvent, TokenUsage
from app.ai.errors import AiErrorCategory, AiProviderError
from app.ai.openai_compatible import OpenAICompatibleProvider
from app.ai.service import ModelRecord, ProviderConnectionRecord, RunnableTaskSettingsBundle
from app.workflow.ai_tasks import TaskInvoker
from app.workflow.context import (
    AttributeMemoryContext,
    FrozenEventKnowledge,
    FrozenObjectiveEvent,
    FrozenRoleChronicle,
    LocationSimulationContext,
    RoleAttributeMemoryContext,
    RoleSimulationContext,
)
from app.workflow.retry import RetryPolicy
from app.workflow.settings import (
    FrozenJsonValue,
    StructuredOutputMode,
    TaskKey,
    TaskSettingSnapshot,
)


def _location_context() -> LocationSimulationContext:
    return LocationSimulationContext(
        location_id="campus",
        day=1,
        time_slot="morning",
        player_intent="向朋友打招呼",
        roles=(
            RoleSimulationContext(
                role_id=1,
                name="天",
                persona="谨慎",
                system_prompt="保持克制",
                world_book="校园",
                effective_attributes={"mood": 1},
                attribute_update_rules={"mood": "可增减"},
                attribute_version=1,
                long_term_memory="",
                recent_turns=(),
            ),
        ),
    )


def _valid_location_output() -> str:
    return json.dumps(
        {
            "location_id": "campus",
            "groups": [{"group_id": "g1", "role_ids": [1]}],
            "events": [],
            "chronicles": [{"role_id": 1, "content": "天独自散步。", "known_event_keys": []}],
        }
    )


def _attribute_context() -> AttributeMemoryContext:
    return AttributeMemoryContext(
        location_id="campus",
        groups=(),
        roles=(
            RoleAttributeMemoryContext(
                role_id=1,
                chronicle=FrozenRoleChronicle(
                    role_id=1,
                    content="天独自散步。",
                    known_event_keys=("event-1",),
                ),
                known_events=(
                    FrozenObjectiveEvent(
                        event_key="event-1",
                        group_id="g1",
                        event_type="walk",
                        fact={"summary": "散步"},
                        knowledge=(
                            FrozenEventKnowledge(
                                role_id=1,
                                level="participant",
                                perspective_notes="亲历",
                            ),
                        ),
                    ),
                ),
                effective_attributes={"mood": 1},
                attribute_update_rules={"mood": "可增减"},
                attribute_version=1,
            ),
        ),
    )


def _valid_attribute_output() -> str:
    return json.dumps(
        {
            "location_id": "campus",
            "roles": [
                {
                    "role_id": 1,
                    "attribute_update_intents": [],
                    "memory_append": "天记得这次独自散步。",
                }
            ],
        }
    )


def _snapshot(
    mode: StructuredOutputMode,
    *,
    task_key: TaskKey = TaskKey.LOCATION_SIMULATION,
    provider_options: dict[str, FrozenJsonValue] | None = None,
) -> TaskSettingSnapshot:
    return TaskSettingSnapshot(
        task_key=task_key,
        model_id=8,
        temperature=0.4,
        max_output_tokens=256,
        reasoning_effort=None,
        timeout_seconds=10,
        extra_prompt="保持简洁",
        structured_output_mode=mode,
        provider_options=provider_options or {"seed": 7},
        memory_target_chars=20 if task_key is TaskKey.ATTRIBUTE_MEMORY_ANALYSIS else None,
        memory_max_chars=50 if task_key is TaskKey.ATTRIBUTE_MEMORY_ANALYSIS else None,
        version=2,
        updated_at=datetime.now(UTC),
        resolved_structured_output_mode=mode,
    )


@dataclass
class FakeSettings:
    snapshot: TaskSettingSnapshot
    provider_type: str = "fake"
    snapshot_calls: int = 0
    model_calls: int = 0
    connection_calls: int = 0

    def get_runnable_task_setting(self, task_key: TaskKey) -> TaskSettingSnapshot:
        assert task_key is self.snapshot.task_key
        self.snapshot_calls += 1
        return self.snapshot

    def get_model(self, model_id: int) -> ModelRecord:
        assert model_id == 8
        self.model_calls += 1
        return ModelRecord(
            id=8,
            provider_id=3,
            display_name="测试模型",
            remote_model="model-a",
            capabilities={"json_output": True},
            enabled=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    def get_provider_connection(self, provider_id: int) -> ProviderConnectionRecord:
        assert provider_id == 3
        self.connection_calls += 1
        return ProviderConnectionRecord(
            provider_id=3,
            provider_type=self.provider_type,
            base_url="https://provider.test/v1",
            api_key=SecretStr("test-only-key"),
            options={},
        )

    def freeze_runnable_tasks(self) -> RunnableTaskSettingsBundle:
        raise AssertionError("直接节点调用不应创建轮次冻结 bundle")


class RunFrozenSettings:
    """模拟运行创建前后保存不同配置，验证真实 TaskInvoker 的冻结边界。"""

    def __init__(self) -> None:
        self.snapshots = {
            TaskKey.LOCATION_SIMULATION: _snapshot(StructuredOutputMode.NATIVE),
            TaskKey.ATTRIBUTE_MEMORY_ANALYSIS: _snapshot(
                StructuredOutputMode.NATIVE,
                task_key=TaskKey.ATTRIBUTE_MEMORY_ANALYSIS,
            ),
        }
        self.bundle_calls = 0

    def freeze_runnable_tasks(self) -> RunnableTaskSettingsBundle:
        self.bundle_calls += 1
        model = ModelRecord(
            id=8,
            provider_id=3,
            display_name="测试模型",
            remote_model="model-a",
            capabilities={"json_output": True},
            enabled=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        connection = ProviderConnectionRecord(
            provider_id=3,
            provider_type="fake",
            base_url="https://provider.test/v1",
            api_key=SecretStr("test-only-key"),
            options={},
        )
        return RunnableTaskSettingsBundle(
            task_settings=self.snapshots.copy(),
            models={model.id: model},
            connections={connection.provider_id: connection},
        )

    def get_runnable_task_setting(self, task_key: TaskKey) -> TaskSettingSnapshot:
        raise AssertionError("轮次冻结不得逐项读取任务设置")

    def get_model(self, model_id: int) -> ModelRecord:
        raise AssertionError("轮次冻结不得逐项读取模型")

    def get_provider_connection(self, provider_id: int) -> ProviderConnectionRecord:
        raise AssertionError("轮次冻结不得逐项读取 Provider 连接")


class FakeProvider:
    provider_type = "fake"

    def __init__(self, results: list[ChatResponse | Exception]) -> None:
        self._results = results
        self.requests: list[ChatRequest] = []

    async def complete(self, request: ChatRequest, connection: ProviderConnection) -> ChatResponse:
        del connection
        self.requests.append(request)
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def stream(
        self, request: ChatRequest, connection: ProviderConnection
    ) -> AsyncIterator[ChatStreamEvent]:
        del request, connection
        if False:
            yield ChatStreamEvent(kind="text_delta")


def _response(text: str) -> ChatResponse:
    return ChatResponse(
        text=text,
        reasoning=None,
        tool_calls=[],
        finish_reason="stop",
        usage=TokenUsage(input_tokens=2, output_tokens=3, total_tokens=5),
        provider_id=3,
        model_id="model-a",
    )


async def test_invoker_retries_invalid_schema_then_returns_validated_output() -> None:
    provider = FakeProvider([_response("not-json"), _response(_valid_location_output())])
    settings = FakeSettings(_snapshot(StructuredOutputMode.NATIVE))
    invoker = TaskInvoker(settings, ProviderRegistry([provider]), RetryPolicy(backoff_seconds=0))

    result = await invoker.invoke_location(_location_context())

    assert result.attempt == 2
    assert result.value.location_id == "campus"
    assert len(provider.requests) == 2


async def test_invoker_retries_location_boundary_error_and_keeps_usage_in_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    invalid_boundary = json.dumps(
        {
            "location_id": "campus",
            "groups": [{"group_id": "g1", "role_ids": [99]}],
            "events": [],
            "chronicles": [{"role_id": 1, "content": "天独自散步。", "known_event_keys": []}],
        }
    )
    provider = FakeProvider([_response(invalid_boundary), _response(_valid_location_output())])
    invoker = TaskInvoker(
        FakeSettings(_snapshot(StructuredOutputMode.NATIVE)),
        ProviderRegistry([provider]),
        RetryPolicy(backoff_seconds=0),
    )

    with caplog.at_level("INFO", logger="app.workflow.ai_tasks"):
        result = await invoker.invoke_location(_location_context())

    assert result.attempt == 2
    assert len(provider.requests) == 2
    assert any(
        "result_category=invalid_response" in record.message
        and "input_tokens=2" in record.message
        and "output_tokens=3" in record.message
        for record in caplog.records
    )


async def test_invoker_runs_attribute_memory_node_with_its_own_event_boundary() -> None:
    provider = FakeProvider([_response(_valid_attribute_output())])
    invoker = TaskInvoker(
        FakeSettings(
            _snapshot(
                StructuredOutputMode.NATIVE,
                task_key=TaskKey.ATTRIBUTE_MEMORY_ANALYSIS,
            )
        ),
        ProviderRegistry([provider]),
        RetryPolicy(backoff_seconds=0),
    )

    result = await invoker.invoke_attribute_memory(_attribute_context())

    assert result.attempt == 1
    assert result.value.roles[0].memory_append == "天记得这次独自散步。"


@respx.mock
async def test_invoker_and_openai_provider_issue_at_most_three_real_http_requests() -> None:
    route = respx.post("https://provider.test/v1/chat/completions").mock(
        return_value=httpx.Response(503, json={"error": {"message": "temporary"}})
    )
    settings = FakeSettings(
        _snapshot(StructuredOutputMode.NATIVE), provider_type="openai_compatible"
    )
    async with httpx.AsyncClient() as client:
        invoker = TaskInvoker(
            settings,
            ProviderRegistry([OpenAICompatibleProvider(client)]),
            RetryPolicy(backoff_seconds=0),
        )
        with pytest.raises(AiProviderError) as captured:
            await invoker.invoke_location(_location_context())

    assert captured.value.category is AiErrorCategory.UNAVAILABLE
    assert route.call_count == 3


async def test_invoker_retries_only_the_single_provider_transport_attempt() -> None:
    transient = AiProviderError(
        category=AiErrorCategory.NETWORK,
        message="网络暂时不可用",
        retryable=True,
    )
    provider = FakeProvider([transient, transient, _response(_valid_location_output())])
    invoker = TaskInvoker(
        FakeSettings(_snapshot(StructuredOutputMode.NATIVE)),
        ProviderRegistry([provider]),
        RetryPolicy(backoff_seconds=0),
    )

    result = await invoker.invoke_location(_location_context())

    assert result.attempt == 3
    assert len(provider.requests) == 3


async def test_invoker_does_not_retry_authentication_error() -> None:
    authentication = AiProviderError(
        category=AiErrorCategory.AUTHENTICATION,
        message="认证失败",
        retryable=False,
    )
    provider = FakeProvider([authentication])
    invoker = TaskInvoker(
        FakeSettings(_snapshot(StructuredOutputMode.NATIVE)),
        ProviderRegistry([provider]),
        RetryPolicy(backoff_seconds=0),
    )

    with pytest.raises(AiProviderError) as captured:
        await invoker.invoke_location(_location_context())

    assert captured.value.category is AiErrorCategory.AUTHENTICATION
    assert len(provider.requests) == 1


@pytest.mark.parametrize("mode", [StructuredOutputMode.NATIVE, StructuredOutputMode.PROMPT])
async def test_native_and_prompt_modes_apply_the_same_output_schema(
    mode: StructuredOutputMode,
) -> None:
    provider = FakeProvider([_response(_valid_location_output())])
    invoker = TaskInvoker(
        FakeSettings(_snapshot(mode)),
        ProviderRegistry([provider]),
        RetryPolicy(backoff_seconds=0),
    )

    result = await invoker.invoke_location(_location_context())

    request = provider.requests[0]
    if mode is StructuredOutputMode.NATIVE:
        assert request.response_format.type == "json_object"
    else:
        assert request.response_format.type == "text"
        assert "LocationSimulationOutput" in (request.messages[0].content or "")
    assert result.value.model_json_schema() == result.value.__class__.model_json_schema()


async def test_invoker_freezes_configuration_before_retrying() -> None:
    first = AiProviderError(
        category=AiErrorCategory.TIMEOUT,
        message="超时",
        retryable=True,
    )
    provider = FakeProvider([first, _response(_valid_location_output())])
    settings = FakeSettings(_snapshot(StructuredOutputMode.NATIVE, provider_options={"seed": 7}))
    invoker = TaskInvoker(settings, ProviderRegistry([provider]), RetryPolicy(backoff_seconds=0))

    await invoker.invoke_location(_location_context())

    assert settings.snapshot_calls == 1
    assert settings.model_calls == 1
    assert settings.connection_calls == 1
    assert [request.provider_options for request in provider.requests] == [{"seed": 7}, {"seed": 7}]


async def test_invoker_freezes_both_task_settings_before_a_run_starts() -> None:
    provider = FakeProvider([_response(_valid_location_output())])
    settings = RunFrozenSettings()
    invoker = TaskInvoker(settings, ProviderRegistry([provider]), RetryPolicy(backoff_seconds=0))

    frozen = invoker.freeze_for_run()
    frozen_memory_max_chars = frozen.memory_max_chars
    settings.snapshots[TaskKey.LOCATION_SIMULATION] = _snapshot(
        StructuredOutputMode.NATIVE,
        provider_options={"seed": 99},
    )
    await frozen.invoke_location(_location_context())

    assert settings.bundle_calls == 1
    assert frozen_memory_max_chars == 50
    assert provider.requests[0].provider_options == {"seed": 7}
