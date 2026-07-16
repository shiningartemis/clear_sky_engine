"""建立合并阶段的任务设置、角色记忆与成功轮次结构。"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004_merged_turn_loop"
down_revision: str | None = "0003_phase3_world_roles"
branch_labels: str | None = None
depends_on: str | None = None


LOCATION_CHECK = (
    "location_id IN ('the_home', 'the_dungeon', 'the_mall', 'the_guild', 'the_hotel', 'the_school')"
)


def upgrade() -> None:
    """只持久化应用级任务配置、长期事实和完整成功轮次。"""

    op.drop_column("ai_model", "defaults_json")
    op.create_table(
        "ai_task_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_key", sa.String(length=40), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_effort", sa.String(length=20), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("extra_prompt", sa.Text(), nullable=False),
        sa.Column("structured_output_mode", sa.String(length=20), nullable=False),
        sa.Column("provider_options_json", sa.JSON(), nullable=False),
        sa.Column("memory_target_chars", sa.Integer(), nullable=True),
        sa.Column("memory_max_chars", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "task_key IN ('location_simulation', 'attribute_memory_analysis')",
            name="ck_ai_task_setting_task_key",
        ),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_ai_task_setting_timeout_seconds"),
        sa.CheckConstraint(
            "structured_output_mode IN ('auto', 'native', 'prompt')",
            name="ck_ai_task_setting_structured_output_mode",
        ),
        sa.CheckConstraint("version >= 1", name="ck_ai_task_setting_version"),
        sa.CheckConstraint(
            "(task_key = 'attribute_memory_analysis' "
            "AND memory_target_chars IS NOT NULL AND memory_max_chars IS NOT NULL "
            "AND memory_target_chars >= 1 AND memory_target_chars <= memory_max_chars) "
            "OR (task_key = 'location_simulation' "
            "AND memory_target_chars IS NULL AND memory_max_chars IS NULL)",
            name="ck_ai_task_setting_memory_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["ai_model.id"],
            name="fk_ai_task_setting_model_id_ai_model",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("task_key", name="uq_ai_task_setting_task_key"),
    )
    # 初始配置不可运行，必须由用户分别选择模型；其余空值保留 Provider 的自然默认。
    op.execute(
        sa.text(
            """
            INSERT INTO ai_task_setting (
                task_key, model_id, temperature, max_output_tokens, reasoning_effort,
                timeout_seconds, extra_prompt, structured_output_mode,
                provider_options_json, memory_target_chars, memory_max_chars,
                version, updated_at
            ) VALUES
                (
                    'location_simulation', NULL, NULL, NULL, NULL,
                    120, '', 'auto', '{}', NULL, NULL, 1, CURRENT_TIMESTAMP
                ),
                (
                    'attribute_memory_analysis', NULL, NULL, NULL, NULL,
                    120, '', 'auto', '{}', 20, 50, 1, CURRENT_TIMESTAMP
                )
            """
        )
    )

    op.create_table(
        "world_role_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("world_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("memory", sa.Text(), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("version >= 1", name="ck_world_role_memory_version"),
        sa.ForeignKeyConstraint(
            ["world_id", "role_id"],
            ["world_role_state.world_id", "world_role_state.role_id"],
            name="fk_world_role_memory_world_role_state",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("world_id", "role_id", name="uq_world_role_memory_world_role"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO world_role_memory (
                world_id, role_id, memory, version, created_at, updated_at
            )
            SELECT world_id, role_id, '', 1, created_at, updated_at
            FROM world_role_state
            """
        )
    )

    # 复合引用把 branch_id 与其 world_id 绑定，禁止轮次跨世界挂接分支。
    op.create_index(
        "uq_world_branch_world_id_id",
        "world_branch",
        ["world_id", "id"],
        unique=True,
    )
    op.create_table(
        "turn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("world_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("parent_turn_id", sa.Integer(), nullable=True),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("time_slot", sa.String(length=20), nullable=False),
        sa.Column("player_intent", sa.Text(), nullable=False),
        sa.Column("objective_events_json", sa.JSON(), nullable=False),
        sa.Column("state_after_json", sa.JSON(), nullable=False),
        sa.Column("ai_execution_meta_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("day >= 1", name="ck_turn_day"),
        sa.CheckConstraint(
            "time_slot IN ('morning', 'midday', 'evening', 'night')",
            name="ck_turn_time_slot",
        ),
        sa.ForeignKeyConstraint(
            ["world_id"], ["world.id"], name="fk_turn_world_id_world", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["world_id", "branch_id"],
            ["world_branch.world_id", "world_branch.id"],
            name="fk_turn_world_branch",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_turn_id"],
            ["turn.id"],
            name="fk_turn_parent_turn_id_turn",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["world_id", "branch_id", "parent_turn_id"],
            ["turn.world_id", "turn.branch_id", "turn.id"],
            name="fk_turn_parent_same_branch",
        ),
        sa.UniqueConstraint("world_id", "branch_id", "id", name="uq_turn_world_branch_id"),
    )
    op.create_table(
        "turn_story",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint("sort_order >= 0", name="ck_turn_story_sort_order"),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turn.id"], name="fk_turn_story_turn_id_turn", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["role.id"], name="fk_turn_story_role_id_role", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("turn_id", "role_id", name="uq_turn_story_turn_role"),
    )
    op.create_table(
        "turn_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("location_id", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("fact_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(LOCATION_CHECK, name="ck_turn_event_location"),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turn.id"], name="fk_turn_event_turn_id_turn", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("turn_id", "id", name="uq_turn_event_turn_id_id"),
    )
    op.create_table(
        "turn_event_participant",
        sa.Column("event_id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), primary_key=True),
        sa.Column("knowledge_level", sa.String(length=20), nullable=False),
        sa.Column("perspective_notes", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "knowledge_level IN ('participant', 'observer', 'told', 'public')",
            name="ck_turn_event_participant_knowledge_level",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["turn_event.id"],
            name="fk_turn_event_participant_event_id_turn_event",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["role.id"],
            name="fk_turn_event_participant_role_id_role",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "state_change",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("turn_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column("attribute_key", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("old_value_json", sa.JSON(), nullable=False),
        sa.Column("operand_json", sa.JSON(), nullable=False),
        sa.Column("new_value_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "operation IN ('replace', 'increment', 'decrement')",
            name="ck_state_change_operation",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["turn.id"], name="fk_state_change_turn_id_turn", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["turn_event.id"],
            name="fk_state_change_event_id_turn_event",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id", "event_id"],
            ["turn_event.turn_id", "turn_event.id"],
            name="fk_state_change_event_same_turn",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["role.id"],
            name="fk_state_change_role_id_role",
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    """先删除轮次子表，再恢复阶段 2 的模型默认参数列。"""

    op.drop_table("state_change")
    op.drop_table("turn_event_participant")
    op.drop_table("turn_event")
    op.drop_table("turn_story")
    op.drop_table("turn")
    op.drop_index("uq_world_branch_world_id_id", table_name="world_branch")
    op.drop_table("world_role_memory")
    op.drop_table("ai_task_setting")
    op.add_column(
        "ai_model",
        sa.Column("defaults_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
