"""全局共享的角色 ORM 模型。"""

from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.attribute import AttributeScalar
from app.db.models import Base


class Role(Base):
    """角色主表拥有基础属性及其完整定义，世界只能保存变化值。"""

    __tablename__ = "role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    persona: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    world_book: Mapped[str] = mapped_column(Text)
    base_values_json: Mapped[dict[str, AttributeScalar]] = mapped_column(JSON)
    attribute_types_json: Mapped[dict[str, str]] = mapped_column(JSON)
    attribute_labels_json: Mapped[dict[str, str]] = mapped_column(JSON)
    attribute_descriptions_json: Mapped[dict[str, str]] = mapped_column(JSON)
    attribute_update_rules_json: Mapped[dict[str, str]] = mapped_column(JSON)
    attribute_constraints_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    attribute_allowed_operations_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    attribute_examples_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
