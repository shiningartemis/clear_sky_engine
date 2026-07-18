"""Provider、模型目录与全局 AI 任务设置的事务及密钥边界。"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast

from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.models import AiModel, AiProvider
from app.ai.store import AiSettingsStore
from app.ai.types import JsonValue
from app.workflow.models import AiTaskSetting
from app.workflow.settings import (
    ReasoningEffort,
    StructuredOutputMode,
    TaskKey,
    TaskSettingConfigurationError,
    TaskSettingNotFoundError,
    TaskSettingPersistenceError,
    TaskSettingRecord,
    TaskSettingSnapshot,
    TaskSettingUpdate,
    TaskSettingValidationError,
    conflicting_provider_option_keys,
    freeze_json_object,
)
from app.workflow.store import TaskSettingsStore


class AiSettingsNotFoundError(Exception):
    """请求的 Provider 或模型不存在。"""


class AiSettingsConflictError(Exception):
    """稳定唯一键发生冲突；错误文本不得包含用户输入或密钥。"""


class AiSettingsConfigurationError(Exception):
    """Provider 或模型缺少执行所需配置。"""


@dataclass(frozen=True)
class ProviderRecord:
    id: int
    name: str
    provider_type: str
    base_url: str
    enabled: bool
    extra: dict[str, JsonValue]
    has_api_key: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ModelRecord:
    id: int
    provider_id: int
    display_name: str
    remote_model: str
    capabilities: dict[str, JsonValue]
    enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ProviderConnectionRecord:
    provider_id: int
    provider_type: str
    base_url: str
    api_key: SecretStr
    options: dict[str, JsonValue]


@dataclass(frozen=True)
class RunnableTaskSettingsBundle:
    """同一短 Session 内冻结的全部工作流配置，离开数据库边界后不得再读设置。"""

    task_settings: Mapping[TaskKey, TaskSettingSnapshot]
    models: Mapping[int, ModelRecord]
    connections: Mapping[int, ProviderConnectionRecord]

    def freeze_runnable_tasks(self) -> RunnableTaskSettingsBundle:
        """已冻结 bundle 可安全复用，避免运行中重新访问数据库。"""

        return self

    def get_runnable_task_setting(self, task_key: TaskKey) -> TaskSettingSnapshot:
        return self.task_settings[task_key]

    def get_model(self, model_id: int) -> ModelRecord:
        return self.models[model_id]

    def get_provider_connection(self, provider_id: int) -> ProviderConnectionRecord:
        return self.connections[provider_id]


@dataclass(frozen=True)
class ProviderChanges:
    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    enabled: bool | None = None
    extra: dict[str, JsonValue] | None = None
    api_key_supplied: bool = False
    api_key: str | None = None


@dataclass(frozen=True)
class ModelChanges:
    provider_id: int | None = None
    display_name: str | None = None
    remote_model: str | None = None
    capabilities: dict[str, JsonValue] | None = None
    enabled: bool | None = None


class AiSettingsService:
    """每次调用只持有一个短 Session，提交失败必须先回滚。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _provider_record(provider: AiProvider) -> ProviderRecord:
        return ProviderRecord(
            id=provider.id,
            name=provider.name,
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            enabled=provider.enabled,
            extra=provider.extra_json,
            has_api_key=bool(provider.api_key),
            created_at=provider.created_at,
            updated_at=provider.updated_at,
        )

    @staticmethod
    def _model_record(model: AiModel) -> ModelRecord:
        return ModelRecord(
            id=model.id,
            provider_id=model.provider_id,
            display_name=model.display_name,
            remote_model=model.remote_model,
            capabilities=model.capabilities_json,
            enabled=model.enabled,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _task_setting_record(setting: AiTaskSetting) -> TaskSettingRecord:
        reasoning_effort = setting.reasoning_effort
        if reasoning_effort not in {None, "high", "max"}:
            raise TaskSettingValidationError("任务设置包含无效的思考强度")
        return TaskSettingRecord(
            task_key=TaskKey(setting.task_key),
            model_id=setting.model_id,
            temperature=setting.temperature,
            max_output_tokens=setting.max_output_tokens,
            reasoning_effort=cast("ReasoningEffort | None", reasoning_effort),
            timeout_seconds=setting.timeout_seconds,
            extra_prompt=setting.extra_prompt,
            structured_output_mode=StructuredOutputMode(setting.structured_output_mode),
            # JSON 对象必须脱离 Session，后续保存和调用方修改都不能污染已读配置。
            provider_options=deepcopy(setting.provider_options_json),
            memory_target_chars=setting.memory_target_chars,
            memory_max_chars=setting.memory_max_chars,
            version=setting.version,
            updated_at=setting.updated_at,
        )

    @staticmethod
    def _validate_task_values(task_key: TaskKey, values: TaskSettingUpdate) -> None:
        conflicts = conflicting_provider_option_keys(values.provider_options)
        if conflicts:
            raise TaskSettingValidationError(
                f"provider_options 与程序拥有字段冲突: {', '.join(conflicts)}"
            )
        if task_key is TaskKey.LOCATION_SIMULATION:
            if values.memory_target_chars is not None or values.memory_max_chars is not None:
                raise TaskSettingValidationError("地点推演不得包含记忆字数设置")
            return
        if values.memory_target_chars is None or values.memory_max_chars is None:
            raise TaskSettingValidationError("属性与记忆任务必须包含记忆字数设置")
        if values.memory_target_chars > values.memory_max_chars:
            raise TaskSettingValidationError("记忆字数目标不得大于硬上限")

    @staticmethod
    def _validate_selected_model(model: AiModel | None, mode: StructuredOutputMode) -> None:
        if model is None:
            raise TaskSettingConfigurationError("模型不存在")
        if not model.enabled:
            raise TaskSettingConfigurationError("模型未启用")
        if (
            mode is StructuredOutputMode.NATIVE
            and model.capabilities_json.get("json_output") is not True
        ):
            raise TaskSettingConfigurationError("所选模型不支持原生 JSON 输出")

    @staticmethod
    def _commit(session: Session, conflict_message: str) -> None:
        conflicted = False
        try:
            session.commit()
        except IntegrityError:
            # SQL 参数可能含密钥，异常链不得越过业务边界。
            session.rollback()
            conflicted = True
        if conflicted:
            # 离开 except 后再抛出，彻底丢弃可能携带 SQL 参数的异常上下文。
            raise AiSettingsConflictError(conflict_message)

    @staticmethod
    def _commit_task_setting(session: Session) -> None:
        failed = False
        try:
            session.commit()
        except SQLAlchemyError:
            # SQL 参数可能含自由 Provider JSON 或额外提示词，必须在事务边界显式回滚。
            session.rollback()
            failed = True
        if failed:
            # 离开 except 后抛固定错误，确保原始异常链和敏感 SQL 参数不可达。
            raise TaskSettingPersistenceError("AI 任务设置保存失败")

    def list_providers(self) -> list[ProviderRecord]:
        with self._session_factory() as session:
            return [
                self._provider_record(item) for item in AiSettingsStore(session).list_providers()
            ]

    def get_provider(self, provider_id: int) -> ProviderRecord:
        with self._session_factory() as session:
            provider = AiSettingsStore(session).get_provider(provider_id)
            if provider is None:
                raise AiSettingsNotFoundError("Provider 不存在")
            return self._provider_record(provider)

    def get_provider_connection(self, provider_id: int) -> ProviderConnectionRecord:
        """只向 AI 调用层返回 SecretStr，API 查询仍只得到 has_api_key。"""

        with self._session_factory() as session:
            provider = AiSettingsStore(session).get_provider(provider_id)
            if provider is None:
                raise AiSettingsNotFoundError("Provider 不存在")
            if not provider.api_key:
                raise AiSettingsConfigurationError("Provider 尚未配置 API Key")
            return ProviderConnectionRecord(
                provider_id=provider.id,
                provider_type=provider.provider_type,
                base_url=provider.base_url,
                api_key=SecretStr(provider.api_key),
                options=provider.extra_json,
            )

    def create_provider(
        self,
        *,
        name: str,
        provider_type: str,
        base_url: str,
        api_key: str | None,
        enabled: bool,
        extra: dict[str, JsonValue],
    ) -> ProviderRecord:
        now = datetime.now(UTC)
        provider = AiProvider(
            name=name,
            provider_type=provider_type,
            base_url=base_url,
            api_key=api_key,
            enabled=enabled,
            extra_json=extra,
            created_at=now,
            updated_at=now,
        )
        with self._session_factory() as session:
            AiSettingsStore(session).add_provider(provider)
            self._commit(session, "Provider 名称已存在")
            session.refresh(provider)
            return self._provider_record(provider)

    def update_provider(self, provider_id: int, changes: ProviderChanges) -> ProviderRecord:
        with self._session_factory() as session:
            provider = AiSettingsStore(session).get_provider(provider_id)
            if provider is None:
                raise AiSettingsNotFoundError("Provider 不存在")
            for field_name in ("name", "provider_type", "base_url", "enabled"):
                value = getattr(changes, field_name)
                if value is not None:
                    setattr(provider, field_name, value)
            if changes.extra is not None:
                provider.extra_json = changes.extra
            if changes.api_key_supplied:
                provider.api_key = changes.api_key
            provider.updated_at = datetime.now(UTC)
            self._commit(session, "Provider 名称已存在")
            session.refresh(provider)
            return self._provider_record(provider)

    def delete_provider(self, provider_id: int) -> None:
        with self._session_factory() as session:
            store = AiSettingsStore(session)
            provider = store.get_provider(provider_id)
            if provider is None:
                raise AiSettingsNotFoundError("Provider 不存在")
            store.delete_provider(provider)
            self._commit(session, "Provider 的模型已被 AI 任务使用")

    def list_models(self, provider_id: int | None) -> list[ModelRecord]:
        with self._session_factory() as session:
            return [
                self._model_record(item)
                for item in AiSettingsStore(session).list_models(provider_id)
            ]

    def get_model(self, model_id: int) -> ModelRecord:
        with self._session_factory() as session:
            model = AiSettingsStore(session).get_model(model_id)
            if model is None:
                raise AiSettingsNotFoundError("模型不存在")
            return self._model_record(model)

    def create_model(
        self,
        *,
        provider_id: int,
        display_name: str,
        remote_model: str,
        capabilities: dict[str, JsonValue],
        enabled: bool,
    ) -> ModelRecord:
        now = datetime.now(UTC)
        model = AiModel(
            provider_id=provider_id,
            display_name=display_name,
            remote_model=remote_model,
            capabilities_json=capabilities,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        with self._session_factory() as session:
            store = AiSettingsStore(session)
            if store.get_provider(provider_id) is None:
                raise AiSettingsNotFoundError("Provider 不存在")
            store.add_model(model)
            self._commit(session, "Provider 下的远端模型已存在")
            session.refresh(model)
            return self._model_record(model)

    def update_model(self, model_id: int, changes: ModelChanges) -> ModelRecord:
        with self._session_factory() as session:
            store = AiSettingsStore(session)
            model = store.get_model(model_id)
            if model is None:
                raise AiSettingsNotFoundError("模型不存在")
            if changes.provider_id is not None:
                if store.get_provider(changes.provider_id) is None:
                    raise AiSettingsNotFoundError("Provider 不存在")
                model.provider_id = changes.provider_id
            for field_name in ("display_name", "remote_model", "enabled"):
                value = getattr(changes, field_name)
                if value is not None:
                    setattr(model, field_name, value)
            if changes.capabilities is not None:
                model.capabilities_json = changes.capabilities
            model.updated_at = datetime.now(UTC)
            self._commit(session, "Provider 下的远端模型已存在")
            session.refresh(model)
            return self._model_record(model)

    def delete_model(self, model_id: int) -> None:
        with self._session_factory() as session:
            store = AiSettingsStore(session)
            model = store.get_model(model_id)
            if model is None:
                raise AiSettingsNotFoundError("模型不存在")
            store.delete_model(model)
            self._commit(session, "模型已被 AI 任务使用")

    def list_task_settings(self) -> list[TaskSettingRecord]:
        with self._session_factory() as session:
            return [
                self._task_setting_record(item)
                for item in TaskSettingsStore(session).list_settings()
            ]

    def get_task_setting(self, task_key: TaskKey) -> TaskSettingRecord:
        with self._session_factory() as session:
            setting = TaskSettingsStore(session).get_setting(task_key)
            if setting is None:
                raise TaskSettingNotFoundError("AI 任务设置不存在")
            return self._task_setting_record(setting)

    def update_task_setting(
        self,
        task_key: TaskKey,
        values: TaskSettingUpdate,
    ) -> TaskSettingRecord:
        self._validate_task_values(task_key, values)
        with self._session_factory() as session:
            setting = TaskSettingsStore(session).get_setting(task_key)
            if setting is None:
                raise TaskSettingNotFoundError("AI 任务设置不存在")
            if values.model_id is not None:
                model = AiSettingsStore(session).get_model(values.model_id)
                self._validate_selected_model(model, values.structured_output_mode)
            setting.model_id = values.model_id
            setting.temperature = values.temperature
            setting.max_output_tokens = values.max_output_tokens
            setting.reasoning_effort = values.reasoning_effort
            setting.timeout_seconds = values.timeout_seconds
            setting.extra_prompt = values.extra_prompt
            setting.structured_output_mode = values.structured_output_mode.value
            setting.provider_options_json = deepcopy(values.provider_options)
            setting.memory_target_chars = values.memory_target_chars
            setting.memory_max_chars = values.memory_max_chars
            # 版本只由成功保存递增；运行中的旧快照继续使用原版本。
            setting.version += 1
            setting.updated_at = datetime.now(UTC)
            self._commit_task_setting(session)
            session.refresh(setting)
            return self._task_setting_record(setting)

    def get_runnable_task_setting(self, task_key: TaskKey) -> TaskSettingSnapshot:
        """在一个短 Session 内冻结任务与模型能力，不执行任何慢 AI I/O。"""

        with self._session_factory() as session:
            setting = TaskSettingsStore(session).get_setting(task_key)
            if setting is None:
                raise TaskSettingNotFoundError("AI 任务设置不存在")
            record = self._task_setting_record(setting)
            if setting.model_id is None:
                raise TaskSettingConfigurationError("AI 任务尚未选择模型")
            model = AiSettingsStore(session).get_model(setting.model_id)
            self._validate_selected_model(model, record.structured_output_mode)
            if record.structured_output_mode is StructuredOutputMode.AUTO:
                supports_native = (
                    model is not None and model.capabilities_json.get("json_output") is True
                )
                resolved = (
                    StructuredOutputMode.NATIVE if supports_native else StructuredOutputMode.PROMPT
                )
            else:
                resolved = record.structured_output_mode
            return TaskSettingSnapshot(
                task_key=record.task_key,
                model_id=setting.model_id,
                temperature=record.temperature,
                max_output_tokens=record.max_output_tokens,
                reasoning_effort=record.reasoning_effort,
                timeout_seconds=record.timeout_seconds,
                extra_prompt=record.extra_prompt,
                structured_output_mode=record.structured_output_mode,
                provider_options=freeze_json_object(record.provider_options),
                memory_target_chars=record.memory_target_chars,
                memory_max_chars=record.memory_max_chars,
                version=record.version,
                updated_at=record.updated_at,
                resolved_structured_output_mode=resolved,
            )

    def freeze_runnable_tasks(self) -> RunnableTaskSettingsBundle:
        """用单一短 Session 原子读取两项任务设置、模型和 Provider 连接。"""

        with self._session_factory() as session:
            ai_store = AiSettingsStore(session)
            settings_store = TaskSettingsStore(session)
            task_settings: dict[TaskKey, TaskSettingSnapshot] = {}
            models: dict[int, ModelRecord] = {}
            connections: dict[int, ProviderConnectionRecord] = {}
            for task_key in TaskKey:
                setting = settings_store.get_setting(task_key)
                if setting is None:
                    raise TaskSettingNotFoundError("AI 任务设置不存在")
                record = self._task_setting_record(setting)
                if setting.model_id is None:
                    raise TaskSettingConfigurationError("AI 任务尚未选择模型")
                model = ai_store.get_model(setting.model_id)
                self._validate_selected_model(model, record.structured_output_mode)
                assert model is not None
                if record.structured_output_mode is StructuredOutputMode.AUTO:
                    resolved = (
                        StructuredOutputMode.NATIVE
                        if model.capabilities_json.get("json_output") is True
                        else StructuredOutputMode.PROMPT
                    )
                else:
                    resolved = record.structured_output_mode
                task_settings[task_key] = TaskSettingSnapshot(
                    task_key=record.task_key,
                    model_id=model.id,
                    temperature=record.temperature,
                    max_output_tokens=record.max_output_tokens,
                    reasoning_effort=record.reasoning_effort,
                    timeout_seconds=record.timeout_seconds,
                    extra_prompt=record.extra_prompt,
                    structured_output_mode=record.structured_output_mode,
                    provider_options=freeze_json_object(record.provider_options),
                    memory_target_chars=record.memory_target_chars,
                    memory_max_chars=record.memory_max_chars,
                    version=record.version,
                    updated_at=record.updated_at,
                    resolved_structured_output_mode=resolved,
                )
                models[model.id] = self._model_record(model)
                if model.provider_id not in connections:
                    provider = ai_store.get_provider(model.provider_id)
                    if provider is None:
                        raise AiSettingsNotFoundError("Provider 不存在")
                    if not provider.api_key:
                        raise AiSettingsConfigurationError("Provider 尚未配置 API Key")
                    connections[provider.id] = ProviderConnectionRecord(
                        provider_id=provider.id,
                        provider_type=provider.provider_type,
                        base_url=provider.base_url,
                        api_key=SecretStr(provider.api_key),
                        options=deepcopy(provider.extra_json),
                    )
            return RunnableTaskSettingsBundle(
                task_settings=MappingProxyType(task_settings),
                models=MappingProxyType(models),
                connections=MappingProxyType(connections),
            )
