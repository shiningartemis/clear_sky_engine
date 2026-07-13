"""世界、世界角色和位置规则的同步持久化查询。"""

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.character.models import Role
from app.world.models import (
    CharacterLocationCandidate,
    CharacterLocationRule,
    World,
    WorldBranch,
    WorldRoleState,
)


class WorldStore:
    """Store 不拥有业务规则和事务，只操作当前短 Session。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_worlds(self) -> list[World]:
        return list(self._session.scalars(select(World).order_by(World.id)))

    def get_world(self, world_id: int) -> World | None:
        return self._session.get(World, world_id)

    def get_branch(self, branch_id: int) -> WorldBranch | None:
        return self._session.get(WorldBranch, branch_id)

    def get_role(self, role_id: int) -> Role | None:
        return self._session.get(Role, role_id)

    def list_role_states(self, world_id: int) -> list[WorldRoleState]:
        statement = (
            select(WorldRoleState)
            .where(WorldRoleState.world_id == world_id)
            .order_by(WorldRoleState.kind.desc(), WorldRoleState.role_id)
        )
        return list(self._session.scalars(statement))

    def get_role_state(self, world_id: int, role_id: int) -> WorldRoleState | None:
        return self._session.scalar(
            select(WorldRoleState).where(
                WorldRoleState.world_id == world_id,
                WorldRoleState.role_id == role_id,
            )
        )

    def count_npcs(self, world_id: int) -> int:
        count = self._session.scalar(
            select(func.count())
            .select_from(WorldRoleState)
            .where(
                WorldRoleState.world_id == world_id,
                WorldRoleState.kind == "npc",
            )
        )
        return 0 if count is None else count

    def list_reference_world_ids(self, role_id: int) -> tuple[int, ...]:
        statement = (
            select(WorldRoleState.world_id)
            .where(WorldRoleState.role_id == role_id)
            .distinct()
            .order_by(WorldRoleState.world_id)
        )
        return tuple(self._session.scalars(statement))

    def list_location_rules(self, world_id: int, role_id: int) -> list[CharacterLocationRule]:
        statement = (
            select(CharacterLocationRule)
            .where(
                CharacterLocationRule.world_id == world_id,
                CharacterLocationRule.role_id == role_id,
            )
            .order_by(CharacterLocationRule.priority.desc(), CharacterLocationRule.id)
        )
        return list(self._session.scalars(statement))

    def list_candidates(self, rule_id: int) -> list[CharacterLocationCandidate]:
        return list(
            self._session.scalars(
                select(CharacterLocationCandidate)
                .where(CharacterLocationCandidate.rule_id == rule_id)
                .order_by(CharacterLocationCandidate.id)
            )
        )

    def add_all(self, *objects: object) -> None:
        self._session.add_all(objects)

    def flush(self) -> None:
        self._session.flush()

    def delete_world(self, world_id: int) -> None:
        # 环形外键要求先解除活动分支引用，再让数据库级联删除世界私有状态。
        self._session.execute(
            update(World).where(World.id == world_id).values(active_branch_id=None)
        )
        self._session.execute(delete(World).where(World.id == world_id))

    def delete_role_state(self, world_id: int, role_id: int) -> None:
        self._session.execute(
            delete(WorldRoleState).where(
                WorldRoleState.world_id == world_id,
                WorldRoleState.role_id == role_id,
            )
        )

    def delete_location_rules(self, world_id: int, role_id: int) -> None:
        self._session.execute(
            delete(CharacterLocationRule).where(
                CharacterLocationRule.world_id == world_id,
                CharacterLocationRule.role_id == role_id,
            )
        )
