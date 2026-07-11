"""Provider 与模型目录的事务及密钥边界。"""

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.models import AiModel, AiProvider
from app.ai.store import AiSettingsStore
from app.ai.types import JsonValue


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
    defaults: dict[str, JsonValue]
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
    defaults: dict[str, JsonValue] | None = None
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
            defaults=model.defaults_json,
            enabled=model.enabled,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

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
            session.commit()

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
        defaults: dict[str, JsonValue],
        enabled: bool,
    ) -> ModelRecord:
        now = datetime.now(UTC)
        model = AiModel(
            provider_id=provider_id,
            display_name=display_name,
            remote_model=remote_model,
            capabilities_json=capabilities,
            defaults_json=defaults,
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
            if changes.defaults is not None:
                model.defaults_json = changes.defaults
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
            session.commit()
