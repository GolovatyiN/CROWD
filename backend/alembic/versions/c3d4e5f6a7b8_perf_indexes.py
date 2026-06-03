"""perf: composite indexes for anchor_plan_items aggregations

Revision ID: c3d4e5f6a7b8
Revises: b1c2d3e4f5a6
Create Date: 2026-06-04 00:00:00.000000

anchor_plan_items is the largest table (10k+ rows). Two hot access patterns
scan it:
  * per-plan status counts (dashboard + plan list) — GROUP BY (anchor_plan_id,
    status);
  * the my-tasks view — WHERE assigned_to = ? AND status = ?.
Single-column indexes already exist on each field, but composite indexes let
Postgres satisfy these as index-only scans instead of scanning the heap.
Creating an index on ~10k rows is near-instant, so no CONCURRENTLY needed.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_api_plan_status", "anchor_plan_items",
        ["anchor_plan_id", "status"], unique=False,
    )
    op.create_index(
        "ix_api_assigned_status", "anchor_plan_items",
        ["assigned_to", "status"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_api_assigned_status", table_name="anchor_plan_items")
    op.drop_index("ix_api_plan_status", table_name="anchor_plan_items")
