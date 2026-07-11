"""AI Provider 与模型目录的 ORM 持久化模型。"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.ai.types import JsonValue


class Base(DeclarativeBase):
    """阶段 2 业务表的 SQLAlchemy 元数据根。"""


class AiProvider(Base):
    """全局 Provider 配置；api_key 绝不直接作为 API DTO 返回。"""

    __tablename__ = "ai_provider"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    provider_type: Mapped[str] = mapped_column(String(40))
    base_url: Mapped[str] = mapped_column(String(2048))
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    extra_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    models: Mapped[list[AiModel]] = relationship(
        back_populates="provider", cascade="all, delete-orphan", passive_deletes=True
    )


class AiModel(Base):
    """Provider 下的远端模型目录，同一远端模型名不得重复。"""

    __tablename__ = "ai_model"
    __table_args__ = (
        UniqueConstraint("provider_id", "remote_model", name="uq_ai_model_provider_remote_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("ai_provider.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(120))
    remote_model: Mapped[str] = mapped_column(String(255))
    capabilities_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    defaults_json: Mapped[dict[str, JsonValue]] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[AiProvider] = relationship(back_populates="models")
