"""add kind (internal/client) to plans, items, placements, stop-list

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-03 00:00:00.000000

Phase 1 of the internal/client split. Adds a `kind` discriminator that defaults
to 'internal', so every existing row becomes "Наши" and nothing changes
behaviourally. `kind` is denormalised onto items/placements/stop-list (inherited
from the plan) so filtering and stats are cheap and the type is explicit on each
entity.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = ["anchor_plans", "anchor_plan_items", "placements", "stop_list_entries"]


def upgrade() -> None:
    for t in TABLES:
        op.add_column(
            t,
            sa.Column("kind", sa.String(length=16), nullable=False, server_default="internal"),
        )
        op.create_index(f"ix_{t}_kind", t, ["kind"], unique=False)


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_index(f"ix_{t}_kind", table_name=t)
        op.drop_column(t, "kind")
