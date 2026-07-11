"""建立全局 AI Provider 与模型目录。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ai_providers"
down_revision: str | None = "0001_initial"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """配置全局共享，密钥只保存在 Provider 表且允许为空。"""

    op.create_table(
        "ai_provider",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provider_type", sa.String(length=40), nullable=False),
        sa.Column("base_url", sa.String(length=2048), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("extra_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "provider_type IN ('openai_compatible', 'deepseek')",
            name="ck_ai_provider_provider_type",
        ),
        sa.UniqueConstraint("name", name="uq_ai_provider_name"),
    )
    op.create_table(
        "ai_model",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("remote_model", sa.String(length=255), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("defaults_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["ai_provider.id"],
            name="fk_ai_model_provider_id_ai_provider",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "provider_id", "remote_model", name="uq_ai_model_provider_remote_model"
        ),
    )


def downgrade() -> None:
    """先删除子表，保持外键降级顺序正确。"""

    op.drop_table("ai_model")
    op.drop_table("ai_provider")
