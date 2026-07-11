"""建立初始数据库版本。"""

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """阶段 1 尚无业务表，仅建立可追踪的 schema head。"""


def downgrade() -> None:
    """初始空版本无需删除业务对象。"""
