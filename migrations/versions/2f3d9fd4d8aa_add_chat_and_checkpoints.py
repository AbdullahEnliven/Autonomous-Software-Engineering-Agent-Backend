"""Add chat messages and project checkpoints

Revision ID: 2f3d9fd4d8aa
Revises: c9b505a13174
Create Date: 2026-04-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2f3d9fd4d8aa"
down_revision: Union[str, Sequence[str], None] = "c9b505a13174"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.TEXT(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "project_checkpoints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("commit_hash", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("project_checkpoints")
    op.drop_table("chat_messages")
