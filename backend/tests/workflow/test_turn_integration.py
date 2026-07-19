import asyncio
from collections import Counter
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue, SecretStr, TypeAdapter
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.ai.contracts import ProviderConnection, ProviderRegistry
from app.ai.dto import ChatRequest, ChatResponse, ChatStreamEvent, TokenUsage
from app.ai.service import ModelRecord, ProviderConnectionRecord, RunnableTaskSettingsBundle
from app.attribute import AttributeUpdateIntent
from app.character.models import Role
from app.config import AppConfig
from app.db.migrations import upgrade_database
from app.db.session import create_session_factory, create_sqlite_engine
from app.main import create_app
from app.story.models import StateChange, Turn, TurnEvent, TurnEventParticipant, TurnStory
from app.story.service import OFFLINE_STORY_CONTENT, SettlementService
from app.workflow.ai_tasks import TaskInvoker
from app.workflow.context import ContextBuilder
from app.workflow.executor import MapChainExecutor
from app.workflow.manager import TurnRunManager
from app.workflow.retry import RetryPolicy
from app.workflow.runtime import ProgressEvent, RunStatus
from app.workflow.schemas import (
    AttributeMemoryAnalysisOutput,
    EventKnowledge,
    InteractionGroupOutput,
    LocationSimulationOutput,
    ObjectiveEventOutput,
    RoleAttributeMemoryOutput,
    RoleChronicleOutput,
)
from app.workflow.settings import StructuredOutputMode, TaskKey, TaskSettingSnapshot
from app.world.models import (
    CharacterLocationCandidate,
    CharacterLocationRule,
    World,
    WorldBranch,
    WorldRoleMemory,
    WorldRoleState,
)

NOW = datetime(2026, 7, 19, tzinfo=UTC)
ASYNC_TEST_TIMEOUT_SECONDS = 1.0
type JsonObject = dict[str, JsonValue]
JSON_OBJECT_ADAPTER: TypeAdapter[JsonObject] = TypeAdapter(dict[str, JsonValue])
JSON_ARRAY_ADAPTER: TypeAdapter[list[JsonValue]] = TypeAdapter(list[JsonValue])


def parse_json_object(raw: str) -> JsonObject:
    return JSON_OBJECT_ADAPTER.validate_json(raw)


def parse_json_array(raw: str) -> list[JsonValue]:
    return JSON_ARRAY_ADAPTER.validate_json(raw)


def require_json_object(value: JsonValue | None, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise AssertionError(f"{label}必须是 JSON 对象")
    return value


def require_json_array(value: JsonValue | None, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise AssertionError(f"{label}必须是 JSON 数组")
    return value


def require_json_string(value: JsonValue | None, label: str) -> str:
    if not isinstance(value, str):
        raise AssertionError(f"{label}必须是字符串")
    return value


def require_json_int(value: JsonValue | None, label: str) -> int:
    if type(value) is not int:
        raise AssertionError(f"{label}必须是整数")
    return value


def role_objects(context: JsonObject) -> tuple[JsonObject, ...]:
    return tuple(
        require_json_object(item, "角色上下文")
        for item in require_json_array(context.get("roles"), "角色列表")
    )


def _role(role_id: int) -> Role:
    return Role(
        id=role_id,
        name=f"角色{role_id}",
        persona=f"角色{role_id}人设",
        system_prompt=f"角色{role_id}提示词",
        world_book="同一世界书",
        base_values_json={"level": 10},
        attribute_types_json={"level": "integer"},
        attribute_labels_json={"level": "等级"},
        attribute_descriptions_json={"level": "当前等级"},
        attribute_update_rules_json={"level": "明确成长时才更新"},
        attribute_constraints_json={"level": {"minimum": 0, "maximum": 99}},
        attribute_allowed_operations_json={"level": ["increment", "replace"]},
        attribute_examples_json={},
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _task_snapshot(task_key: TaskKey) -> TaskSettingSnapshot:
    memory = task_key is TaskKey.ATTRIBUTE_MEMORY_ANALYSIS
    return TaskSettingSnapshot(
        task_key=task_key,
        model_id=1,
        temperature=0,
        max_output_tokens=512,
        reasoning_effort=None,
        timeout_seconds=10,
        extra_prompt="",
        structured_output_mode=StructuredOutputMode.NATIVE,
        provider_options=MappingProxyType({"seed": 7}),
        memory_target_chars=20 if memory else None,
        memory_max_chars=50 if memory else None,
        version=1,
        updated_at=NOW,
        resolved_structured_output_mode=StructuredOutputMode.NATIVE,
    )


def build_test_settings() -> RunnableTaskSettingsBundle:
    model = ModelRecord(
        id=1,
        provider_id=1,
        display_name="确定性模型",
        remote_model="deterministic",
        capabilities={"json_output": True},
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )
    return RunnableTaskSettingsBundle(
        task_settings={key: _task_snapshot(key) for key in TaskKey},
        models={1: model},
        connections={
            1: ProviderConnectionRecord(
                provider_id=1,
                provider_type="deterministic",
                base_url="https://unused.invalid/v1",
                api_key=SecretStr("integration-only-secret"),
                options={},
            )
        },
    )


def build_integration_test_db(tmp_path: Path) -> sessionmaker[Session]:
    config = AppConfig.for_local_app_data(tmp_path)
    upgrade_database(config.paths.database_path, Path(__file__).parents[3] / "alembic.ini")
    factory = create_session_factory(create_sqlite_engine(config.paths.database_path))
    with factory() as session:
        session.add_all(_role(role_id) for role_id in range(1, 8))
        world = World(
            id=1,
            active_branch_id=None,
            created_at=NOW,
            updated_at=NOW,
            last_played_at=NOW,
        )
        session.add(world)
        session.flush()
        branch = WorldBranch(
            id=1,
            world_id=1,
            name="主分支",
            parent_branch_id=None,
            fork_turn_id=None,
            head_turn_id=None,
            day=1,
            time_slot="morning",
            current_location_id="the_home",
            state_version=1,
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(branch)
        session.flush()
        world.active_branch_id = branch.id
        for role_id in range(1, 8):
            session.add(
                WorldRoleState(
                    world_id=1,
                    role_id=role_id,
                    kind="player" if role_id == 1 else "npc",
                    enabled=True,
                    change_values_json={},
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        session.flush()
        for role_id in range(1, 8):
            session.add(
                WorldRoleMemory(
                    world_id=1,
                    role_id=role_id,
                    memory=("很长的既有记忆" * 20 if role_id == 2 else ""),
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
        locations = {
            2: "the_home",
            3: "the_home",
            4: "the_dungeon",
            5: "the_dungeon",
            6: "the_school",
        }
        # morning 与 midday 使用相同固定规则，使第二轮仍覆盖多人、单人和 offline。
        for role_id, location_id in locations.items():
            for time_slot in ("morning", "midday"):
                rule = CharacterLocationRule(
                    world_id=1,
                    role_id=role_id,
                    weekday_mask=1,
                    time_slot=time_slot,
                    mode="fixed",
                    priority=1,
                    enabled=True,
                )
                session.add(rule)
                session.flush()
                session.add(
                    CharacterLocationCandidate(
                        rule_id=rule.id,
                        location_id=location_id,
                        weight=1,
                    )
                )
        session.commit()
    return factory


@pytest.fixture
def integration_db(tmp_path: Path) -> sessionmaker[Session]:
    return build_integration_test_db(tmp_path)


class DeterministicProvider:
    provider_type = "deterministic"

    def __init__(self) -> None:
        self.location_calls: dict[str, int] = {}
        self.attribute_calls: dict[str, int] = {}
        self.successful_attribute_calls: list[tuple[str, frozenset[int]]] = []
        self.home_invalid_attribute_attempts = 0
        self.location_intents: dict[str, list[str | None]] = {}
        self.max_parallel_locations = 0
        self._active_locations = 0
        self._location_barrier = asyncio.Event()
        self._invalid_home_attribute_returned = False
        self.connection_count: Callable[[], int] = lambda: 0

    async def complete(
        self,
        request: ChatRequest,
        connection: ProviderConnection,
    ) -> ChatResponse:
        del connection
        raw = request.messages[-1].content
        assert raw is not None
        context = parse_json_object(raw)
        # Provider 调用代表慢 I/O；此刻若仍有连接被占用就说明事务边界泄漏。
        assert self.connection_count() == 0
        location_id = require_json_string(context.get("location_id"), "地点 ID")
        if "day" in context:
            self.location_calls[location_id] = self.location_calls.get(location_id, 0) + 1
            intent = context.get("player_intent")
            assert intent is None or isinstance(intent, str)
            self.location_intents.setdefault(location_id, []).append(intent)
            self._active_locations += 1
            self.max_parallel_locations = max(self.max_parallel_locations, self._active_locations)
            if self._active_locations >= 2:
                self._location_barrier.set()
            try:
                await asyncio.wait_for(
                    self._location_barrier.wait(),
                    timeout=ASYNC_TEST_TIMEOUT_SECONDS,
                )
            except TimeoutError as error:
                raise AssertionError("地点调用未并行到达屏障, 执行器可能已退化为串行") from error
            self._active_locations -= 1
            text = self._location_output(context).model_dump_json()
        else:
            self.attribute_calls[location_id] = self.attribute_calls.get(location_id, 0) + 1
            role_ids = frozenset(
                require_json_int(item.get("role_id"), "角色 ID") for item in role_objects(context)
            )
            if location_id == "the_home" and not self._invalid_home_attribute_returned:
                self._invalid_home_attribute_returned = True
                self.home_invalid_attribute_attempts += 1
                text = "not-json"
            else:
                self.successful_attribute_calls.append((location_id, role_ids))
                text = self._attribute_output(context).model_dump_json()
        return ChatResponse(
            text=text,
            reasoning=None,
            tool_calls=[],
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            provider_id=1,
            model_id="deterministic",
        )

    @staticmethod
    def _location_output(context: JsonObject) -> LocationSimulationOutput:
        location_id = require_json_string(context.get("location_id"), "地点 ID")
        role_ids = [
            require_json_int(role.get("role_id"), "角色 ID") for role in role_objects(context)
        ]
        if location_id == "the_home":
            groups = [
                InteractionGroupOutput(group_id="player-alone", role_ids=[1]),
                InteractionGroupOutput(group_id="npc-pair", role_ids=[2, 3]),
            ]
            events = [
                ObjectiveEventOutput(
                    event_key="npc_exchange",
                    group_id="npc-pair",
                    event_type="conversation",
                    fact={"summary": "两名 NPC 自主交换消息"},
                    knowledge=[
                        EventKnowledge(
                            role_id=2,
                            level="participant",
                            perspective_notes="发起者",
                        ),
                        EventKnowledge(
                            role_id=3,
                            level="participant",
                            perspective_notes="回应者",
                        ),
                    ],
                )
            ]
        else:
            groups = [
                InteractionGroupOutput(
                    group_id=f"group-{location_id}",
                    role_ids=role_ids,
                )
            ]
            events = []
        known = {2: ["npc_exchange"], 3: ["npc_exchange"]} if location_id == "the_home" else {}
        return LocationSimulationOutput(
            location_id=location_id,
            groups=groups,
            events=events,
            chronicles=[
                RoleChronicleOutput(
                    role_id=role_id,
                    content=f"角色{role_id}在{location_id}度过本轮。",
                    known_event_keys=known.get(role_id, []),
                )
                for role_id in role_ids
            ],
        )

    @staticmethod
    def _attribute_output(context: JsonObject) -> AttributeMemoryAnalysisOutput:
        outputs: list[RoleAttributeMemoryOutput] = []
        for role in role_objects(context):
            role_id = require_json_int(role.get("role_id"), "角色 ID")
            intents: list[AttributeUpdateIntent] = []
            if role_id == 2:
                intents.append(
                    AttributeUpdateIntent(
                        role_id=2,
                        attribute_key="level",
                        operation="increment",
                        value=1,
                        reason="NPC 自主交流获得经验",
                        source_event_id="npc_exchange",
                        expected_version=require_json_int(
                            role.get("attribute_version"),
                            "属性版本",
                        ),
                    )
                )
            outputs.append(
                RoleAttributeMemoryOutput(
                    role_id=role_id,
                    attribute_update_intents=intents,
                    memory_append=f"角色{role_id}本轮摘要",
                )
            )
        return AttributeMemoryAnalysisOutput(
            location_id=require_json_string(context.get("location_id"), "地点 ID"),
            roles=outputs,
        )

    def stream(
        self,
        request: ChatRequest,
        connection: ProviderConnection,
    ) -> AsyncIterator[ChatStreamEvent]:
        del request, connection
        raise AssertionError("纵向回归不调用流式 Provider")
        yield


async def _run_turn(
    factory: sessionmaker[Session],
    provider: DeterministicProvider,
    intent: str,
) -> tuple[int, tuple[ProgressEvent, ...]]:
    snapshot = ContextBuilder(factory).build_current_turn_snapshot(world_id=1, player_intent=intent)
    invoker = TaskInvoker(
        build_test_settings(),
        ProviderRegistry([provider]),
        RetryPolicy(backoff_seconds=0, sleep=no_test_wait),
    )
    settlement = SettlementService(factory, clock=lambda: NOW)
    manager = TurnRunManager(
        lambda frozen, sink: MapChainExecutor(frozen, progress_sink=sink),
        settlement_handler=settlement.settle,
    )
    run = await manager.create(snapshot, invoker)
    subscription = await manager.claim(run.run_id)
    events: list[ProgressEvent] = []
    while True:
        try:
            item = await asyncio.wait_for(
                subscription.receive(),
                timeout=ASYNC_TEST_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            pytest.fail("完整轮次未在短超时内产生下一条进度, 可能发生并发死锁")
        events.append(item)
        if item.kind.startswith("run_"):
            break
    try:
        summary = await asyncio.wait_for(
            manager.wait(run.run_id),
            timeout=ASYNC_TEST_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        pytest.fail("完整轮次已发终态但 Manager 未及时释放活动槽")
    assert summary.status is RunStatus.SUCCEEDED
    assert summary.turn_id is not None
    return summary.turn_id, tuple(events)


async def no_test_wait(_seconds: float) -> None:
    return None


async def test_complete_two_turn_loop_is_parallel_isolated_and_atomic(
    integration_db: sessionmaker[Session],
) -> None:
    """覆盖冻结上下文、并行节点、原子结算和历史 DTO 的同一真实调用链。"""

    provider = DeterministicProvider()
    bind = integration_db.kw.get("bind")
    assert isinstance(bind, Engine)
    engine = bind
    checked_out = 0

    def checkout(*_args: object) -> None:
        nonlocal checked_out
        checked_out += 1

    def checkin(*_args: object) -> None:
        nonlocal checked_out
        checked_out -= 1

    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    provider.connection_count = lambda: checked_out
    try:
        first_turn_id, first_events = await _run_turn(
            integration_db, provider, "尝试与同地点角色交流"
        )
        second_turn_id, _ = await _run_turn(integration_db, provider, "继续观察各地变化")
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)

    # Provider 等待并行屏障时连接数必须为零，慢 I/O 绝不持有 Session。
    assert checked_out == 0
    assert provider.max_parallel_locations >= 2
    assert provider.location_calls == {"the_home": 2, "the_dungeon": 2, "the_school": 2}
    assert provider.location_intents == {
        "the_home": ["尝试与同地点角色交流", "继续观察各地变化"],
        "the_dungeon": [None, None],
        "the_school": [None, None],
    }
    assert provider.attribute_calls == {"the_home": 3, "the_dungeon": 2, "the_school": 2}
    assert provider.home_invalid_attribute_attempts == 1
    assert len(provider.successful_attribute_calls) == 6
    assert Counter(provider.successful_attribute_calls) == Counter(
        {
            ("the_home", frozenset({1, 2, 3})): 2,
            ("the_dungeon", frozenset({4, 5})): 2,
            ("the_school", frozenset({6})): 2,
        }
    )
    assert any(
        item.location_id == "the_home"
        and item.node is not None
        and item.node.value == "attribute_memory_analysis"
        and item.retrying
        for item in first_events
    )

    history = SettlementService(integration_db).list_history(world_id=1)
    assert [item.turn_id for item in history] == [second_turn_id, first_turn_id]
    assert [(item.day, item.time_slot) for item in history] == [(1, "midday"), (1, "morning")]
    assert [role.role_id for role in history[0].roles] == [1, 2, 3, 4, 5, 6, 7]
    assert history[0].roles[-1].offline is True
    assert history[0].roles[-1].content == OFFLINE_STORY_CONTENT
    assert any(event.fact["summary"] == "两名 NPC 自主交换消息" for event in history[0].events)
    assert [change.role_id for change in history[0].state_changes] == [2]

    with integration_db() as session:
        branch = session.get(WorldBranch, 1)
        assert branch is not None
        assert (branch.day, branch.time_slot, branch.state_version, branch.head_turn_id) == (
            1,
            "evening",
            3,
            second_turn_id,
        )
        turns = list(session.scalars(select(Turn).order_by(Turn.id)))
        stories = list(
            session.scalars(select(TurnStory).order_by(TurnStory.turn_id, TurnStory.sort_order))
        )
        assert len(stories) == 12
        assert [item.role_id for item in stories if item.turn_id == turns[0].id] == [
            1,
            2,
            3,
            4,
            5,
            6,
        ]
        assert [item.role_id for item in stories if item.turn_id == turns[1].id] == [
            1,
            2,
            3,
            4,
            5,
            6,
        ]
        assert all(item.role_id != 7 for item in stories)
        first_after = require_json_object(
            turns[0].state_after_json.get("after"),
            "第一轮结算状态",
        )
        first_next_positions = require_json_object(
            first_after.get("npc_positions"),
            "第一轮下一位置",
        )
        assert require_json_string(first_after.get("time_slot"), "第一轮下一时段") == "midday"
        assert first_next_positions == {
            "2": "the_home",
            "3": "the_home",
            "4": "the_dungeon",
            "5": "the_dungeon",
            "6": "the_school",
            "7": "offline",
        }
        second_after = require_json_object(
            turns[1].state_after_json.get("after"),
            "第二轮结算状态",
        )
        second_next_positions = require_json_object(
            second_after.get("npc_positions"),
            "第二轮下一位置",
        )
        assert require_json_string(second_after.get("time_slot"), "第二轮下一时段") == "evening"
        assert second_next_positions == {
            "2": "offline",
            "3": "offline",
            "4": "offline",
            "5": "offline",
            "6": "offline",
            "7": "offline",
        }
        memories = list(session.scalars(select(WorldRoleMemory).order_by(WorldRoleMemory.role_id)))
        assert memories[0].memory == "角色1本轮摘要__角色1本轮摘要"
        assert len(memories[1].memory) > 50
        assert memories[1].memory.endswith("__角色2本轮摘要__角色2本轮摘要")
        assert memories[-1].memory == ""
        assert session.scalar(select(StateChange).where(StateChange.role_id == 2)) is not None
        latest_event_ids = list(
            session.scalars(select(TurnEvent.id).where(TurnEvent.turn_id == turns[1].id))
        )
        participants = list(
            session.scalars(
                select(TurnEventParticipant)
                .where(TurnEventParticipant.event_id.in_(latest_event_ids))
                .order_by(TurnEventParticipant.role_id)
            )
        )
        assert [item.role_id for item in participants] == [2, 3]


async def test_real_asgi_turn_stream_history_and_game_view_share_one_settled_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实 HTTP 纵向链路必须让流、历史与游戏视图读取同一次原子结算。"""

    build_integration_test_db(tmp_path)
    config = AppConfig.for_local_app_data(tmp_path)
    app = create_app(config)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        task_invoker_value: object = app.state.task_invoker
        assert isinstance(task_invoker_value, TaskInvoker)
        task_invoker = task_invoker_value
        provider = DeterministicProvider()
        # 只替换应用已装配 Invoker 的外部 AI 边界，Router、NDJSON、Manager 与结算服务仍走生产装配。
        monkeypatch.setattr(task_invoker, "_settings", build_test_settings())
        monkeypatch.setattr(task_invoker, "_registry", ProviderRegistry([provider]))
        monkeypatch.setattr(
            task_invoker,
            "_retry_policy",
            RetryPolicy(backoff_seconds=0, sleep=no_test_wait),
        )

        created = await client.post(
            "/api/worlds/1/turn-runs",
            json={"player_intent": "通过真实路由观察同地点角色"},
        )
        assert created.status_code == 202, created.text
        created_body = parse_json_object(created.text)
        run_id = require_json_string(created_body.get("run_id"), "运行 ID")

        streamed = await client.get(f"/api/turn-runs/{run_id}/stream")
        assert streamed.status_code == 200, streamed.text
        events = [parse_json_object(line) for line in streamed.text.splitlines() if line]
        terminal = events[-1]
        assert terminal.get("kind") == "run_succeeded"
        assert terminal.get("run_id") == run_id
        terminal_turn = require_json_object(terminal.get("turn"), "成功事件完整轮次")
        turn_id = require_json_int(terminal_turn.get("turn_id"), "轮次 ID")
        assert terminal_turn.get("day") == 1
        assert terminal_turn.get("time_slot") == "morning"
        assert terminal_turn.get("player_intent") == "通过真实路由观察同地点角色"
        assert [
            require_json_int(require_json_object(item, "角色故事").get("role_id"), "角色 ID")
            for item in require_json_array(terminal_turn.get("roles"), "完整角色故事")
        ] == [1, 2, 3, 4, 5, 6, 7]
        state_changes = require_json_array(terminal_turn.get("state_changes"), "属性变化")
        assert state_changes == [
            {
                "role_id": 2,
                "attribute_key": "level",
                "operation": "increment",
                "old_value": 10,
                "operand": 1,
                "new_value": 11,
                "reason": "NPC 自主交流获得经验",
            }
        ]

        history_response = await client.get("/api/worlds/1/turns")
        assert history_response.status_code == 200, history_response.text
        history = parse_json_array(history_response.text)
        assert history == [terminal_turn]

        game_view_response = await client.get(
            "/api/worlds/1/game-view", params={"scene_id": "the_home"}
        )
        assert game_view_response.status_code == 200, game_view_response.text
        game_view = parse_json_object(game_view_response.text)
        assert game_view.get("day") == 1
        assert game_view.get("time_slot") == "midday"
        visible_roles = [
            require_json_object(item, "游戏视图角色")
            for item in require_json_array(game_view.get("visible_roles"), "可见角色")
        ]
        assert [require_json_int(item.get("role_id"), "可见角色 ID") for item in visible_roles] == [
            1,
            2,
            3,
        ]
        role_two = visible_roles[1]
        assert require_json_object(role_two.get("effective_attributes"), "最终属性") == {
            "level": 11
        }

        status_response = await client.get(f"/api/turn-runs/{run_id}")
        assert status_response.status_code == 200, status_response.text
        status_body = parse_json_object(status_response.text)
        assert status_body.get("status") == "succeeded"
        assert status_body.get("turn_id") == turn_id
