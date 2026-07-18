"""轮次 HTTP DTO、错误映射与成功历史投影测试。"""

from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.turns import create_turn_router
from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.main import create_app
from app.story.service import (
    StateChangeHistoryRecord,
    TurnEventHistoryRecord,
    TurnHistoryRecord,
    TurnRoleHistoryRecord,
)
from app.workflow.context import LocationSimulationContext, TurnContextSnapshot
from app.workflow.manager import (
    ActiveTurnRunError,
    FrozenRunInvoker,
    RunInvoker,
    TurnRunSubscription,
)
from app.workflow.runtime import RunStatus, TurnRun, TurnRunSummary
from app.world.service import WorldNotFoundError


class FakeWorldService:
    def __init__(self) -> None:
        self.error: Exception | None = None

    def get_world(self, world_id: int) -> object:
        del world_id
        if self.error is not None:
            raise self.error
        return object()


class FakeContextBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def build_current_turn_snapshot(
        self,
        *,
        world_id: int,
        player_intent: str,
    ) -> tuple[LocationSimulationContext, ...]:
        self.calls.append((world_id, player_intent))
        return ()


class FakeManager:
    def __init__(self) -> None:
        self.run = TurnRun.create(())
        self.create_error: Exception | None = None
        self.cancel_calls = 0

    async def create(
        self,
        source: Sequence[LocationSimulationContext] | TurnContextSnapshot,
        invoker: RunInvoker,
    ) -> TurnRun:
        del source, invoker
        if self.create_error is not None:
            raise self.create_error
        return self.run

    async def get(self, run_id: str) -> TurnRunSummary:
        if run_id != self.run.run_id:
            raise KeyError("轮次不存在或已过期")
        return self.run.summary()

    async def cancel(self, run_id: str) -> TurnRunSummary:
        if run_id != self.run.run_id:
            raise KeyError("轮次不存在或已过期")
        self.cancel_calls += 1
        self.run.cancel()
        return self.run.summary()

    async def claim(self, run_id: str) -> TurnRunSubscription:
        del run_id
        raise RuntimeError("API 单元测试不建立流订阅")

    async def wait(self, run_id: str) -> TurnRunSummary:
        return await self.get(run_id)


class FakeHistoryService:
    def __init__(self) -> None:
        self.history: tuple[TurnHistoryRecord, ...] = ()

    def list_history(self, *, world_id: int) -> tuple[TurnHistoryRecord, ...]:
        assert world_id == 7
        return self.history

    def get_turn(self, turn_id: int) -> TurnHistoryRecord:
        for item in self.history:
            if item.turn_id == turn_id:
                return item
        raise RuntimeError("API 单元测试的成功轮次不存在")


class FakeInvoker:
    def freeze_for_run(self) -> FrozenRunInvoker:
        raise RuntimeError("FakeManager 不会冻结调用器")


def _app(
    world_service: FakeWorldService,
    context_builder: FakeContextBuilder,
    manager: FakeManager,
    history_service: FakeHistoryService,
) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_turn_router(
            world_service,
            context_builder,
            history_service,
            manager,
            lambda: FakeInvoker(),
        )
    )
    return app


async def test_create_returns_202_pending_and_preserves_the_original_intent() -> None:
    world_service = FakeWorldService()
    context_builder = FakeContextBuilder()
    manager = FakeManager()
    app = _app(world_service, context_builder, manager, FakeHistoryService())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/worlds/7/turn-runs",
            json={"player_intent": "  去找莫莉莉  "},
        )

    assert response.status_code == 202
    assert response.json() == {"run_id": manager.run.run_id, "status": "pending"}
    assert context_builder.calls == [(7, "  去找莫莉莉  ")]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"player_intent": ""},
        {"player_intent": "   \t"},
        {"player_intent": "向前走", "unexpected": True},
    ],
)
async def test_create_rejects_missing_empty_or_extra_input(payload: dict[str, object]) -> None:
    app = _app(FakeWorldService(), FakeContextBuilder(), FakeManager(), FakeHistoryService())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/worlds/7/turn-runs", json=payload)

    assert response.status_code == 422


async def test_create_maps_unknown_world_and_active_run_to_safe_http_errors() -> None:
    world_service = FakeWorldService()
    manager = FakeManager()
    app = _app(world_service, FakeContextBuilder(), manager, FakeHistoryService())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        world_service.error = WorldNotFoundError("世界不存在")
        missing = await client.post("/api/worlds/7/turn-runs", json={"player_intent": "向前走"})
        world_service.error = None
        manager.create_error = ActiveTurnRunError("已有活动轮次")
        conflict = await client.post("/api/worlds/7/turn-runs", json={"player_intent": "向前走"})

    assert missing.status_code == 404
    assert missing.json() == {"detail": "世界不存在"}
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "已有活动轮次"}


async def test_status_and_cancel_are_process_local_and_cancel_is_idempotent() -> None:
    manager = FakeManager()
    app = _app(FakeWorldService(), FakeContextBuilder(), manager, FakeHistoryService())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        status_response = await client.get(f"/api/turn-runs/{manager.run.run_id}")
        first_cancel = await client.post(f"/api/turn-runs/{manager.run.run_id}/cancel")
        second_cancel = await client.post(f"/api/turn-runs/{manager.run.run_id}/cancel")
        missing = await client.get("/api/turn-runs/restarted-process-id")

    assert status_response.json()["status"] == RunStatus.PENDING
    assert first_cancel.json()["status"] == RunStatus.CANCELLED
    assert second_cancel.json() == first_cancel.json()
    assert manager.cancel_calls == 2
    assert missing.status_code == 404


async def test_history_returns_the_complete_successful_turn_projection() -> None:
    history_service = FakeHistoryService()
    history_service.history = (
        TurnHistoryRecord(
            turn_id=9,
            day=2,
            time_slot="night",
            player_intent="休息",
            roles=(TurnRoleHistoryRecord(role_id=1, content="天回到房间。", offline=False),),
            events=(
                TurnEventHistoryRecord(
                    event_id=11,
                    location_id="the_home",
                    event_type="rest",
                    fact={"summary": "天休息了"},
                ),
            ),
            state_changes=(
                StateChangeHistoryRecord(
                    role_id=1,
                    attribute_key="energy",
                    operation="increment",
                    old_value=30,
                    operand=10,
                    new_value=40,
                    reason="完成休息",
                ),
            ),
        ),
    )
    app = _app(FakeWorldService(), FakeContextBuilder(), FakeManager(), history_service)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/worlds/7/turns")

    assert response.status_code == 200
    assert response.json() == [
        {
            "turn_id": 9,
            "day": 2,
            "time_slot": "night",
            "player_intent": "休息",
            "roles": [{"role_id": 1, "content": "天回到房间。", "offline": False}],
            "events": [
                {
                    "event_id": 11,
                    "location_id": "the_home",
                    "event_type": "rest",
                    "fact": {"summary": "天休息了"},
                }
            ],
            "state_changes": [
                {
                    "role_id": 1,
                    "attribute_key": "energy",
                    "operation": "increment",
                    "old_value": 30,
                    "operand": 10,
                    "new_value": 40,
                    "reason": "完成休息",
                }
            ],
        }
    ]


async def test_application_registers_turn_routes_with_lifespan_dependencies(
    tmp_path: Path,
) -> None:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[2] / "alembic.ini")
    app = create_app(config)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        create_response = await client.post(
            "/api/worlds/999/turn-runs",
            json={"player_intent": "向前走"},
        )
        history_response = await client.get("/api/worlds/999/turns")

    assert create_response.status_code == 404
    assert create_response.json() == {"detail": "世界不存在"}
    assert history_response.status_code == 404
    assert history_response.json() == {"detail": "世界不存在"}

    stream_content = app.openapi()["paths"]["/api/turn-runs/{run_id}/stream"]["get"]["responses"][
        "200"
    ]["content"]
    assert stream_content == {
        "application/x-ndjson": {
            # HTTP body 是逐块字符串，额外 ref 固定每一行解析后的事件 DTO。
            "schema": {
                "type": "string",
                "$ref": "#/components/schemas/TurnRunEventResponse",
            }
        }
    }
    event_kind_schema = app.openapi()["components"]["schemas"]["TurnRunEventResponse"][
        "properties"
    ]["kind"]
    assert event_kind_schema == {"$ref": "#/components/schemas/TurnEventKind"}
    assert app.openapi()["components"]["schemas"]["TurnEventKind"]["enum"] == [
        "node_started",
        "node_retrying",
        "node_succeeded",
        "map_completed",
        "node_failed",
        "run_succeeded",
        "run_failed",
        "run_cancelled",
    ]


def _task_payload(model_id: int, *, memory: bool) -> dict[str, object]:
    return {
        "model_id": model_id,
        "temperature": 0.7,
        "max_output_tokens": 512,
        "reasoning_effort": "high",
        "timeout_seconds": 90,
        "extra_prompt": "",
        "structured_output_mode": "auto",
        "provider_options": {},
        "memory_target_chars": 20 if memory else None,
        "memory_max_chars": 50 if memory else None,
    }


async def test_real_app_create_status_cancel_and_restart_lifecycle(tmp_path: Path) -> None:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[2] / "alembic.ini")
    role_dir = config.paths.characters_dir / "天"
    role_dir.mkdir(parents=True)
    (role_dir / "天.jpg").write_bytes(b"\xff\xd8\xff\xe0")
    app = create_app(config)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        role = await client.post(
            "/api/roles",
            json={
                "name": "天",
                "persona": "天空城居民",
                "system_prompt": "保持自主性",
                "world_book": "天空城",
                "attributes": [],
            },
        )
        world = await client.post(
            "/api/worlds",
            json={"protagonist_role_id": role.json()["id"]},
        )
        world_id = world.json()["id"]
        unconfigured = await client.post(
            f"/api/worlds/{world_id}/turn-runs",
            json={"player_intent": "去学校"},
        )
        provider = await client.post(
            "/api/providers",
            json={
                "name": "Primary",
                "provider_type": "openai_compatible",
                "base_url": "https://example.test/v1",
                "api_key": "test-only-key",
            },
        )
        model = await client.post(
            "/api/models",
            json={
                "provider_id": provider.json()["id"],
                "display_name": "Model A",
                "remote_model": "model-a",
                "capabilities": {"json_output": True, "reasoning": True},
                "enabled": True,
            },
        )
        model_id = model.json()["id"]
        for task_key, memory in (
            ("location_simulation", False),
            ("attribute_memory_analysis", True),
        ):
            configured = await client.put(
                f"/api/ai-task-settings/{task_key}",
                json=_task_payload(model_id, memory=memory),
            )
            assert configured.status_code == 200, configured.text
        created = await client.post(
            f"/api/worlds/{world_id}/turn-runs",
            json={"player_intent": "去学校"},
        )
        run_id = created.json()["run_id"]
        status_response = await client.get(f"/api/turn-runs/{run_id}")
        duplicate = await client.post(
            f"/api/worlds/{world_id}/turn-runs",
            json={"player_intent": "重复提交"},
        )
        first_cancel = await client.post(f"/api/turn-runs/{run_id}/cancel")
        second_cancel = await client.post(f"/api/turn-runs/{run_id}/cancel")

    assert unconfigured.status_code == 409
    assert unconfigured.json() == {"detail": "AI 任务尚未选择模型"}
    assert created.status_code == 202
    assert status_response.json()["status"] == "pending"
    assert duplicate.status_code == 409
    assert first_cancel.json()["status"] == "cancelled"
    assert second_cancel.json() == first_cancel.json()

    restarted_app = create_app(config)
    async with (
        restarted_app.router.lifespan_context(restarted_app),
        AsyncClient(
            transport=ASGITransport(app=restarted_app), base_url="http://testserver"
        ) as restarted_client,
    ):
        restarted_status = await restarted_client.get(f"/api/turn-runs/{run_id}")

    assert restarted_status.status_code == 404
