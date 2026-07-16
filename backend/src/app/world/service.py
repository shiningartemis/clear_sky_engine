"""世界原子事务、世界角色引用和游戏视图业务。"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeGuard
from urllib.parse import quote

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.attribute import (
    AttributeDefinitionMaps,
    AttributeScalar,
    decode_attribute_definitions,
    resolve_effective_attributes,
)
from app.character.models import Role
from app.character.service import RoleRecord
from app.game.locations import (
    LOCATION_IDS,
    LocationCandidate,
    LocationRule,
    RolePresence,
    enforce_location_capacity,
    resolve_npc_location,
    weekday_for_day,
)
from app.resources.catalog import ResourceCatalog
from app.world.models import (
    CharacterLocationCandidate,
    CharacterLocationRule,
    World,
    WorldBranch,
    WorldRoleMemory,
    WorldRoleState,
)
from app.world.store import WorldStore


class WorldNotFoundError(Exception):
    """请求的世界或世界角色不存在。"""


class WorldConflictError(Exception):
    """世界业务不变量冲突，消息不得携带底层 SQL。"""


class InvalidLocationError(ValueError):
    """地点不属于稳定地图清单。"""


@dataclass(frozen=True)
class WorldRecord:
    id: int
    display_name: str
    active_branch_id: int
    day: int
    weekday: str
    time_slot: str
    player_role: RoleRecord
    npc_count: int
    last_played_at: datetime


@dataclass(frozen=True)
class WorldRoleRecord:
    world_id: int
    role_id: int
    name: str
    kind: Literal["player", "npc"]
    enabled: bool
    effective_attributes: dict[str, AttributeScalar]
    portrait_url: str
    version: int
    updated_at: datetime


@dataclass(frozen=True)
class LocationCandidateDraft:
    location_id: str
    weight: int


@dataclass(frozen=True)
class LocationRuleDraft:
    weekday_mask: int
    time_slot: str
    mode: Literal["fixed", "random"]
    priority: int
    enabled: bool
    candidates: tuple[LocationCandidateDraft, ...]


@dataclass(frozen=True)
class LocationRuleRecord:
    id: int
    world_id: int
    role_id: int
    weekday_mask: int
    time_slot: str
    mode: Literal["fixed", "random"]
    priority: int
    enabled: bool
    candidates: tuple[LocationCandidateDraft, ...]


@dataclass(frozen=True)
class MapLocationRecord:
    scene_id: str
    display_name: str
    order: int
    anchor_x: float
    anchor_y: float


@dataclass(frozen=True)
class GameViewRecord:
    world_id: int
    scene_id: str
    day: int
    weekday: str
    time_slot: str
    background_url: str
    fallback_background_url: str
    player_marker_url: str
    player_location_id: str
    locations: tuple[MapLocationRecord, ...]
    visible_roles: tuple[WorldRoleRecord, ...]


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


def _role_record(role: Role, referenced_world_ids: tuple[int, ...]) -> RoleRecord:
    return RoleRecord(
        id=role.id,
        name=role.name,
        persona=role.persona,
        system_prompt=role.system_prompt,
        world_book=role.world_book,
        attributes=decode_attribute_definitions(_definition_maps(role)),
        portrait_url=f"/api/assets/characters/{quote(role.name, safe='')}/default",
        referenced_world_ids=referenced_world_ids,
        version=role.version,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


def _is_attribute_scalar(value: object) -> TypeGuard[AttributeScalar]:
    return type(value) in {int, float, str, bool}


class WorldService:
    """每次业务调用只持有短事务，文件资源检查永不与 Session 重叠。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        resources: ResourceCatalog,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._resources = resources
        self._clock = clock
        # manifest 是地图的唯一事实来源；应用启动时读取一次，此时尚未打开 Session。
        manifest = resources.load_map_manifest()
        self._scenes = {scene.scene_id: scene for scene in manifest.scenes}
        self._locations = tuple(
            MapLocationRecord(
                scene_id=scene.scene_id,
                display_name=scene.display_name,
                order=scene.order,
                anchor_x=scene.anchor.x,
                anchor_y=scene.anchor.y,
            )
            for scene in sorted(manifest.scenes, key=lambda item: item.order)
            if scene.kind == "location" and scene.anchor is not None
        )

    @staticmethod
    def _commit(session: Session, message: str) -> None:
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise WorldConflictError(message) from None

    @staticmethod
    def _required_branch(store: WorldStore, world: World) -> WorldBranch:
        if world.active_branch_id is None:
            raise WorldConflictError("世界活动分支缺失")
        branch = store.get_branch(world.active_branch_id)
        if branch is None or branch.world_id != world.id:
            raise WorldConflictError("世界活动分支无效")
        return branch

    @staticmethod
    def _required_world(store: WorldStore, world_id: int) -> World:
        world = store.get_world(world_id)
        if world is None:
            raise WorldNotFoundError("世界不存在")
        return world

    @staticmethod
    def _world_role_record(
        store: WorldStore,
        state: WorldRoleState,
    ) -> WorldRoleRecord:
        role = store.get_role(state.role_id)
        if role is None:
            raise WorldConflictError("世界引用的角色不存在")
        definitions = decode_attribute_definitions(_definition_maps(role))
        # JSON 列可含旧结构；只把严格标量交给统一属性组合器，其余静默忽略。
        scalar_changes = {
            key: value
            for key, value in state.change_values_json.items()
            if _is_attribute_scalar(value)
        }
        effective = resolve_effective_attributes(definitions, scalar_changes)
        kind: Literal["player", "npc"] = "player" if state.kind == "player" else "npc"
        return WorldRoleRecord(
            world_id=state.world_id,
            role_id=state.role_id,
            name=role.name,
            kind=kind,
            enabled=state.enabled,
            effective_attributes=effective,
            portrait_url=f"/api/assets/characters/{quote(role.name, safe='')}/default",
            version=state.version,
            updated_at=state.updated_at,
        )

    @classmethod
    def _world_record(cls, store: WorldStore, world: World) -> WorldRecord:
        branch = cls._required_branch(store, world)
        states = store.list_role_states(world.id)
        player_state = next((item for item in states if item.kind == "player"), None)
        if player_state is None:
            raise WorldConflictError("世界主角缺失")
        player = store.get_role(player_state.role_id)
        if player is None:
            raise WorldConflictError("世界主角记录缺失")
        return WorldRecord(
            id=world.id,
            display_name=f"世界 {world.id}",
            active_branch_id=branch.id,
            day=branch.day,
            weekday=weekday_for_day(branch.day),
            time_slot=branch.time_slot,
            player_role=_role_record(player, store.list_reference_world_ids(player.id)),
            npc_count=sum(item.kind == "npc" for item in states),
            last_played_at=world.last_played_at,
        )

    def list_worlds(self) -> list[WorldRecord]:
        with self._session_factory() as session:
            store = WorldStore(session)
            return [self._world_record(store, world) for world in store.list_worlds()]

    def get_world(self, world_id: int) -> WorldRecord:
        with self._session_factory() as session:
            store = WorldStore(session)
            return self._world_record(store, self._required_world(store, world_id))

    def create_world(self, protagonist_role_id: int) -> WorldRecord:
        # 世界只引用全局角色；先复制资源查找所需名称，文件 I/O 不得占用 Session。
        with self._session_factory() as session:
            protagonist = WorldStore(session).get_role(protagonist_role_id)
            if protagonist is None:
                raise WorldNotFoundError("主角角色不存在")
            protagonist_name = protagonist.name
        self._resources.resolve_portrait(protagonist_name)

        now = self._clock()
        world_id: int
        with self._session_factory() as session:
            store = WorldStore(session)
            try:
                # 资源检查后重新确认角色仍存在，避免并发删除留下悬空引用。
                role = store.get_role(protagonist_role_id)
                if role is None:
                    raise WorldNotFoundError("主角角色不存在")
                world = World(
                    active_branch_id=None,
                    created_at=now,
                    updated_at=now,
                    last_played_at=now,
                )
                store.add_all(world)
                store.flush()
                branch = WorldBranch(
                    world_id=world.id,
                    name="主分支",
                    parent_branch_id=None,
                    fork_turn_id=None,
                    head_turn_id=None,
                    day=1,
                    time_slot="morning",
                    current_location_id="the_home",
                    state_version=1,
                    created_at=now,
                    updated_at=now,
                )
                store.add_all(branch)
                store.flush()
                world.active_branch_id = branch.id
                state = WorldRoleState(
                    world_id=world.id,
                    role_id=role.id,
                    kind="player",
                    enabled=True,
                    change_values_json={},
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
                store.add_all(state)
                store.flush()
                store.add_all(
                    WorldRoleMemory(
                        world_id=world.id,
                        role_id=role.id,
                        memory="",
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
                world_id = world.id
                session.commit()
            except IntegrityError:
                session.rollback()
                raise WorldConflictError("世界创建冲突") from None
        # 提交后使用全新 Session，禁止依赖已过期 ORM 对象。
        return self.get_world(world_id)

    def delete_world(self, world_id: int) -> None:
        with self._session_factory() as session:
            store = WorldStore(session)
            self._required_world(store, world_id)
            store.delete_world(world_id)
            self._commit(session, "世界删除冲突")

    def list_world_roles(self, world_id: int) -> list[WorldRoleRecord]:
        with self._session_factory() as session:
            store = WorldStore(session)
            self._required_world(store, world_id)
            return [
                self._world_role_record(store, item) for item in store.list_role_states(world_id)
            ]

    def get_world_role(self, world_id: int, role_id: int) -> WorldRoleRecord:
        with self._session_factory() as session:
            store = WorldStore(session)
            self._required_world(store, world_id)
            state = store.get_role_state(world_id, role_id)
            if state is None:
                raise WorldNotFoundError("世界角色不存在")
            return self._world_role_record(store, state)

    def add_npc(self, world_id: int, role_id: int) -> WorldRoleRecord:
        # 先短暂读取不可变角色名，关闭连接后再访问图片资源。
        with self._session_factory() as session:
            store = WorldStore(session)
            self._required_world(store, world_id)
            role = store.get_role(role_id)
            if role is None:
                raise WorldNotFoundError("角色不存在")
            role_name = role.name
        self._resources.resolve_portrait(role_name)

        now = self._clock()
        with self._session_factory() as session:
            store = WorldStore(session)
            self._required_world(store, world_id)
            if store.get_role(role_id) is None:
                raise WorldNotFoundError("角色不存在")
            if store.count_npcs(world_id) >= 20:
                raise WorldConflictError("每个世界最多包含 20 个 NPC")
            state = WorldRoleState(
                world_id=world_id,
                role_id=role_id,
                kind="npc",
                enabled=True,
                change_values_json={},
                version=1,
                created_at=now,
                updated_at=now,
            )
            store.add_all(state)
            try:
                # 复合外键没有 relationship 可推导顺序，先落父行再写同事务记忆行。
                store.flush()
            except IntegrityError:
                session.rollback()
                raise WorldConflictError("角色已存在于当前世界") from None
            store.add_all(
                WorldRoleMemory(
                    world_id=world_id,
                    role_id=role_id,
                    memory="",
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            self._commit(session, "角色已存在于当前世界")
        return self.get_world_role(world_id, role_id)

    def update_npc_enabled(self, world_id: int, role_id: int, enabled: bool) -> WorldRoleRecord:
        now = self._clock()
        with self._session_factory() as session:
            store = WorldStore(session)
            self._required_world(store, world_id)
            state = store.get_role_state(world_id, role_id)
            if state is None:
                raise WorldNotFoundError("世界角色不存在")
            if state.kind != "npc":
                raise WorldConflictError("主角启用状态不可修改")
            state.enabled = enabled
            state.version += 1
            state.updated_at = now
            self._commit(session, "世界角色更新冲突")
        return self.get_world_role(world_id, role_id)

    def remove_npc(self, world_id: int, role_id: int) -> None:
        with self._session_factory() as session:
            store = WorldStore(session)
            self._required_world(store, world_id)
            state = store.get_role_state(world_id, role_id)
            if state is None:
                raise WorldNotFoundError("世界角色不存在")
            if state.kind != "npc":
                raise WorldConflictError("主角不可移除")
            store.delete_role_state(world_id, role_id)
            self._commit(session, "世界角色删除冲突")

    @staticmethod
    def _validate_rules(rules: Sequence[LocationRuleDraft]) -> None:
        for rule in rules:
            if not 1 <= rule.weekday_mask <= 127:
                raise InvalidLocationError("weekday_mask 必须介于 1 和 127")
            if rule.time_slot not in {"morning", "midday", "evening", "night"}:
                raise InvalidLocationError("时间段无效")
            if not rule.candidates:
                raise InvalidLocationError("位置规则至少需要一个候选地点")
            if rule.mode == "fixed" and len(rule.candidates) != 1:
                raise InvalidLocationError("固定位置规则只能包含一个候选地点")
            if any(
                item.location_id not in LOCATION_IDS or item.weight <= 0 for item in rule.candidates
            ):
                raise InvalidLocationError("位置规则候选无效")

    @staticmethod
    def _location_rule_record(store: WorldStore, rule: CharacterLocationRule) -> LocationRuleRecord:
        mode: Literal["fixed", "random"] = "fixed" if rule.mode == "fixed" else "random"
        return LocationRuleRecord(
            id=rule.id,
            world_id=rule.world_id,
            role_id=rule.role_id,
            weekday_mask=rule.weekday_mask,
            time_slot=rule.time_slot,
            mode=mode,
            priority=rule.priority,
            enabled=rule.enabled,
            candidates=tuple(
                LocationCandidateDraft(location_id=item.location_id, weight=item.weight)
                for item in store.list_candidates(rule.id)
            ),
        )

    def replace_location_rules(
        self,
        world_id: int,
        role_id: int,
        rules: Sequence[LocationRuleDraft],
    ) -> list[LocationRuleRecord]:
        self._validate_rules(rules)
        with self._session_factory() as session:
            store = WorldStore(session)
            self._required_world(store, world_id)
            state = store.get_role_state(world_id, role_id)
            if state is None:
                raise WorldNotFoundError("世界角色不存在")
            if state.kind != "npc":
                raise WorldConflictError("主角不使用 NPC 位置规则")
            store.delete_location_rules(world_id, role_id)
            try:
                for draft in rules:
                    rule = CharacterLocationRule(
                        world_id=world_id,
                        role_id=role_id,
                        weekday_mask=draft.weekday_mask,
                        time_slot=draft.time_slot,
                        mode=draft.mode,
                        priority=draft.priority,
                        enabled=draft.enabled,
                    )
                    store.add_all(rule)
                    store.flush()
                    store.add_all(
                        *(
                            CharacterLocationCandidate(
                                rule_id=rule.id,
                                location_id=item.location_id,
                                weight=item.weight,
                            )
                            for item in draft.candidates
                        )
                    )
                session.commit()
            except IntegrityError:
                session.rollback()
                raise WorldConflictError("位置规则替换冲突") from None

        with self._session_factory() as session:
            store = WorldStore(session)
            return [
                self._location_rule_record(store, item)
                for item in store.list_location_rules(world_id, role_id)
            ]

    def select_location(self, world_id: int, location_id: str) -> GameViewRecord:
        if location_id not in LOCATION_IDS:
            raise InvalidLocationError("地点不存在")
        now = self._clock()
        with self._session_factory() as session:
            store = WorldStore(session)
            world = self._required_world(store, world_id)
            branch = self._required_branch(store, world)
            # 地图移动只改变位置和状态版本，绝不推进 day 或 time_slot。
            branch.current_location_id = location_id
            branch.state_version += 1
            branch.updated_at = now
            self._commit(session, "地点选择冲突")
        return self.get_game_view(world_id, "the_world_map")

    def _rules_for_state(
        self, store: WorldStore, state: WorldRoleState
    ) -> tuple[LocationRule, ...]:
        return tuple(
            LocationRule(
                weekday_mask=rule.weekday_mask,
                time_slot=rule.time_slot,
                mode=rule.mode,
                priority=rule.priority,
                enabled=rule.enabled,
                candidates=tuple(
                    LocationCandidate(location_id=item.location_id, weight=item.weight)
                    for item in store.list_candidates(rule.id)
                ),
            )
            for rule in store.list_location_rules(state.world_id, state.role_id)
        )

    def get_game_view(self, world_id: int, scene_id: str) -> GameViewRecord:
        scene = self._scenes.get(scene_id)
        if scene is None:
            raise InvalidLocationError("地图场景不存在")
        with self._session_factory() as session:
            store = WorldStore(session)
            world = self._required_world(store, world_id)
            branch = self._required_branch(store, world)
            states = store.list_role_states(world_id)
            records = {item.role_id: self._world_role_record(store, item) for item in states}
            player = next((item for item in states if item.kind == "player"), None)
            if player is None:
                raise WorldConflictError("世界主角缺失")

            presences = [
                RolePresence(
                    role_id=player.role_id,
                    kind="player",
                    location_id=branch.current_location_id,
                    enabled=True,
                )
            ]
            for state in states:
                if state.kind != "npc":
                    continue
                location_id = resolve_npc_location(
                    self._rules_for_state(store, state),
                    world_id=world_id,
                    day=branch.day,
                    time_slot=branch.time_slot,
                    role_id=state.role_id,
                )
                presences.append(
                    RolePresence(
                        role_id=state.role_id,
                        kind="npc",
                        location_id=location_id,
                        enabled=state.enabled,
                    )
                )
            resolved = enforce_location_capacity(presences)
            visible_roles = (
                ()
                if scene.kind == "the_world_map"
                else tuple(
                    records[item.role_id] for item in resolved if item.location_id == scene_id
                )
            )
            marker_url = records[player.role_id].portrait_url
            player_location_id = branch.current_location_id
            day = branch.day
            weekday = weekday_for_day(branch.day)
            time_slot = branch.time_slot

        image_url = f"/api/assets/maps/{scene_id}"
        return GameViewRecord(
            world_id=world_id,
            scene_id=scene_id,
            day=day,
            weekday=weekday,
            time_slot=time_slot,
            background_url=image_url,
            fallback_background_url=f"{image_url}?default=true",
            player_marker_url=marker_url,
            player_location_id=player_location_id,
            locations=self._locations,
            visible_roles=visible_roles,
        )
