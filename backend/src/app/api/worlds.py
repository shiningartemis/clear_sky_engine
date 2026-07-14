"""世界、世界角色、位置规则和游戏视图 HTTP API。"""

from datetime import datetime
from typing import Annotated, Literal, TypeGuard

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.roles import RoleResponse
from app.attribute import AttributeScalar
from app.resources.catalog import AssetNotFoundError, InvalidResourceNameError
from app.world.service import (
    GameViewRecord,
    InvalidLocationError,
    LocationCandidateDraft,
    LocationRuleDraft,
    LocationRuleRecord,
    ProtagonistDraft,
    WorldConflictError,
    WorldNotFoundError,
    WorldRecord,
    WorldRoleRecord,
    WorldService,
)

LocationId = Literal[
    "the_home",
    "the_dungeon",
    "the_mall",
    "the_guild",
    "the_hotel",
    "the_school",
]


class WorldCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protagonist_name: Annotated[str, Field(min_length=1, max_length=120)]
    protagonist_persona: Annotated[str, Field(min_length=1, max_length=8000)]


class WorldRoleAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: int = Field(gt=0)


class WorldRoleEnabledUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class LocationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: LocationId


class LocationCandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location_id: LocationId
    weight: int = Field(gt=0)


class LocationRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday_mask: int = Field(ge=1, le=127)
    time_slot: Literal["morning", "midday", "evening", "night"]
    mode: Literal["fixed", "random"]
    priority: int
    enabled: bool = True
    candidates: list[LocationCandidateCreate] = Field(min_length=1)


class LocationRuleResponse(LocationRuleCreate):
    id: int
    world_id: int
    role_id: int


class MapLocationResponse(BaseModel):
    scene_id: LocationId
    display_name: str
    order: int
    anchor_x: float = Field(ge=0, le=1)
    anchor_y: float = Field(ge=0, le=1)


class EffectiveAttributesResponse(BaseModel):
    world_id: int
    role_id: int
    values: dict[str, AttributeScalar]
    updated_at: datetime


class WorldRoleResponse(BaseModel):
    world_id: int
    role_id: int
    name: str
    kind: Literal["player", "npc"]
    enabled: bool
    effective_attributes: dict[str, AttributeScalar]
    portrait_url: str
    version: int
    updated_at: datetime


class WorldResponse(BaseModel):
    id: int
    display_name: str
    active_branch_id: int
    day: int
    weekday: str
    time_slot: str
    player_role: RoleResponse
    npc_count: int
    last_played_at: datetime


class GameViewResponse(BaseModel):
    world_id: int
    scene_id: str
    day: int
    weekday: str
    time_slot: str
    background_url: str
    fallback_background_url: str
    player_marker_url: str
    player_location_id: str
    locations: list[MapLocationResponse]
    visible_roles: list[WorldRoleResponse]


def _world_response(record: WorldRecord) -> WorldResponse:
    return WorldResponse(
        id=record.id,
        display_name=record.display_name,
        active_branch_id=record.active_branch_id,
        day=record.day,
        weekday=record.weekday,
        time_slot=record.time_slot,
        player_role=RoleResponse(
            id=record.player_role.id,
            name=record.player_role.name,
            persona=record.player_role.persona,
            system_prompt=record.player_role.system_prompt,
            world_book=record.player_role.world_book,
            attributes=list(record.player_role.attributes),
            effective_base_values={
                item.key: item.base_value for item in record.player_role.attributes
            },
            portrait_url=record.player_role.portrait_url,
            referenced_world_ids=list(record.player_role.referenced_world_ids),
            version=record.player_role.version,
            created_at=record.player_role.created_at,
            updated_at=record.player_role.updated_at,
        ),
        npc_count=record.npc_count,
        last_played_at=record.last_played_at,
    )


def _world_role_response(record: WorldRoleRecord) -> WorldRoleResponse:
    return WorldRoleResponse(
        world_id=record.world_id,
        role_id=record.role_id,
        name=record.name,
        kind=record.kind,
        enabled=record.enabled,
        effective_attributes=record.effective_attributes,
        portrait_url=record.portrait_url,
        version=record.version,
        updated_at=record.updated_at,
    )


def _location_rule_response(record: LocationRuleRecord) -> LocationRuleResponse:
    if not _is_time_slot(record.time_slot):
        raise RuntimeError("持久化位置规则时间段无效")
    return LocationRuleResponse(
        id=record.id,
        world_id=record.world_id,
        role_id=record.role_id,
        weekday_mask=record.weekday_mask,
        time_slot=record.time_slot,
        mode=record.mode,
        priority=record.priority,
        enabled=record.enabled,
        candidates=[
            LocationCandidateCreate(
                location_id=_required_location_id(item.location_id), weight=item.weight
            )
            for item in record.candidates
        ],
    )


def _game_view_response(record: GameViewRecord) -> GameViewResponse:
    return GameViewResponse(
        world_id=record.world_id,
        scene_id=record.scene_id,
        day=record.day,
        weekday=record.weekday,
        time_slot=record.time_slot,
        background_url=record.background_url,
        fallback_background_url=record.fallback_background_url,
        player_marker_url=record.player_marker_url,
        player_location_id=record.player_location_id,
        locations=[
            MapLocationResponse(
                scene_id=_required_location_id(item.scene_id),
                display_name=item.display_name,
                order=item.order,
                anchor_x=item.anchor_x,
                anchor_y=item.anchor_y,
            )
            for item in record.locations
        ],
        visible_roles=[_world_role_response(item) for item in record.visible_roles],
    )


def _is_time_slot(value: str) -> TypeGuard[Literal["morning", "midday", "evening", "night"]]:
    return value in {"morning", "midday", "evening", "night"}


def _is_location_id(value: str) -> TypeGuard[LocationId]:
    return value in {
        "the_home",
        "the_dungeon",
        "the_mall",
        "the_guild",
        "the_hotel",
        "the_school",
    }


def _required_location_id(value: str) -> LocationId:
    if not _is_location_id(value):
        raise RuntimeError("持久化地图地点无效")
    return value


def _not_found(error: WorldNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def _conflict(error: WorldConflictError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))


def _invalid_location(error: InvalidLocationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


def create_world_router(service: WorldService) -> APIRouter:
    """路由只负责严格 DTO、Service 调用和业务错误到 HTTP 的转换。"""

    router = APIRouter(prefix="/api")

    def list_worlds() -> list[WorldResponse]:
        return [_world_response(item) for item in service.list_worlds()]

    def create_world(payload: WorldCreate) -> WorldResponse:
        try:
            return _world_response(
                service.create_world(
                    ProtagonistDraft(
                        name=payload.protagonist_name,
                        persona=payload.protagonist_persona,
                    )
                )
            )
        except AssetNotFoundError, InvalidResourceNameError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="主角缺少有效的同名默认立绘",
            ) from None
        except WorldConflictError as error:
            raise _conflict(error) from None

    def delete_world(world_id: int) -> Response:
        try:
            service.delete_world(world_id)
        except WorldNotFoundError as error:
            raise _not_found(error) from None
        except WorldConflictError as error:
            raise _conflict(error) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def list_world_roles(world_id: int) -> list[WorldRoleResponse]:
        try:
            return [_world_role_response(item) for item in service.list_world_roles(world_id)]
        except WorldNotFoundError as error:
            raise _not_found(error) from None

    def add_world_role(world_id: int, payload: WorldRoleAdd) -> WorldRoleResponse:
        try:
            return _world_role_response(service.add_npc(world_id, payload.role_id))
        except AssetNotFoundError, InvalidResourceNameError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="NPC 缺少有效的同名默认立绘",
            ) from None
        except WorldNotFoundError as error:
            raise _not_found(error) from None
        except WorldConflictError as error:
            raise _conflict(error) from None

    def update_world_role(
        world_id: int,
        role_id: int,
        payload: WorldRoleEnabledUpdate,
    ) -> WorldRoleResponse:
        try:
            return _world_role_response(
                service.update_npc_enabled(world_id, role_id, payload.enabled)
            )
        except WorldNotFoundError as error:
            raise _not_found(error) from None
        except WorldConflictError as error:
            raise _conflict(error) from None

    def remove_world_role(world_id: int, role_id: int) -> Response:
        try:
            service.remove_npc(world_id, role_id)
        except WorldNotFoundError as error:
            raise _not_found(error) from None
        except WorldConflictError as error:
            raise _conflict(error) from None
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def replace_location_rules(
        world_id: int,
        role_id: int,
        payload: list[LocationRuleCreate],
    ) -> list[LocationRuleResponse]:
        try:
            records = service.replace_location_rules(
                world_id,
                role_id,
                tuple(
                    LocationRuleDraft(
                        weekday_mask=item.weekday_mask,
                        time_slot=item.time_slot,
                        mode=item.mode,
                        priority=item.priority,
                        enabled=item.enabled,
                        candidates=tuple(
                            LocationCandidateDraft(
                                location_id=candidate.location_id,
                                weight=candidate.weight,
                            )
                            for candidate in item.candidates
                        ),
                    )
                    for item in payload
                ),
            )
            return [_location_rule_response(item) for item in records]
        except WorldNotFoundError as error:
            raise _not_found(error) from None
        except WorldConflictError as error:
            raise _conflict(error) from None
        except InvalidLocationError as error:
            raise _invalid_location(error) from None

    def read_effective_attributes(world_id: int, role_id: int) -> EffectiveAttributesResponse:
        try:
            record = service.get_world_role(world_id, role_id)
        except WorldNotFoundError as error:
            raise _not_found(error) from None
        return EffectiveAttributesResponse(
            world_id=record.world_id,
            role_id=record.role_id,
            values=record.effective_attributes,
            updated_at=record.updated_at,
        )

    def select_location(world_id: int, payload: LocationSelection) -> GameViewResponse:
        try:
            return _game_view_response(service.select_location(world_id, payload.location_id))
        except WorldNotFoundError as error:
            raise _not_found(error) from None
        except WorldConflictError as error:
            raise _conflict(error) from None
        except InvalidLocationError as error:
            raise _invalid_location(error) from None

    def get_game_view(world_id: int, scene_id: str) -> GameViewResponse:
        try:
            return _game_view_response(service.get_game_view(world_id, scene_id))
        except WorldNotFoundError as error:
            raise _not_found(error) from None
        except WorldConflictError as error:
            raise _conflict(error) from None
        except InvalidLocationError as error:
            raise _invalid_location(error) from None

    router.add_api_route(
        "/worlds", list_worlds, methods=["GET"], response_model=list[WorldResponse]
    )
    router.add_api_route(
        "/worlds", create_world, methods=["POST"], response_model=WorldResponse, status_code=201
    )
    router.add_api_route("/worlds/{world_id}", delete_world, methods=["DELETE"], status_code=204)
    router.add_api_route(
        "/worlds/{world_id}/roles",
        list_world_roles,
        methods=["GET"],
        response_model=list[WorldRoleResponse],
    )
    router.add_api_route(
        "/worlds/{world_id}/roles",
        add_world_role,
        methods=["POST"],
        response_model=WorldRoleResponse,
        status_code=201,
    )
    router.add_api_route(
        "/worlds/{world_id}/roles/{role_id}",
        update_world_role,
        methods=["PATCH"],
        response_model=WorldRoleResponse,
    )
    router.add_api_route(
        "/worlds/{world_id}/roles/{role_id}",
        remove_world_role,
        methods=["DELETE"],
        status_code=204,
    )
    router.add_api_route(
        "/worlds/{world_id}/roles/{role_id}/location-rules",
        replace_location_rules,
        methods=["PUT"],
        response_model=list[LocationRuleResponse],
    )
    router.add_api_route(
        "/worlds/{world_id}/roles/{role_id}/effective-attributes",
        read_effective_attributes,
        methods=["GET"],
        response_model=EffectiveAttributesResponse,
    )
    router.add_api_route(
        "/worlds/{world_id}/location",
        select_location,
        methods=["POST"],
        response_model=GameViewResponse,
    )
    router.add_api_route(
        "/worlds/{world_id}/game-view",
        get_game_view,
        methods=["GET"],
        response_model=GameViewResponse,
    )
    return router
