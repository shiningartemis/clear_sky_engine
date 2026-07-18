"""轮次创建、进程内状态、NDJSON 订阅、取消与成功历史 API。"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import suppress
from typing import Literal, Protocol, TypeGuard

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.types import Receive, Scope, Send

from app.ai.service import AiSettingsConfigurationError, AiSettingsNotFoundError
from app.ai.types import JsonValue
from app.story.service import SettlementConflictError, TurnHistoryRecord
from app.story.store import StoryDataError
from app.workflow.context import (
    ContextBuildError,
    LocationSimulationContext,
    TurnContextSnapshot,
)
from app.workflow.manager import (
    ActiveTurnRunError,
    RunInvoker,
    TurnRunAlreadyClaimedError,
    TurnRunSubscription,
)
from app.workflow.runtime import NodeKey, ProgressEvent, RunStatus, TurnRun, TurnRunSummary
from app.workflow.settings import TaskSettingConfigurationError, TaskSettingNotFoundError
from app.world.service import WorldConflictError, WorldNotFoundError


class TurnRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_intent: str = Field(min_length=1)

    @field_validator("player_intent")
    @classmethod
    def reject_blank_intent(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("玩家意图不能为空")
        # 只用 strip 判断空白，不改写玩家原文。
        return value


class TurnRunCreated(BaseModel):
    run_id: str
    status: Literal[RunStatus.PENDING]


class TurnRunStatusResponse(BaseModel):
    run_id: str
    status: RunStatus
    turn_id: int | None = None
    error: str | None = None


class TurnRoleResponse(BaseModel):
    role_id: int
    content: str
    offline: bool


class TurnEventResponse(BaseModel):
    event_id: int
    location_id: str
    event_type: str
    fact: dict[str, JsonValue]


class StateChangeResponse(BaseModel):
    role_id: int
    attribute_key: str
    operation: str
    old_value: JsonValue
    operand: JsonValue
    new_value: JsonValue
    reason: str


class TurnResponse(BaseModel):
    turn_id: int
    day: int
    time_slot: str
    player_intent: str
    roles: list[TurnRoleResponse]
    events: list[TurnEventResponse]
    state_changes: list[StateChangeResponse]


type TurnEventKind = Literal[
    "node_started",
    "node_retrying",
    "node_succeeded",
    "map_completed",
    "node_failed",
    "run_succeeded",
    "run_failed",
    "run_cancelled",
]

TURN_EVENT_KINDS: tuple[TurnEventKind, ...] = (
    "node_started",
    "node_retrying",
    "node_succeeded",
    "map_completed",
    "node_failed",
    "run_succeeded",
    "run_failed",
    "run_cancelled",
)


class TurnRunEventResponse(BaseModel):
    run_id: str
    kind: TurnEventKind
    location_id: str | None
    node: NodeKey | None
    attempt: int | None
    max_attempts: int
    retrying: bool
    completed_maps: int
    total_maps: int
    elapsed_ms: int
    error: str | None = None
    turn: TurnResponse | None = None


class NdjsonStreamingResponse(StreamingResponse):
    """让 OpenAPI 与真实流共享唯一媒体类型及事件 Schema。"""

    media_type = "application/x-ndjson"

    def __init__(
        self,
        content: AsyncIterator[bytes],
        *,
        cleanup: Callable[[], Awaitable[object]],
        status_code: int = status.HTTP_200_OK,
    ) -> None:
        # FastAPI 会检查 response class 的 status_code 默认值来生成 OpenAPI。
        super().__init__(content, status_code=status_code)
        self._cleanup = cleanup

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """即使传输在首次 body 迭代前失败，也必须等待运行清理。"""

        try:
            await super().__call__(scope, receive, send)
        finally:
            cleanup_task = asyncio.ensure_future(self._cleanup())
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                with suppress(KeyError):
                    await cleanup_task
                raise
            except KeyError:
                # 仅当新的运行已淘汰旧安全摘要时发生；旧运行此时已经清理。
                pass


class TurnContextSource(Protocol):
    def build_current_turn_snapshot(
        self,
        *,
        world_id: int,
        player_intent: str,
    ) -> Sequence[LocationSimulationContext] | TurnContextSnapshot: ...


class WorldReader(Protocol):
    def get_world(self, world_id: int) -> object: ...


class TurnHistorySource(Protocol):
    def list_history(self, *, world_id: int) -> tuple[TurnHistoryRecord, ...]: ...

    def get_turn(self, turn_id: int) -> TurnHistoryRecord: ...


class TurnRunControl(Protocol):
    async def create(
        self,
        source: Sequence[LocationSimulationContext] | TurnContextSnapshot,
        invoker: RunInvoker,
    ) -> TurnRun: ...

    async def get(self, run_id: str) -> TurnRunSummary: ...

    async def claim(self, run_id: str) -> TurnRunSubscription: ...

    async def cancel(self, run_id: str) -> TurnRunSummary: ...

    async def wait(self, run_id: str) -> TurnRunSummary: ...


type RunInvokerProvider = Callable[[], RunInvoker]


def _status_response(summary: TurnRunSummary) -> TurnRunStatusResponse:
    return TurnRunStatusResponse(
        run_id=summary.run_id,
        status=summary.status,
        turn_id=summary.turn_id,
        error=summary.error,
    )


def _turn_response(record: TurnHistoryRecord) -> TurnResponse:
    return TurnResponse(
        turn_id=record.turn_id,
        day=record.day,
        time_slot=record.time_slot,
        player_intent=record.player_intent,
        roles=[
            TurnRoleResponse(role_id=item.role_id, content=item.content, offline=item.offline)
            for item in record.roles
        ],
        events=[
            TurnEventResponse(
                event_id=item.event_id,
                location_id=item.location_id,
                event_type=item.event_type,
                fact=item.fact,
            )
            for item in record.events
        ],
        state_changes=[
            StateChangeResponse(
                role_id=item.role_id,
                attribute_key=item.attribute_key,
                operation=item.operation,
                old_value=item.old_value,
                operand=item.operand,
                new_value=item.new_value,
                reason=item.reason,
            )
            for item in record.state_changes
        ],
    )


def _is_turn_event_kind(value: str) -> TypeGuard[TurnEventKind]:
    return value in TURN_EVENT_KINDS


def _event_response(event: ProgressEvent, turn: TurnResponse | None = None) -> TurnRunEventResponse:
    if not _is_turn_event_kind(event.kind):
        # 运行时与公开协议必须同步；未知事件不能静默泄漏给客户端。
        raise RuntimeError(f"未知轮次进度事件类型: {event.kind}")
    return TurnRunEventResponse(
        run_id=event.run_id,
        kind=event.kind,
        location_id=event.location_id,
        node=event.node,
        attempt=event.attempt,
        max_attempts=event.max_attempts,
        retrying=event.retrying,
        completed_maps=event.completed_maps,
        total_maps=event.total_maps,
        elapsed_ms=event.elapsed_ms,
        error=event.error,
        turn=turn,
    )


async def stream_turn_run_events(
    manager: TurnRunControl,
    history: TurnHistorySource,
    subscription: TurnRunSubscription,
) -> AsyncGenerator[bytes]:
    """流连接拥有运行生命周期；非自然终态退出必须等待取消清理。"""

    terminal_seen = False
    try:
        while True:
            event = await subscription.receive()
            turn: TurnResponse | None = None
            if event.kind == "run_succeeded":
                summary = await manager.wait(subscription.run_id)
                if summary.turn_id is None:
                    raise RuntimeError("成功轮次缺少持久化 ID")
                turn = _turn_response(history.get_turn(summary.turn_id))
            response = _event_response(event, turn)
            yield (response.model_dump_json(exclude_none=True) + "\n").encode()
            if event.kind in {"run_succeeded", "run_failed", "run_cancelled"}:
                terminal_seen = True
                return
    finally:
        if not terminal_seen:
            # 被取消的 ASGI scope 仍要等 Manager 丢弃输出并释放活动槽。
            cleanup = asyncio.create_task(manager.cancel(subscription.run_id))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise


def create_turn_router(
    world_service: WorldReader,
    context_builder: TurnContextSource,
    history_service: TurnHistorySource,
    manager: TurnRunControl,
    get_invoker: RunInvokerProvider,
) -> APIRouter:
    """路由只投影受控 DTO；快照、运行生命周期和历史事实由下层拥有。"""

    router = APIRouter(prefix="/api")

    async def create_run(world_id: int, payload: TurnRunCreate) -> TurnRunCreated:
        try:
            world_service.get_world(world_id)
            snapshot = context_builder.build_current_turn_snapshot(
                world_id=world_id,
                player_intent=payload.player_intent,
            )
            run = await manager.create(snapshot, get_invoker())
        except WorldNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
        except (
            ActiveTurnRunError,
            AiSettingsConfigurationError,
            AiSettingsNotFoundError,
            ContextBuildError,
            TaskSettingConfigurationError,
            TaskSettingNotFoundError,
            WorldConflictError,
        ) as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
        return TurnRunCreated(run_id=run.run_id, status=RunStatus.PENDING)

    async def get_run(run_id: str) -> TurnRunStatusResponse:
        try:
            return _status_response(await manager.get(run_id))
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="轮次不存在或已过期",
            ) from None

    async def cancel_run(run_id: str) -> TurnRunStatusResponse:
        try:
            return _status_response(await manager.cancel(run_id))
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="轮次不存在或已过期",
            ) from None

    async def stream_run(run_id: str) -> NdjsonStreamingResponse:
        try:
            subscription = await manager.claim(run_id)
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="轮次不存在或已过期",
            ) from None
        except TurnRunAlreadyClaimedError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None
        return NdjsonStreamingResponse(
            stream_turn_run_events(manager, history_service, subscription),
            cleanup=lambda: manager.cancel(run_id),
        )

    def list_turns(world_id: int) -> list[TurnResponse]:
        try:
            world_service.get_world(world_id)
            return [
                _turn_response(item) for item in history_service.list_history(world_id=world_id)
            ]
        except WorldNotFoundError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from None
        except (SettlementConflictError, StoryDataError, WorldConflictError) as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from None

    router.add_api_route(
        "/worlds/{world_id}/turn-runs",
        create_run,
        methods=["POST"],
        response_model=TurnRunCreated,
        status_code=status.HTTP_202_ACCEPTED,
    )
    router.add_api_route(
        "/turn-runs/{run_id}",
        get_run,
        methods=["GET"],
        response_model=TurnRunStatusResponse,
    )
    router.add_api_route(
        "/turn-runs/{run_id}/stream",
        stream_run,
        methods=["GET"],
        response_model=None,
        response_class=NdjsonStreamingResponse,
        responses={
            status.HTTP_200_OK: {
                "model": TurnRunEventResponse,
                "description": "完整 NDJSON 轮次进度事件流",
            }
        },
    )
    router.add_api_route(
        "/turn-runs/{run_id}/cancel",
        cancel_run,
        methods=["POST"],
        response_model=TurnRunStatusResponse,
    )
    router.add_api_route(
        "/worlds/{world_id}/turns",
        list_turns,
        methods=["GET"],
        response_model=list[TurnResponse],
    )
    return router
