"""全局角色库 HTTP API。"""

import json
from datetime import datetime
from typing import Annotated, TypeGuard

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.attribute import AttributeDefinition, AttributeDefinitionError, AttributeScalar
from app.character.service import (
    RoleChanges,
    RoleConflictError,
    RoleDraft,
    RoleNotFoundError,
    RoleRecord,
    RoleReferencedError,
    RoleService,
)
from app.resources.catalog import AssetNotFoundError, InvalidResourceNameError


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _empty_attributes() -> list[AttributeDefinition]:
    return []


def _parse_json_attributes(value: object) -> object:
    """JSON 数组经严格模型解析后转为不可变容器，不放宽 Python 调用边界。"""

    if value is None or not _is_object_list(value):
        return value
    parsed: list[object] = []
    for item in value:
        if isinstance(item, AttributeDefinition):
            parsed.append(item)
        else:
            parsed.append(
                AttributeDefinition.model_validate_json(json.dumps(item, ensure_ascii=False))
            )
    return parsed


class RoleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(min_length=1, max_length=120)]
    persona: Annotated[str, Field(min_length=1, max_length=8000)]
    system_prompt: Annotated[str, Field(max_length=8000)] = ""
    world_book: Annotated[str, Field(max_length=16000)] = ""
    attributes: list[AttributeDefinition] = Field(default_factory=_empty_attributes)

    @field_validator("attributes", mode="before")
    @classmethod
    def parse_json_attributes(cls, value: object) -> object:
        return _parse_json_attributes(value)


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: Annotated[str | None, Field(min_length=1, max_length=8000)] = None
    system_prompt: Annotated[str | None, Field(max_length=8000)] = None
    world_book: Annotated[str | None, Field(max_length=16000)] = None
    attributes: list[AttributeDefinition] | None = None

    @field_validator("attributes", mode="before")
    @classmethod
    def parse_json_attributes(cls, value: object) -> object:
        return _parse_json_attributes(value)


class RoleResponse(BaseModel):
    id: int
    name: str
    persona: str
    system_prompt: str
    world_book: str
    attributes: list[AttributeDefinition]
    effective_base_values: dict[str, AttributeScalar]
    portrait_url: str
    referenced_world_ids: list[int]
    version: int
    created_at: datetime
    updated_at: datetime


def _response(record: RoleRecord) -> RoleResponse:
    return RoleResponse(
        id=record.id,
        name=record.name,
        persona=record.persona,
        system_prompt=record.system_prompt,
        world_book=record.world_book,
        attributes=list(record.attributes),
        effective_base_values={item.key: item.base_value for item in record.attributes},
        portrait_url=record.portrait_url,
        referenced_world_ids=list(record.referenced_world_ids),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def create_role_router(service: RoleService) -> APIRouter:
    """路由只解析 DTO、调用角色 Service 并转换业务错误。"""

    router = APIRouter(prefix="/api")

    def list_roles() -> list[RoleResponse]:
        return [_response(record) for record in service.list_roles()]

    def create_role(payload: RoleCreate) -> RoleResponse:
        try:
            return _response(
                service.create_role(
                    RoleDraft(
                        name=payload.name,
                        persona=payload.persona,
                        system_prompt=payload.system_prompt,
                        world_book=payload.world_book,
                        attributes=tuple(payload.attributes),
                    )
                )
            )
        except AssetNotFoundError, InvalidResourceNameError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="角色缺少有效的同名默认立绘",
            ) from None
        except AttributeDefinitionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from None
        except RoleConflictError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None

    def get_role(role_id: int) -> RoleResponse:
        try:
            return _response(service.get_role(role_id))
        except RoleNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None

    def update_role(role_id: int, payload: RoleUpdate) -> RoleResponse:
        try:
            return _response(
                service.update_role(
                    role_id,
                    RoleChanges(
                        persona=payload.persona,
                        system_prompt=payload.system_prompt,
                        world_book=payload.world_book,
                        attributes=(
                            tuple(payload.attributes) if payload.attributes is not None else None
                        ),
                    ),
                )
            )
        except RoleNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
        except AttributeDefinitionError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from None
        except RoleConflictError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None

    def delete_role(role_id: int) -> Response:
        try:
            service.delete_role(role_id)
        except RoleNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
        except RoleReferencedError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"message": str(error), "world_ids": list(error.world_ids)},
            ) from None
        except RoleConflictError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    router.add_api_route("/roles", list_roles, methods=["GET"], response_model=list[RoleResponse])
    router.add_api_route(
        "/roles", create_role, methods=["POST"], response_model=RoleResponse, status_code=201
    )
    router.add_api_route("/roles/{role_id}", get_role, methods=["GET"], response_model=RoleResponse)
    router.add_api_route(
        "/roles/{role_id}", update_role, methods=["PATCH"], response_model=RoleResponse
    )
    router.add_api_route("/roles/{role_id}", delete_role, methods=["DELETE"], status_code=204)
    return router
