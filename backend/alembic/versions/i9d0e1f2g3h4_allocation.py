"""allocation_settings (internal/client work split)

Revision ID: i9d0e1f2g3h4
Revises: h8c9d0e1f2g3
Create Date: 2026-08-03 00:00:00.000000

Phase 4. Global + per-employee internal/client ratio and daily/monthly targets.
Additive.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i9d0e1f2g3h4"
down_revision: Union[str, None] = "h8c9d0e1f2g3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "allocation_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="global"),  # global|employee
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("internal_pct", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("client_pct", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("daily_target", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("monthly_target", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_allocation_scope_user", "allocation_settings", ["scope", "user_id"], unique=True)


def downgrade() -> None:
    op.drop_table("allocation_settings")
