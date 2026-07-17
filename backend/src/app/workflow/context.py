"""在短 Session 中冻结地点、角色状态与严格隔离的 AI 上下文。"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeGuard

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.attribute import (
    AttributeDefinitionMaps,
    AttributeScalar,
    decode_attribute_definitions,
    resolve_effective_attributes,
)
from app.game.locations import LOCATION_IDS, OFFLINE, RolePresence
from app.story.store import KnownEventRecord, RecentRoleTurnRecord, StoryStore
from app.workflow.schemas import (
    InteractionGroupOutput,
    LocationSimulationOutput,
    ObjectiveEventOutput,
    RoleChronicleOutput,
    validate_location_simulation_output,
)
from app.workflow.settings import FrozenJsonValue, freeze_json_object
from app.world.models import WorldRoleMemory
from app.world.store import WorldStore


class ContextBuildError(ValueError):
    """冻结位置与当前持久化角色事实不一致，轮次不能启动。"""


@dataclass(frozen=True)
class KnownEventContext:
    event_id: int
    event_type: str
    fact: Mapping[str, FrozenJsonValue]
    knowledge_level: str
    perspective_notes: str


@dataclass(frozen=True)
class RecentTurnContext:
    turn_id: int
    day: int
    time_slot: str
    own_chronicle: str
    known_events: tuple[KnownEventContext, ...]


@dataclass(frozen=True)
class RoleSimulationContext:
    role_id: int
    name: str
    persona: str
    system_prompt: str
    world_book: str
    effective_attributes: Mapping[str, AttributeScalar]
    attribute_update_rules: Mapping[str, str]
    attribute_version: int
    long_term_memory: str
    recent_turns: tuple[RecentTurnContext, ...]


@dataclass(frozen=True)
class LocationSimulationContext:
    location_id: str
    day: int
    time_slot: str
    player_intent: str | None
    roles: tuple[RoleSimulationContext, ...]


@dataclass(frozen=True)
class TurnContextSnapshot:
    world_id: int
    branch_id: int
    day: int
    time_slot: str
    world_state_version: int
    protagonist_role_id: int
    turn_positions: Mapping[int, str]
    locations: tuple[LocationSimulationContext, ...]


@dataclass(frozen=True)
class RoleAttributeMemoryContext:
    role_id: int
    chronicle: RoleChronicleOutput
    known_events: tuple[ObjectiveEventOutput, ...]
    effective_attributes: Mapping[str, AttributeScalar]
    attribute_update_rules: Mapping[str, str]
    attribute_version: int


@dataclass(frozen=True)
class AttributeMemoryContext:
    location_id: str
    groups: tuple[InteractionGroupOutput, ...]
    events: tuple[ObjectiveEventOutput, ...]
    roles: tuple[RoleAttributeMemoryContext, ...]


def _definition_maps(role: object) -> AttributeDefinitionMaps:
    # Role 的映射字段由 ORM 精确标注；单独函数保持解码入口与世界服务一致。
    from app.character.models import Role

    if not isinstance(role, Role):
        raise ContextBuildError("角色主记录无效")
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


def _event_context(record: KnownEventRecord) -> KnownEventContext:
    return KnownEventContext(
        event_id=record.event_id,
        event_type=record.event_type,
        fact=freeze_json_object(record.fact),
        knowledge_level=record.knowledge_level,
        perspective_notes=record.perspective_notes,
    )


def _recent_turn_context(record: RecentRoleTurnRecord) -> RecentTurnContext:
    return RecentTurnContext(
        turn_id=record.turn_id,
        day=record.day,
        time_slot=record.time_slot,
        own_chronicle=record.own_chronicle,
        known_events=tuple(_event_context(event) for event in record.known_events),
    )


class ContextBuilder:
    """一次调用只短暂读库，返回值可在慢 AI I/O 期间安全持有。"""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def build_turn_snapshot(
        self,
        *,
        world_id: int,
        branch_id: int,
        day: int,
        time_slot: str,
        player_intent: str,
        presences: Sequence[RolePresence],
    ) -> TurnContextSnapshot:
        role_ids = [presence.role_id for presence in presences]
        if len(role_ids) != len(set(role_ids)):
            raise ContextBuildError("冻结位置包含重复角色")
        players = [presence for presence in presences if presence.kind == "player"]
        if len(players) != 1:
            raise ContextBuildError("冻结位置必须恰有一名主角")
        player = players[0]
        if player.location_id not in LOCATION_IDS:
            raise ContextBuildError("主角冻结地点无效")
        for presence in presences:
            if presence.location_id not in {*LOCATION_IDS, OFFLINE}:
                raise ContextBuildError("角色冻结地点无效")

        positions = MappingProxyType(
            {presence.role_id: presence.location_id for presence in presences}
        )
        located = [
            presence
            for presence in presences
            if presence.enabled and presence.location_id != OFFLINE
        ]
        roles_by_location: dict[str, list[RoleSimulationContext]] = {
            location_id: [] for location_id in LOCATION_IDS
        }

        with self._session_factory() as session:
            world_store = WorldStore(session)
            story_store = StoryStore(session)
            world = world_store.get_world(world_id)
            branch = world_store.get_branch(branch_id)
            if world is None or branch is None or branch.world_id != world_id:
                raise ContextBuildError("世界或活动分支不存在")
            if branch.day != day or branch.time_slot != time_slot:
                raise ContextBuildError("冻结时间与分支事实不一致")
            world_state_version = branch.state_version

            ordered = sorted(
                located,
                key=lambda item: (
                    LOCATION_IDS.index(item.location_id),
                    item.kind != "player",
                    item.role_id,
                ),
            )
            for presence in ordered:
                state = world_store.get_role_state(world_id, presence.role_id)
                role = world_store.get_role(presence.role_id)
                memory = session.scalar(
                    select(WorldRoleMemory).where(
                        WorldRoleMemory.world_id == world_id,
                        WorldRoleMemory.role_id == presence.role_id,
                    )
                )
                if (
                    state is None
                    or role is None
                    or memory is None
                    or not state.enabled
                    or state.kind != presence.kind
                ):
                    raise ContextBuildError("冻结角色与世界角色事实不一致")

                definitions = decode_attribute_definitions(_definition_maps(role))
                scalar_changes = {
                    key: value
                    for key, value in state.change_values_json.items()
                    if _is_attribute_scalar(value)
                }
                effective = resolve_effective_attributes(definitions, scalar_changes)
                recent = story_store.list_recent_role_turns(
                    world_id=world_id,
                    branch_id=branch_id,
                    role_id=role.id,
                )
                roles_by_location[presence.location_id].append(
                    RoleSimulationContext(
                        role_id=role.id,
                        name=role.name,
                        persona=role.persona,
                        system_prompt=role.system_prompt,
                        world_book=role.world_book,
                        effective_attributes=MappingProxyType(effective),
                        attribute_update_rules=MappingProxyType(
                            {item.key: item.update_rule for item in definitions}
                        ),
                        attribute_version=state.version,
                        long_term_memory=memory.memory,
                        recent_turns=tuple(_recent_turn_context(item) for item in recent),
                    )
                )

        locations = tuple(
            LocationSimulationContext(
                location_id=location_id,
                day=day,
                time_slot=time_slot,
                player_intent=(player_intent if location_id == player.location_id else None),
                roles=tuple(roles_by_location[location_id]),
            )
            for location_id in LOCATION_IDS
            if roles_by_location[location_id]
        )
        return TurnContextSnapshot(
            world_id=world_id,
            branch_id=branch_id,
            day=day,
            time_slot=time_slot,
            world_state_version=world_state_version,
            protagonist_role_id=player.role_id,
            turn_positions=positions,
            locations=locations,
        )

    @staticmethod
    def build_attribute_memory_context(
        location: LocationSimulationContext,
        simulation: LocationSimulationOutput,
    ) -> AttributeMemoryContext:
        """第二节点只复用本地图冻结角色和本地图本轮已校验结构。"""

        expected_role_ids = {role.role_id for role in location.roles}
        validate_location_simulation_output(
            simulation,
            expected_location_id=location.location_id,
            expected_role_ids=expected_role_ids,
        )
        chronicles = {item.role_id: item for item in simulation.chronicles}
        return AttributeMemoryContext(
            location_id=location.location_id,
            groups=tuple(simulation.groups),
            events=tuple(simulation.events),
            roles=tuple(
                RoleAttributeMemoryContext(
                    role_id=role.role_id,
                    chronicle=chronicles[role.role_id],
                    known_events=tuple(
                        event
                        for event in simulation.events
                        if any(item.role_id == role.role_id for item in event.knowledge)
                    ),
                    effective_attributes=role.effective_attributes,
                    attribute_update_rules=role.attribute_update_rules,
                    attribute_version=role.attribute_version,
                )
                for role in location.roles
            ),
        )
