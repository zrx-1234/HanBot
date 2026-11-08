"""M2 全部建表（design §4.3-§4.13，claude-code-lessons 缺口#1/#2）。

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "llm_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("base_url", sa.String(length=256), nullable=False),
        sa.Column("api_key_encrypted", sa.String(length=512), nullable=False),
        sa.Column("models", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("cooldown_until", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_sources_name"), "llm_sources", ["name"], unique=True)
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.Column("dir_path", sa.String(length=512), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sessions_uuid"), "sessions", ["uuid"], unique=True)
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_uuid", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_session_uuid"), "messages", ["session_uuid"], unique=False)
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("session_uuid", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.Column("started_at", sa.Integer(), nullable=True),
        sa.Column("ended_at", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_estimate", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_uuid"), "tasks", ["uuid"], unique=True)
    op.create_index(op.f("ix_tasks_session_uuid"), "tasks", ["session_uuid"], unique=False)
    op.create_table(
        "task_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_uuid", sa.String(length=36), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_steps_task_uuid"), "task_steps", ["task_uuid"], unique=False)
    op.create_table(
        "abilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("desc", sa.String(length=512), nullable=True),
        sa.Column("install_path", sa.String(length=512), nullable=False),
        sa.Column("global_active", sa.Boolean(), nullable=False),
        sa.Column(
            "installed_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_abilities_uuid"), "abilities", ["uuid"], unique=True)
    op.create_table(
        "memories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("layer", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_task_uuid", sa.String(length=36), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_memories_uuid"), "memories", ["uuid"], unique=True)
    op.create_table(
        "usage_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_uuid", sa.String(length=36), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_creation_tokens", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_usage_log_task_uuid"), "usage_log", ["task_uuid"], unique=False)
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_uuid", sa.String(length=36), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notifications_task_uuid"), "notifications", ["task_uuid"], unique=False
    )
    op.create_table(
        "credentials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("site", sa.String(length=256), nullable=True),
        sa.Column("secret_encrypted", sa.String(length=512), nullable=False),
        sa.Column("note", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_credentials_name"), "credentials", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_credentials_name"), table_name="credentials")
    op.drop_table("credentials")
    op.drop_index(op.f("ix_notifications_task_uuid"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(op.f("ix_usage_log_task_uuid"), table_name="usage_log")
    op.drop_table("usage_log")
    op.drop_index(op.f("ix_memories_uuid"), table_name="memories")
    op.drop_table("memories")
    op.drop_index(op.f("ix_abilities_uuid"), table_name="abilities")
    op.drop_table("abilities")
    op.drop_index(op.f("ix_task_steps_task_uuid"), table_name="task_steps")
    op.drop_table("task_steps")
    op.drop_index(op.f("ix_tasks_session_uuid"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_uuid"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_messages_session_uuid"), table_name="messages")
    op.drop_table("messages")
    op.drop_index(op.f("ix_sessions_uuid"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_llm_sources_name"), table_name="llm_sources")
    op.drop_table("llm_sources")
    op.drop_table("settings")
