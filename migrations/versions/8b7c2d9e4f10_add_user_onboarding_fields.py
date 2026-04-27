"""Add user onboarding fields

Revision ID: 8b7c2d9e4f10
Revises: 4f1a7db9c2ef
Create Date: 2026-04-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8b7c2d9e4f10"
down_revision: Union[str, Sequence[str], None] = "4f1a7db9c2ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("company_name", sa.String(), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(), nullable=True))
    op.add_column("users", sa.Column("website", sa.String(), nullable=True))
    op.add_column("users", sa.Column("country", sa.String(), nullable=True))
    op.add_column("users", sa.Column("industry", sa.String(), nullable=True))
    op.add_column("users", sa.Column("company_size", sa.String(), nullable=True))
    op.add_column("users", sa.Column("primary_goal", sa.String(), nullable=True))
    op.add_column("users", sa.Column("store_stage", sa.String(), nullable=True))
    op.add_column("users", sa.Column("monthly_revenue", sa.String(), nullable=True))
    op.add_column("users", sa.Column("referral_source", sa.String(), nullable=True))
    op.add_column("users", sa.Column("onboarding_completed", sa.Boolean(), nullable=True, server_default=sa.false()))
    op.execute("UPDATE users SET onboarding_completed = false WHERE onboarding_completed IS NULL")


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed")
    op.drop_column("users", "referral_source")
    op.drop_column("users", "monthly_revenue")
    op.drop_column("users", "store_stage")
    op.drop_column("users", "primary_goal")
    op.drop_column("users", "company_size")
    op.drop_column("users", "industry")
    op.drop_column("users", "country")
    op.drop_column("users", "website")
    op.drop_column("users", "phone")
    op.drop_column("users", "role")
    op.drop_column("users", "company_name")
