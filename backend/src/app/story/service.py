"""成功轮次的原子结算与完整历史投影。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeGuard

from sqlalchemy.orm import Session, sessionmaker

from app.ai.types import JsonValue
from app.attribute import (
    AttributeDefinitionMaps,
    AttributeScalar,
    AttributeUpdateIntent,
    apply_attribute_updates,
    decode_attribute_definitions,
    resolve_effective_attributes,
)
from app.character.models import Role
from app.game.locations import OFFLINE
from app.game.time import advance_time
from app.story.models import (
    StateChange,
    Turn,
    TurnEvent,
    TurnEventParticipant,
    TurnStory,
)
from app.story.store import StoryDataError, StoryStore
from app.workflow.runtime import RunStatus, TurnRun
from app.workflow.schemas import (
    AttributeMemoryAnalysisOutput,
    LocationSimulationOutput,
    RoleAttributeMemoryOutput,
    validate_attribute_memory_output,
    validate_location_simulation_output,
)
from app.world.models import WorldRoleMemory, WorldRoleState
from app.world.service import resolve_world_presences
from app.world.store import WorldStore

OFFLINE_STORY_CONTENT = "本轮处于离线状态。未参与推演。"


class SettlementConflictError(RuntimeError):
    """冻结世界事实已变化，本轮 AI 输出必须整体作废。"""


@dataclass(frozen=True)
class TurnRoleHistoryRecord:
    role_id: int
    content: str
    offline: bool


@dataclass(frozen=True)
class TurnEventHistoryRecord:
    event_id: int
    location_id: str
    event_type: str
    fact: dict[str, JsonValue]


@dataclass(frozen=True)
class StateChangeHistoryRecord:
    role_id: int
    attribute_key: str
    operation: str
    old_value: JsonValue
    operand: JsonValue
    new_value: JsonValue
    reason: str


@dataclass(frozen=True)
class TurnHistoryRecord:
    turn_id: int
    day: int
    time_slot: str
    player_intent: str
    roles: tuple[TurnRoleHistoryRecord, ...]
    events: tuple[TurnEventHistoryRecord, ...]
    state_changes: tuple[StateChangeHistoryRecord, ...]


@dataclass(frozen=True)
class _PreparedChange:
    intent: AttributeUpdateIntent
    old_value: AttributeScalar
    new_value: AttributeScalar


@dataclass(frozen=True)
class _PreparedRole:
    state: WorldRoleState
    memory: WorldRoleMemory
    analysis: RoleAttributeMemoryOutput
    next_changes: dict[str, AttributeScalar]
    changes: tuple[_PreparedChange, ...]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _definition_maps(role: Role) -> AttributeDefinitionMaps:
    return AttributeDefinitionMaps(
        base_values=role.base_values_json,
        types=role.attribute_types_json,
        labels=role.attribute_labels_json,
        descriptions=role.attribute_descriptions_json,
        update_rules=role.attribute_update_rules_json,
        constraints=role.attribute_constraints_json,
        allowed_operations=role.attribute_allowed_operations_json,
        examples=role.attribute_examples_json,
    )


def _is_attribute_scalar(value: object) -> TypeGuard[AttributeScalar]:
    return type(value) in {int, float, str, bool}


def _scalar_changes(state: WorldRoleState) -> dict[str, AttributeScalar]:
    return {
        key: value for key, value in state.change_values_json.items() if _is_attribute_scalar(value)
    }


def _ordered_role_ids(role_ids: set[int], protagonist_role_id: int) -> tuple[int, ...]:
    if protagonist_role_id not in role_ids:
        raise SettlementConflictError("冻结主角不在启用角色中")
    return (protagonist_role_id, *(sorted(role_ids - {protagonist_role_id})))


class SettlementService:
    """慢 AI I/O 结束后，只在一个短 Session 中校验并提交完整轮次。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock

    async def settle(self, run: TurnRun) -> int:
        """满足 Manager 的异步 handler；内部不等待慢 I/O，只执行同步短事务。"""

        snapshot = run.snapshot
        if run.status is not RunStatus.SUCCEEDED or snapshot is None:
            raise SettlementConflictError("轮次没有可结算的完整冻结输入")
        now = self._clock()
        with self._session_factory() as session:
            try:
                turn_id = self._settle_in_session(session, run, now)
                session.commit()
            except BaseException:
                session.rollback()
                raise
        return turn_id

    def _settle_in_session(self, session: Session, run: TurnRun, now: datetime) -> int:
        snapshot = run.snapshot
        if snapshot is None:
            raise SettlementConflictError("冻结输入已释放")
        world_store = WorldStore(session)
        story_store = StoryStore(session)
        world = world_store.get_world(snapshot.world_id)
        branch = world_store.get_world_branch(snapshot.world_id, snapshot.branch_id)
        if (
            world is None
            or branch is None
            or world.active_branch_id != branch.id
            or branch.state_version != snapshot.world_state_version
            or branch.day != snapshot.day
            or branch.time_slot != snapshot.time_slot
        ):
            raise SettlementConflictError("世界或分支版本已变化")

        simulations, analyses = self._validated_outputs(run)
        located_role_ids = {
            role.role_id for location in snapshot.locations for role in location.roles
        }
        frozen_role_ids = set(snapshot.turn_positions)
        enabled_states = {
            state.role_id: state
            for state in world_store.list_role_states(snapshot.world_id)
            if state.enabled
        }
        if (
            set(enabled_states) != frozen_role_ids
            or set(snapshot.world_role_versions) != frozen_role_ids
            or any(
                enabled_states[role_id].version != snapshot.world_role_versions[role_id]
                for role_id in frozen_role_ids
            )
        ):
            raise SettlementConflictError("角色状态版本已变化")
        current_roles: dict[int, Role] = {}
        if set(snapshot.role_definition_versions) != frozen_role_ids:
            raise SettlementConflictError("角色定义版本已变化")
        for role_id in frozen_role_ids:
            role = world_store.get_role(role_id)
            if role is None or role.version != snapshot.role_definition_versions[role_id]:
                raise SettlementConflictError("角色定义版本已变化")
            current_roles[role_id] = role
        if located_role_ids != {
            role_id
            for role_id, location_id in snapshot.turn_positions.items()
            if location_id != OFFLINE
        }:
            raise SettlementConflictError("冻结角色或位置覆盖已变化")

        analyses_by_role = {
            role.role_id: role for analysis in analyses.values() for role in analysis.roles
        }
        valid_event_keys_by_role: dict[int, set[str]] = {
            role_id: set() for role_id in located_role_ids
        }
        all_event_keys: set[str] = set()
        for simulation in simulations.values():
            for event in simulation.events:
                if event.event_key in all_event_keys:
                    raise SettlementConflictError("跨地图事件 key 不能重复")
                all_event_keys.add(event.event_key)
                for knowledge in event.knowledge:
                    valid_event_keys_by_role[knowledge.role_id].add(event.event_key)

        prepared: dict[int, _PreparedRole] = {}
        for role_id in _ordered_role_ids(located_role_ids, snapshot.protagonist_role_id):
            state = enabled_states[role_id]
            role = current_roles[role_id]
            memory = world_store.get_role_memory(snapshot.world_id, role_id)
            analysis = analyses_by_role.get(role_id)
            context = next(
                item
                for location in snapshot.locations
                for item in location.roles
                if item.role_id == role_id
            )
            if memory is None or analysis is None or state.version != context.attribute_version:
                raise SettlementConflictError("角色属性或记忆版本已变化")
            definitions = decode_attribute_definitions(_definition_maps(role))
            current_changes = _scalar_changes(state)
            # 所有角色先在内存副本完整应用；到此循环结束前不得修改任何 ORM 字段。
            next_changes = current_changes
            prepared_changes: list[_PreparedChange] = []
            for intent in analysis.attribute_update_intents:
                old_effective = resolve_effective_attributes(definitions, next_changes)
                next_changes = apply_attribute_updates(
                    definitions,
                    next_changes,
                    [intent],
                    role_id=role_id,
                    current_version=state.version,
                    valid_event_keys=valid_event_keys_by_role[role_id],
                )
                new_effective = resolve_effective_attributes(definitions, next_changes)
                prepared_changes.append(
                    _PreparedChange(
                        intent=intent,
                        old_value=old_effective[intent.attribute_key],
                        new_value=new_effective[intent.attribute_key],
                    )
                )
            prepared[role_id] = _PreparedRole(
                state=state,
                memory=memory,
                analysis=analysis,
                next_changes=next_changes,
                changes=tuple(prepared_changes),
            )

        objective_events: list[JsonValue] = []
        for location_id in sorted(simulations):
            for event in simulations[location_id].events:
                objective_events.append(
                    {
                        "event_key": event.event_key,
                        "location_id": location_id,
                        "event_type": event.event_type,
                        "fact": event.fact,
                    }
                )
        player_intent = next(
            (
                location.player_intent
                for location in snapshot.locations
                if location.player_intent is not None
            ),
            "",
        )
        turn = Turn(
            world_id=snapshot.world_id,
            branch_id=snapshot.branch_id,
            parent_turn_id=branch.head_turn_id,
            day=snapshot.day,
            time_slot=snapshot.time_slot,
            player_intent=player_intent,
            objective_events_json=objective_events,
            state_after_json={},
            ai_execution_meta_json={},
            created_at=now,
        )
        story_store.add_turn(turn)

        event_ids: dict[str, int] = {}
        chronicles = {
            chronicle.role_id: chronicle
            for simulation in simulations.values()
            for chronicle in simulation.chronicles
        }
        for location_id in sorted(simulations):
            for event in simulations[location_id].events:
                persisted = TurnEvent(
                    turn_id=turn.id,
                    location_id=location_id,
                    event_type=event.event_type,
                    fact_json=event.fact,
                    created_at=now,
                )
                story_store.add_event(persisted)
                event_ids[event.event_key] = persisted.id
                for knowledge in event.knowledge:
                    story_store.add_event_participant(
                        TurnEventParticipant(
                            event_id=persisted.id,
                            role_id=knowledge.role_id,
                            knowledge_level=knowledge.level,
                            perspective_notes=knowledge.perspective_notes,
                        )
                    )

        for sort_order, role_id in enumerate(
            _ordered_role_ids(located_role_ids, snapshot.protagonist_role_id)
        ):
            story_store.add_story(
                TurnStory(
                    turn_id=turn.id,
                    role_id=role_id,
                    content=chronicles[role_id].content,
                    sort_order=sort_order,
                )
            )

        for role_id in _ordered_role_ids(located_role_ids, snapshot.protagonist_role_id):
            item = prepared[role_id]
            for change in item.changes:
                story_store.add_state_change(
                    self._state_change(turn.id, event_ids, item.state.role_id, change)
                )
            next_values_json: dict[str, JsonValue] = {
                key: value for key, value in item.next_changes.items()
            }
            item.state.change_values_json = next_values_json
            item.state.version += 1
            item.state.updated_at = now
            world_store.save_role_state(item.state)

        for role_id in _ordered_role_ids(located_role_ids, snapshot.protagonist_role_id):
            item = prepared[role_id]
            fragment = item.analysis.memory_append
            item.memory.memory = (
                fragment if not item.memory.memory else f"{item.memory.memory}__{fragment}"
            )
            item.memory.version += 1
            item.memory.updated_at = now
            world_store.save_role_memory(item.memory)

        next_day, next_time_slot = advance_time(snapshot.day, snapshot.time_slot)
        next_positions = resolve_world_presences(
            world_store,
            world_id=snapshot.world_id,
            day=next_day,
            time_slot=next_time_slot,
            player_location_id=branch.current_location_id,
        )
        turn.state_after_json = {
            "protagonist_role_id": snapshot.protagonist_role_id,
            "turn_positions": {
                str(role_id): location_id
                for role_id, location_id in snapshot.turn_positions.items()
            },
            "after": {
                "day": next_day,
                "time_slot": next_time_slot,
                "current_location_id": branch.current_location_id,
                "npc_positions": {
                    str(item.role_id): item.location_id
                    for item in next_positions
                    if item.kind == "npc"
                },
            },
        }
        branch.head_turn_id = turn.id
        branch.day = next_day
        branch.time_slot = next_time_slot
        branch.state_version += 1
        branch.updated_at = now
        world.updated_at = now
        world.last_played_at = now
        session.flush()
        return turn.id

    @staticmethod
    def _validated_outputs(
        run: TurnRun,
    ) -> tuple[
        dict[str, LocationSimulationOutput],
        dict[str, AttributeMemoryAnalysisOutput],
    ]:
        snapshot = run.snapshot
        if snapshot is None or set(run.map_runs) != {
            location.location_id for location in snapshot.locations
        }:
            raise SettlementConflictError("地图输出覆盖不完整")
        simulations: dict[str, LocationSimulationOutput] = {}
        analyses: dict[str, AttributeMemoryAnalysisOutput] = {}
        if run.memory_max_chars is None:
            raise SettlementConflictError("轮次缺少冻结记忆摘要上限")
        for location in snapshot.locations:
            chain = run.map_runs[location.location_id]
            if (
                chain.status is not RunStatus.SUCCEEDED
                or chain.location_output is None
                or chain.attribute_output is None
            ):
                raise SettlementConflictError("地图链输出不完整")
            role_ids = {role.role_id for role in location.roles}
            simulation = validate_location_simulation_output(
                chain.location_output,
                expected_location_id=location.location_id,
                expected_role_ids=role_ids,
            )
            valid_event_keys_by_role = {
                role_id: {
                    event.event_key
                    for event in simulation.events
                    if any(item.role_id == role_id for item in event.knowledge)
                }
                for role_id in role_ids
            }
            analysis = validate_attribute_memory_output(
                chain.attribute_output,
                expected_location_id=location.location_id,
                expected_role_ids=role_ids,
                valid_event_keys_by_role=valid_event_keys_by_role,
                memory_max_chars=run.memory_max_chars,
            )
            simulations[location.location_id] = simulation
            analyses[location.location_id] = analysis
        return simulations, analyses

    @staticmethod
    def _state_change(
        turn_id: int,
        event_ids: dict[str, int],
        role_id: int,
        change: _PreparedChange,
    ) -> StateChange:
        intent = change.intent
        return StateChange(
            turn_id=turn_id,
            event_id=(event_ids[intent.source_event_id] if intent.source_event_id else None),
            role_id=role_id,
            attribute_key=intent.attribute_key,
            operation=intent.operation,
            old_value_json=change.old_value,
            operand_json=intent.value,
            new_value_json=change.new_value,
            reason=intent.reason,
        )

    def list_history(self, *, world_id: int) -> tuple[TurnHistoryRecord, ...]:
        """返回当前内部活动分支的全部成功轮次，旧轮次不裁剪。"""

        with self._session_factory() as session:
            world_store = WorldStore(session)
            world = world_store.get_world(world_id)
            if world is None or world.active_branch_id is None:
                raise SettlementConflictError("世界或活动分支不存在")
            branch = world_store.get_world_branch(world_id, world.active_branch_id)
            if branch is None:
                raise SettlementConflictError("世界或活动分支不存在")
            store = StoryStore(session)
            return tuple(
                self._history_record(store, turn)
                for turn in store.list_turns(world_id=world_id, branch_id=branch.id)
            )

    @staticmethod
    def _history_record(
        store: StoryStore,
        turn: Turn,
    ) -> TurnHistoryRecord:
        positions = turn.state_after_json.get("turn_positions")
        if not isinstance(positions, dict):
            raise StoryDataError("轮次位置快照无效")
        role_positions: dict[int, str] = {}
        for raw_role_id, raw_location in positions.items():
            if not raw_role_id.isdigit() or not isinstance(raw_location, str):
                raise StoryDataError("轮次位置快照无效")
            role_positions[int(raw_role_id)] = raw_location
        ordered_stories = store.list_turn_stories(turn.id)
        stories = {item.role_id: item.content for item in ordered_stories}
        raw_protagonist = turn.state_after_json.get("protagonist_role_id")
        if isinstance(raw_protagonist, int):
            protagonist = raw_protagonist
        elif ordered_stories:
            # 首次发布前的兼容行没有显式主角，sort_order=0 是该轮唯一可靠事实。
            protagonist = ordered_stories[0].role_id
        else:
            raise SettlementConflictError("轮次缺少可恢复的主角事实")
        roles: list[TurnRoleHistoryRecord] = []
        for role_id in _ordered_role_ids(set(role_positions), protagonist):
            offline = role_positions[role_id] == OFFLINE
            content = OFFLINE_STORY_CONTENT if offline else stories.get(role_id)
            if content is None:
                raise StoryDataError("已定位角色缺少独立纪事")
            roles.append(TurnRoleHistoryRecord(role_id=role_id, content=content, offline=offline))
        events = tuple(
            TurnEventHistoryRecord(
                event_id=event.id,
                location_id=event.location_id,
                event_type=event.event_type,
                fact=event.fact_json,
            )
            for event in store.list_turn_events(turn.id)
        )
        state_changes = tuple(
            StateChangeHistoryRecord(
                role_id=change.role_id,
                attribute_key=change.attribute_key,
                operation=change.operation,
                old_value=change.old_value_json,
                operand=change.operand_json,
                new_value=change.new_value_json,
                reason=change.reason,
            )
            for change in store.list_turn_state_changes(turn.id)
        )
        return TurnHistoryRecord(
            turn_id=turn.id,
            day=turn.day,
            time_slot=turn.time_slot,
            player_intent=turn.player_intent,
            roles=tuple(roles),
            events=events,
            state_changes=state_changes,
        )
