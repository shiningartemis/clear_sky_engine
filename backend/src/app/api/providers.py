"""全局 AI Provider 与模型目录 API。"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.ai.connection_test import ConnectionTestResult, ConnectionTestService
from app.ai.contracts import ProviderRegistry
from app.ai.dto import TokenUsage
from app.ai.errors import AiErrorCategory
from app.ai.service import (
    AiSettingsConfigurationError,
    AiSettingsConflictError,
    AiSettingsNotFoundError,
    AiSettingsService,
    ModelChanges,
    ModelRecord,
    ProviderChanges,
    ProviderRecord,
)
from app.ai.types import JsonValue

Name = Annotated[str, Field(min_length=1, max_length=120)]
RemoteModel = Annotated[str, Field(min_length=1, max_length=255)]
BaseUrl = Annotated[str, Field(min_length=1, max_length=2048)]
ProviderType = Literal["openai_compatible", "deepseek"]


class ProviderCreate(BaseModel):
    name: Name
    provider_type: ProviderType
    base_url: BaseUrl
    api_key: SecretStr | None = None
    enabled: bool = True
    extra: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """只接受明确的 HTTP(S) 根地址，避免把无效配置持久化。"""

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url 必须是 HTTP(S) URL")
        return value.rstrip("/")


class ProviderUpdate(BaseModel):
    name: Name | None = None
    provider_type: ProviderType | None = None
    base_url: BaseUrl | None = None
    api_key: SecretStr | None = None
    enabled: bool | None = None
    extra: dict[str, JsonValue] | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return ProviderCreate.validate_base_url(value)


class ProviderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider_type: ProviderType
    base_url: str
    enabled: bool
    extra: dict[str, JsonValue]
    has_api_key: bool
    created_at: datetime
    updated_at: datetime


class ModelCreate(BaseModel):
    provider_id: int = Field(gt=0)
    display_name: Name
    remote_model: RemoteModel
    capabilities: dict[str, JsonValue] = Field(default_factory=dict)
    defaults: dict[str, JsonValue] = Field(default_factory=dict)
    enabled: bool = True


class ModelUpdate(BaseModel):
    provider_id: int | None = Field(default=None, gt=0)
    display_name: Name | None = None
    remote_model: RemoteModel | None = None
    capabilities: dict[str, JsonValue] | None = None
    defaults: dict[str, JsonValue] | None = None
    enabled: bool | None = None


class ModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_id: int
    display_name: str
    remote_model: str
    capabilities: dict[str, JsonValue]
    defaults: dict[str, JsonValue]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ConnectionTestRequest(BaseModel):
    model_id: int = Field(gt=0)


class ConnectionTestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    success: bool
    provider_type: ProviderType
    remote_model: str
    capabilities: dict[str, JsonValue]
    diagnostic: str
    error_category: AiErrorCategory | None
    usage: TokenUsage | None


def _not_found(error: AiSettingsNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def _conflict(error: AiSettingsConflictError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


def _provider_response(record: ProviderRecord) -> ProviderResponse:
    return ProviderResponse.model_validate(record)


def _model_response(record: ModelRecord) -> ModelResponse:
    return ModelResponse.model_validate(record)


def create_provider_router(
    service: AiSettingsService,
    get_registry: Callable[[], ProviderRegistry],
) -> APIRouter:
    """路由只解析 DTO、调用 Service 并转换业务错误。"""

    router = APIRouter(prefix="/api")
    connection_tests = ConnectionTestService(service)

    def _list_providers() -> list[ProviderResponse]:
        return [_provider_response(item) for item in service.list_providers()]

    def _create_provider(payload: ProviderCreate) -> ProviderResponse:
        try:
            record = service.create_provider(
                name=payload.name,
                provider_type=payload.provider_type,
                base_url=payload.base_url,
                api_key=payload.api_key.get_secret_value() if payload.api_key else None,
                enabled=payload.enabled,
                extra=payload.extra,
            )
        except AiSettingsConflictError as error:
            raise _conflict(error) from None
        return _provider_response(record)

    def _get_provider(provider_id: int) -> ProviderResponse:
        try:
            return _provider_response(service.get_provider(provider_id))
        except AiSettingsNotFoundError as error:
            raise _not_found(error) from None

    def _update_provider(provider_id: int, payload: ProviderUpdate) -> ProviderResponse:
        key_supplied = "api_key" in payload.model_fields_set
        try:
            record = service.update_provider(
                provider_id,
                ProviderChanges(
                    name=payload.name,
                    provider_type=payload.provider_type,
                    base_url=payload.base_url,
                    enabled=payload.enabled,
                    extra=payload.extra,
                    api_key_supplied=key_supplied,
                    api_key=(
                        payload.api_key.get_secret_value()
                        if key_supplied and payload.api_key is not None
                        else None
                    ),
                ),
            )
        except AiSettingsNotFoundError as error:
            raise _not_found(error) from None
        except AiSettingsConflictError as error:
            raise _conflict(error) from None
        return _provider_response(record)

    def _delete_provider(provider_id: int) -> Response:
        try:
            service.delete_provider(provider_id)
        except AiSettingsNotFoundError as error:
            raise _not_found(error) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    async def _test_provider_connection(
        provider_id: int, payload: ConnectionTestRequest
    ) -> ConnectionTestResponse:
        try:
            result: ConnectionTestResult = await connection_tests.test(
                registry=get_registry(),
                provider_id=provider_id,
                model_id=payload.model_id,
            )
        except AiSettingsNotFoundError as error:
            raise _not_found(error) from None
        except AiSettingsConfigurationError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
        return ConnectionTestResponse.model_validate(result)

    def _list_models(
        provider_id: Annotated[int | None, Query(gt=0)] = None,
    ) -> list[ModelResponse]:
        return [_model_response(item) for item in service.list_models(provider_id)]

    def _create_model(payload: ModelCreate) -> ModelResponse:
        try:
            record = service.create_model(
                provider_id=payload.provider_id,
                display_name=payload.display_name,
                remote_model=payload.remote_model,
                capabilities=payload.capabilities,
                defaults=payload.defaults,
                enabled=payload.enabled,
            )
        except AiSettingsNotFoundError as error:
            raise _not_found(error) from None
        except AiSettingsConflictError as error:
            raise _conflict(error) from None
        return _model_response(record)

    def _get_model(model_id: int) -> ModelResponse:
        try:
            return _model_response(service.get_model(model_id))
        except AiSettingsNotFoundError as error:
            raise _not_found(error) from None

    def _update_model(model_id: int, payload: ModelUpdate) -> ModelResponse:
        try:
            record = service.update_model(
                model_id,
                ModelChanges(
                    provider_id=payload.provider_id,
                    display_name=payload.display_name,
                    remote_model=payload.remote_model,
                    capabilities=payload.capabilities,
                    defaults=payload.defaults,
                    enabled=payload.enabled,
                ),
            )
        except AiSettingsNotFoundError as error:
            raise _not_found(error) from None
        except AiSettingsConflictError as error:
            raise _conflict(error) from None
        return _model_response(record)

    def _delete_model(model_id: int) -> Response:
        try:
            service.delete_model(model_id)
        except AiSettingsNotFoundError as error:
            raise _not_found(error) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    router.add_api_route(
        "/providers", _list_providers, methods=["GET"], response_model=list[ProviderResponse]
    )
    router.add_api_route(
        "/providers",
        _create_provider,
        methods=["POST"],
        response_model=ProviderResponse,
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route(
        "/providers/{provider_id}",
        _get_provider,
        methods=["GET"],
        response_model=ProviderResponse,
    )
    router.add_api_route(
        "/providers/{provider_id}",
        _update_provider,
        methods=["PATCH"],
        response_model=ProviderResponse,
    )
    router.add_api_route(
        "/providers/{provider_id}",
        _delete_provider,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
    )
    router.add_api_route(
        "/providers/{provider_id}/test-connection",
        _test_provider_connection,
        methods=["POST"],
        response_model=ConnectionTestResponse,
    )
    router.add_api_route(
        "/models", _list_models, methods=["GET"], response_model=list[ModelResponse]
    )
    router.add_api_route(
        "/models",
        _create_model,
        methods=["POST"],
        response_model=ModelResponse,
        status_code=status.HTTP_201_CREATED,
    )
    router.add_api_route(
        "/models/{model_id}", _get_model, methods=["GET"], response_model=ModelResponse
    )
    router.add_api_route(
        "/models/{model_id}", _update_model, methods=["PATCH"], response_model=ModelResponse
    )
    router.add_api_route(
        "/models/{model_id}",
        _delete_model,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
    )
    return router
