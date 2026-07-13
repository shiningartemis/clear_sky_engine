"""全局角色库的业务不变量与短事务边界。"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.attribute import (
    AttributeDefinition,
    AttributeDefinitionMaps,
    decode_attribute_definitions,
    encode_attribute_definitions,
    validate_attribute_definitions,
)
from app.character.models import Role
from app.character.store import RoleStore
from app.resources.catalog import ResourceCatalog


class RoleNotFoundError(Exception):
    """请求的全局角色不存在。"""


class RoleConflictError(Exception):
    """角色库业务约束冲突，消息不得携带数据库异常上下文。"""


class RoleReferencedError(RoleConflictError):
    """角色仍被世界引用，删除会破坏世界角色不变量。"""

    def __init__(self, world_ids: tuple[int, ...]) -> None:
        super().__init__("角色被世界引用时禁止删除")
        self.world_ids = world_ids


@dataclass(frozen=True)
class RoleDraft:
    name: str
    persona: str
    system_prompt: str
    world_book: str
    attributes: tuple[AttributeDefinition, ...]


@dataclass(frozen=True)
class RoleChanges:
    persona: str | None = None
    system_prompt: str | None = None
    world_book: str | None = None
    attributes: tuple[AttributeDefinition, ...] | None = None


@dataclass(frozen=True)
class RoleRecord:
    id: int
    name: str
    persona: str
    system_prompt: str
    world_book: str
    attributes: tuple[AttributeDefinition, ...]
    portrait_url: str
    referenced_world_ids: tuple[int, ...]
    version: int
    created_at: datetime
    updated_at: datetime


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RoleService:
    """角色名不可变；每次调用只在内存计算之外短暂持有 Session。"""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        resources: ResourceCatalog,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._resources = resources
        self._clock = clock

    @staticmethod
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

    @classmethod
    def _record(
        cls,
        role: Role,
        referenced_world_ids: tuple[int, ...],
    ) -> RoleRecord:
        return RoleRecord(
            id=role.id,
            name=role.name,
            persona=role.persona,
            system_prompt=role.system_prompt,
            world_book=role.world_book,
            attributes=decode_attribute_definitions(cls._definition_maps(role)),
            portrait_url=f"/api/assets/characters/{quote(role.name, safe='')}/default",
            referenced_world_ids=referenced_world_ids,
            version=role.version,
            created_at=role.created_at,
            updated_at=role.updated_at,
        )

    @staticmethod
    def _write_definition_maps(role: Role, maps: AttributeDefinitionMaps) -> None:
        """完整替换所有定义分列，禁止部分 metadata 与基础 key 错位。"""

        role.base_values_json = maps.base_values
        role.attribute_types_json = maps.types
        role.attribute_labels_json = maps.labels
        role.attribute_descriptions_json = maps.descriptions
        role.attribute_update_rules_json = maps.update_rules
        role.attribute_constraints_json = maps.constraints
        role.attribute_allowed_operations_json = maps.allowed_operations
        role.attribute_examples_json = maps.examples

    @staticmethod
    def _commit(session: Session, conflict_message: str) -> None:
        conflicted = False
        try:
            session.commit()
        except IntegrityError:
            # SQL 异常可能包含用户值；离开 except 后再抛业务错误以彻底丢弃上下文。
            session.rollback()
            conflicted = True
        if conflicted:
            raise RoleConflictError(conflict_message)

    def list_roles(self) -> list[RoleRecord]:
        with self._session_factory() as session:
            store = RoleStore(session)
            return [
                self._record(role, tuple(store.list_reference_world_ids(role.id)))
                for role in store.list_roles()
            ]

    def get_role(self, role_id: int) -> RoleRecord:
        with self._session_factory() as session:
            store = RoleStore(session)
            role = store.get_role(role_id)
            if role is None:
                raise RoleNotFoundError("角色不存在")
            return self._record(role, tuple(store.list_reference_world_ids(role.id)))

    def create_role(self, draft: RoleDraft) -> RoleRecord:
        # 默认立绘是创建前置条件，文件 I/O 必须发生在打开数据库连接之前。
        self._resources.resolve_portrait(draft.name)
        definitions = validate_attribute_definitions(draft.attributes)
        maps = encode_attribute_definitions(definitions)
        now = self._clock()
        with self._session_factory() as session:
            store = RoleStore(session)
            if store.get_role_by_name(draft.name) is not None:
                raise RoleConflictError("角色名称已存在")
            role = Role(
                name=draft.name,
                persona=draft.persona,
                system_prompt=draft.system_prompt,
                world_book=draft.world_book,
                base_values_json=maps.base_values,
                attribute_types_json=maps.types,
                attribute_labels_json=maps.labels,
                attribute_descriptions_json=maps.descriptions,
                attribute_update_rules_json=maps.update_rules,
                attribute_constraints_json=maps.constraints,
                attribute_allowed_operations_json=maps.allowed_operations,
                attribute_examples_json=maps.examples,
                version=1,
                created_at=now,
                updated_at=now,
            )
            store.add_role(role)
            self._commit(session, "角色名称已存在")
            session.refresh(role)
            return self._record(role, ())

    def update_role(self, role_id: int, changes: RoleChanges) -> RoleRecord:
        definitions = (
            validate_attribute_definitions(changes.attributes)
            if changes.attributes is not None
            else None
        )
        maps = encode_attribute_definitions(definitions) if definitions is not None else None
        now = self._clock()
        with self._session_factory() as session:
            store = RoleStore(session)
            role = store.get_role(role_id)
            if role is None:
                raise RoleNotFoundError("角色不存在")
            if changes.persona is not None:
                role.persona = changes.persona
            if changes.system_prompt is not None:
                role.system_prompt = changes.system_prompt
            if changes.world_book is not None:
                role.world_book = changes.world_book
            if maps is not None:
                self._write_definition_maps(role, maps)
            role.version += 1
            role.updated_at = now
            self._commit(session, "角色更新冲突")
            session.refresh(role)
            return self._record(role, tuple(store.list_reference_world_ids(role.id)))

    def delete_role(self, role_id: int) -> None:
        with self._session_factory() as session:
            store = RoleStore(session)
            role = store.get_role(role_id)
            if role is None:
                raise RoleNotFoundError("角色不存在")
            world_ids = tuple(store.list_reference_world_ids(role.id))
            if world_ids:
                raise RoleReferencedError(world_ids)
            store.delete_role(role)
            self._commit(session, "角色被世界引用时禁止删除")
