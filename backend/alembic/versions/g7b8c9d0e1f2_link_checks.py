"""link_checks + link_check_results (ready-link verification)

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-03 00:00:00.000000

Phase 5. Per-placement current state + queue (link_checks, unique per placement)
and append-only history (link_check_results). Additive — nothing existing changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "link_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("placement_id", sa.Integer(), sa.ForeignKey("placements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="internal"),
        sa.Column("expected_url", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("expected_anchor", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("expected_link_type", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("final_url", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("found_anchor", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("is_dofollow", sa.Boolean(), nullable=True),
        sa.Column("error_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_checked_at", sa.DateTime(), nullable=True),
        sa.Column("next_check_at", sa.DateTime(), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_link_checks_placement_id", "link_checks", ["placement_id"], unique=True)
    op.create_index("ix_link_checks_status", "link_checks", ["status"])
    op.create_index("ix_link_checks_kind", "link_checks", ["kind"])
    op.create_index("ix_link_checks_next_check_at", "link_checks", ["next_check_at"])
    op.create_index("ix_link_checks_priority", "link_checks", ["priority"])
    op.create_index("ix_link_checks_status_next", "link_checks", ["status", "next_check_at"])

    op.create_table(
        "link_check_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("placement_id", sa.Integer(), sa.ForeignKey("placements.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_check_id", sa.Integer(), sa.ForeignKey("link_checks.id", ondelete="CASCADE"), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("found_url", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("found_anchor", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("expected_url", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("expected_anchor", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("final_url", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("is_dofollow", sa.Boolean(), nullable=True),
        sa.Column("redirect_chain", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_link_check_results_placement_id", "link_check_results", ["placement_id"])
    op.create_index("ix_link_check_results_link_check_id", "link_check_results", ["link_check_id"])
    op.create_index("ix_link_check_results_checked_at", "link_check_results", ["checked_at"])
    op.create_index("ix_link_check_results_status", "link_check_results", ["status"])


def downgrade() -> None:
    op.drop_table("link_check_results")
    op.drop_table("link_checks")
