"""Add vercel integration type

Revision ID: 4f1a7db9c2ef
Revises: 2f3d9fd4d8aa
Create Date: 2026-04-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "4f1a7db9c2ef"
down_revision: Union[str, Sequence[str], None] = "2f3d9fd4d8aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE integrationtype ADD VALUE IF NOT EXISTS 'vercel'")


def downgrade() -> None:
    # PostgreSQL enum value removal is non-trivial and unsafe in downgrade for live systems.
    pass
