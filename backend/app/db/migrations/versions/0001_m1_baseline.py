"""M1 基线收编（users + login_log）。

M1 时代用 metadata.create_all 建表（DEVLOG 会话1裁定：M2 收编 alembic）。
已有 M1 库通过 init_db 的 stamp 逻辑标记到此版本，不再重放。

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import func

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column(
            "created_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    op.create_table(
        "login_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.Integer(),
            server_default=func.strftime("%s", "now"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("login_log")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")
