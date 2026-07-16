"""按世界隔离的阶段 3 ORM 模型。"""

from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class World(Base):
    __tablename__ = "world"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    active_branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_branch.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorldBranch(Base):
    __tablename__ = "world_branch"
    __table_args__ = (Index("uq_world_branch_world_id_id", "world_id", "id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("world.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    parent_branch_id: Mapped[int | None] = mapped_column(
        ForeignKey("world_branch.id", ondelete="RESTRICT"), nullable=True
    )
    fork_turn_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    head_turn_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day: Mapped[int] = mapped_column(Integer)
    time_slot: Mapped[str] = mapped_column(String(20))
    current_location_id: Mapped[str] = mapped_column(String(40))
    state_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorldRoleState(Base):
    """阶段 3 的变化值按世界隔离；角色在同一世界只能出现一次。"""

    __tablename__ = "world_role_state"
    __table_args__ = (
        UniqueConstraint("world_id", "role_id", name="uq_world_role_state_world_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("world.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean)
    change_values_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorldRoleMemory(Base):
    """长期记忆严格按世界和角色唯一，并随世界角色级联删除。"""

    __tablename__ = "world_role_memory"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_world_role_memory_version"),
        ForeignKeyConstraint(
            ["world_id", "role_id"],
            ["world_role_state.world_id", "world_role_state.role_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("world_id", "role_id", name="uq_world_role_memory_world_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[int] = mapped_column(Integer)
    role_id: Mapped[int] = mapped_column(Integer)
    memory: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CharacterLocationRule(Base):
    """复合外键阻止位置规则跨世界引用同一角色。"""

    __tablename__ = "character_location_rule"
    __table_args__ = (
        ForeignKeyConstraint(
            ["world_id", "role_id"],
            ["world_role_state.world_id", "world_role_state.role_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[int] = mapped_column(Integer)
    role_id: Mapped[int] = mapped_column(Integer)
    weekday_mask: Mapped[int] = mapped_column(Integer)
    time_slot: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(20))
    priority: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean)


class CharacterLocationCandidate(Base):
    __tablename__ = "character_location_candidate"
    __table_args__ = (
        UniqueConstraint("rule_id", "location_id", name="uq_location_candidate_rule_location"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("character_location_rule.id", ondelete="CASCADE")
    )
    location_id: Mapped[str] = mapped_column(String(40))
    weight: Mapped[int] = mapped_column(Integer)
