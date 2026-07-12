"""建立阶段 3 世界、角色、动态属性与位置规则结构。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0003_phase3_world_roles"
down_revision: str | None = "0002_ai_providers"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """角色全局共享，变化值与位置规则严格按世界隔离。"""

    op.create_table(
        "role",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("world_book", sa.Text(), nullable=False),
        sa.Column("base_values_json", sa.JSON(), nullable=False),
        sa.Column("attribute_types_json", sa.JSON(), nullable=False),
        sa.Column("attribute_labels_json", sa.JSON(), nullable=False),
        sa.Column("attribute_descriptions_json", sa.JSON(), nullable=False),
        sa.Column("attribute_update_rules_json", sa.JSON(), nullable=False),
        sa.Column("attribute_constraints_json", sa.JSON(), nullable=False),
        sa.Column("attribute_allowed_operations_json", sa.JSON(), nullable=False),
        sa.Column("attribute_examples_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_role_name"),
    )
    op.create_table(
        "world",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("active_branch_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_played_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["active_branch_id"],
            ["world_branch.id"],
            name="fk_world_active_branch_id_world_branch",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "world_branch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("world_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("parent_branch_id", sa.Integer(), nullable=True),
        sa.Column("fork_turn_id", sa.Integer(), nullable=True),
        sa.Column("head_turn_id", sa.Integer(), nullable=True),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("time_slot", sa.String(length=20), nullable=False),
        sa.Column("current_location_id", sa.String(length=40), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("day >= 1", name="ck_world_branch_day"),
        sa.CheckConstraint(
            "time_slot IN ('morning', 'midday', 'evening', 'night')",
            name="ck_world_branch_time_slot",
        ),
        sa.CheckConstraint(
            "current_location_id IN ('the_home', 'the_dungeon', 'the_mall', 'the_guild', "
            "'the_hotel', 'the_school')",
            name="ck_world_branch_current_location",
        ),
        sa.ForeignKeyConstraint(
            ["world_id"],
            ["world.id"],
            name="fk_world_branch_world_id_world",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_branch_id"],
            ["world_branch.id"],
            name="fk_world_branch_parent_branch_id_world_branch",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "world_role_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("world_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("change_values_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('player', 'npc')", name="ck_world_role_state_kind"),
        sa.ForeignKeyConstraint(
            ["world_id"],
            ["world.id"],
            name="fk_world_role_state_world_id_world",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["role.id"],
            name="fk_world_role_state_role_id_role",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("world_id", "role_id", name="uq_world_role_state_world_role"),
    )
    op.create_index(
        "uq_world_role_state_player",
        "world_role_state",
        ["world_id"],
        unique=True,
        sqlite_where=sa.text("kind = 'player'"),
    )
    op.create_table(
        "character_location_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("world_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("weekday_mask", sa.Integer(), nullable=False),
        sa.Column("time_slot", sa.String(length=20), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint("weekday_mask BETWEEN 1 AND 127", name="ck_location_rule_weekday_mask"),
        sa.CheckConstraint("mode IN ('fixed', 'random')", name="ck_location_rule_mode"),
        sa.ForeignKeyConstraint(
            ["world_id", "role_id"],
            ["world_role_state.world_id", "world_role_state.role_id"],
            name="fk_location_rule_world_role_state",
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "character_location_candidate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.String(length=40), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.CheckConstraint("weight > 0", name="ck_location_candidate_weight"),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["character_location_rule.id"],
            name="fk_location_candidate_rule_id_location_rule",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("rule_id", "location_id", name="uq_location_candidate_rule_location"),
    )


def downgrade() -> None:
    """严格按子表优先顺序删除，避免留下悬空外键。"""

    op.drop_table("character_location_candidate")
    op.drop_table("character_location_rule")
    op.drop_index("uq_world_role_state_player", table_name="world_role_state")
    op.drop_table("world_role_state")
    # world 与 world_branch 形成环；先解除活动分支引用，避免启用外键时无法降级。
    op.execute(sa.text("UPDATE world SET active_branch_id = NULL"))
    op.drop_table("world_branch")
    op.drop_table("world")
    op.drop_table("role")
