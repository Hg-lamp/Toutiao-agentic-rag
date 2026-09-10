"""add memory table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-09 21:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False, comment="记忆主键"),
        sa.Column(
            "user_id",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            comment="所属用户",
        ),
        sa.Column("memory_key", sa.String(length=100), nullable=False, comment="记忆键"),
        sa.Column("memory_value", sa.Text(), nullable=False, comment="记忆内容"),
        sa.Column("memory_type", sa.String(length=30), nullable=False, server_default="fact", comment="记忆类型"),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="assistant", comment="记忆来源"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1", comment="置信度"),
        sa.Column("is_active", mysql.TINYINT(), nullable=False, server_default="1", comment="是否有效"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"), comment="更新时间"),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True, comment="最后读取时间"),
        sa.Column("expires_at", sa.DateTime(), nullable=True, comment="过期时间"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_memory_user", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "memory_key", name="uq_memory_user_key"),
        comment="用户长期记忆表",
        mysql_collate="utf8mb4_unicode_ci",
        mysql_default_charset="utf8mb4",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "idx_memory_user_active",
        "memory",
        ["user_id", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_memory_user_active", table_name="memory")
    op.drop_table("memory")
