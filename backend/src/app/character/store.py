"""全局角色库的同步数据库查询。"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.character.models import Role
from app.world.models import WorldRoleState


class RoleStore:
    """Store 只封装角色持久化，不拥有业务规则或事务。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_roles(self) -> list[Role]:
        return list(self._session.scalars(select(Role).order_by(Role.id)))

    def get_role(self, role_id: int) -> Role | None:
        return self._session.get(Role, role_id)

    def get_role_by_name(self, name: str) -> Role | None:
        return self._session.scalar(select(Role).where(Role.name == name))

    def list_reference_world_ids(self, role_id: int) -> list[int]:
        statement = (
            select(WorldRoleState.world_id)
            .where(WorldRoleState.role_id == role_id)
            .distinct()
            .order_by(WorldRoleState.world_id)
        )
        return list(self._session.scalars(statement))

    def add_role(self, role: Role) -> None:
        self._session.add(role)

    def delete_role(self, role: Role) -> None:
        # 显式按主键删除，避免为无关系配置的 ORM 对象引入级联语义。
        self._session.execute(delete(Role).where(Role.id == role.id))
