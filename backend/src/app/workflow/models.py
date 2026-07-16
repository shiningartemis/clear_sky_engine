"""应用级固定 AI 任务配置 ORM 模型。"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.ai.types import JsonValue
from app.db.models import Base


class AiTaskSetting(Base):
    """两个全局任务各占一行，世界不得复制或覆盖任务参数。"""

    __tablename__ = "ai_task_setting"
    __table_args__ = (
        CheckConstraint(
            "task_key IN ('location_simulation', 'attribute_memory_analysis')",
            name="ck_ai_task_setting_task_key",
        ),
        CheckConstraint("timeout_seconds > 0", name="ck_ai_task_setting_timeout_seconds"),
        CheckConstraint(
            "structured_output_mode IN ('auto', 'native', 'prompt')",
            name="ck_ai_task_setting_structured_output_mode",
        ),
        CheckConstraint("version >= 1", name="ck_ai_task_setting_version"),
        CheckConstraint(
            "(task_key = 'attribute_memory_analysis' "
            "AND memory_target_chars IS NOT NULL AND memory_max_chars IS NOT NULL "
            "AND memory_target_chars >= 1 AND memory_target_chars <= memory_max_chars) "
            "OR (task_key = 'location_simulation' "
            "AND memory_target_chars IS NULL AND memory_max_chars IS NULL)",
            name="ck_ai_task_setting_memory_bounds",
        ),
        UniqueConstraint("task_key", name="uq_ai_task_setting_task_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_key: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_model.id", ondelete="RESTRICT"), nullable=True
    )
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    extra_prompt: Mapped[str] = mapped_column(Text)
    structured_output_mode: Mapped[str] = mapped_column(String(20))
    provider_options_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    memory_target_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_max_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
