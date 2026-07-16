"""只保存完整成功轮次的 ORM 模型。"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.ai.types import JsonValue
from app.db.models import Base


class Turn(Base):
    """完整结算后的不可变轮次；失败和中间运行绝不写入。"""

    __tablename__ = "turn"
    __table_args__ = (
        CheckConstraint("day >= 1", name="ck_turn_day"),
        CheckConstraint(
            "time_slot IN ('morning', 'midday', 'evening', 'night')",
            name="ck_turn_time_slot",
        ),
        ForeignKeyConstraint(
            ["world_id", "branch_id"],
            ["world_branch.world_id", "world_branch.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["world_id", "branch_id", "parent_turn_id"],
            ["turn.world_id", "turn.branch_id", "turn.id"],
        ),
        UniqueConstraint("world_id", "branch_id", "id", name="uq_turn_world_branch_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    world_id: Mapped[int] = mapped_column(ForeignKey("world.id", ondelete="CASCADE"))
    branch_id: Mapped[int] = mapped_column(Integer)
    parent_turn_id: Mapped[int | None] = mapped_column(
        ForeignKey("turn.id", ondelete="SET NULL"), nullable=True
    )
    day: Mapped[int] = mapped_column(Integer)
    time_slot: Mapped[str] = mapped_column(String(20))
    player_intent: Mapped[str] = mapped_column(Text)
    objective_events_json: Mapped[list[JsonValue]] = mapped_column(JSON)
    state_after_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    ai_execution_meta_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TurnStory(Base):
    """每个已定位角色每轮恰有一篇独立纪事。"""

    __tablename__ = "turn_story"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="ck_turn_story_sort_order"),
        UniqueConstraint("turn_id", "role_id", name="uq_turn_story_turn_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    turn_id: Mapped[int] = mapped_column(ForeignKey("turn.id", ondelete="CASCADE"))
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="RESTRICT"))
    content: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer)


class TurnEvent(Base):
    """程序校验并接受的地图内客观事件。"""

    __tablename__ = "turn_event"
    __table_args__ = (
        CheckConstraint(
            "location_id IN ('the_home', 'the_dungeon', 'the_mall', 'the_guild', "
            "'the_hotel', 'the_school')",
            name="ck_turn_event_location",
        ),
        UniqueConstraint("turn_id", "id", name="uq_turn_event_turn_id_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    turn_id: Mapped[int] = mapped_column(ForeignKey("turn.id", ondelete="CASCADE"))
    location_id: Mapped[str] = mapped_column(String(40))
    event_type: Mapped[str] = mapped_column(String(80))
    fact_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TurnEventParticipant(Base):
    """事件知识按角色持久化，后续上下文只能据此过滤。"""

    __tablename__ = "turn_event_participant"
    __table_args__ = (
        CheckConstraint(
            "knowledge_level IN ('participant', 'observer', 'told', 'public')",
            name="ck_turn_event_participant_knowledge_level",
        ),
    )

    event_id: Mapped[int] = mapped_column(
        ForeignKey("turn_event.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("role.id", ondelete="RESTRICT"), primary_key=True
    )
    knowledge_level: Mapped[str] = mapped_column(String(20))
    perspective_notes: Mapped[str] = mapped_column(Text)


class StateChange(Base):
    """记录通用属性函数已应用的旧值、操作数与最终值。"""

    __tablename__ = "state_change"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('replace', 'increment', 'decrement')",
            name="ck_state_change_operation",
        ),
        ForeignKeyConstraint(
            ["turn_id", "event_id"],
            ["turn_event.turn_id", "turn_event.id"],
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    turn_id: Mapped[int] = mapped_column(ForeignKey("turn.id", ondelete="CASCADE"))
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("turn_event.id", ondelete="SET NULL"), nullable=True
    )
    role_id: Mapped[int] = mapped_column(ForeignKey("role.id", ondelete="RESTRICT"))
    attribute_key: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(20))
    old_value_json: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    operand_json: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    new_value_json: Mapped[JsonValue] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text)
