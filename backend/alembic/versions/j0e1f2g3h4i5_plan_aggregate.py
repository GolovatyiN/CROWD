"""anchor_plan_items: aggregate model (required/reserved/used counts, buckets)

Revision ID: j0e1f2g3h4i5
Revises: i9d0e1f2g3h4
Create Date: 2026-08-03 00:00:00.000000

Phase A. "Формат 2" (анкор + количество): a plan item can be a *bucket*
(required_count > 1) that lazily spawns child unit-items instead of creating
tens of thousands of identical rows. Fully additive + backward compatible:
existing rows get required_count=1, and already-placed items are back-filled
to used_count=1 so aggregate progress stays correct.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j0e1f2g3h4i5"
down_revision: Union[str, None] = "i9d0e1f2g3h4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("anchor_plan_items", sa.Column("required_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("anchor_plan_items", sa.Column("reserved_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("anchor_plan_items", sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("anchor_plan_items", sa.Column("parent_item_id", sa.Integer(), nullable=True))
    op.add_column("anchor_plan_items", sa.Column("anchor_type", sa.String(length=32), nullable=False, server_default=""))
    op.add_column("anchor_plan_items", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))

    op.create_index(op.f("ix_anchor_plan_items_parent_item_id"), "anchor_plan_items", ["parent_item_id"], unique=False)
    op.create_index(op.f("ix_anchor_plan_items_priority"), "anchor_plan_items", ["priority"], unique=False)

    # Back-fill: existing completed items count as one used unit each, so the
    # aggregate "done" (SUM(used_count) over top-level items) matches reality.
    op.execute("UPDATE anchor_plan_items SET used_count = 1 WHERE status IN ('placed', 'done')")

    # SQLite can't ALTER TABLE ADD a named FK — skip it there (column + index
    # still work; FK enforcement isn't required for the app to function).
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_anchor_plan_items_parent_item",
            "anchor_plan_items", "anchor_plan_items",
            ["parent_item_id"], ["id"], ondelete="CASCADE",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_anchor_plan_items_parent_item", "anchor_plan_items", type_="foreignkey")
    op.drop_index(op.f("ix_anchor_plan_items_priority"), table_name="anchor_plan_items")
    op.drop_index(op.f("ix_anchor_plan_items_parent_item_id"), table_name="anchor_plan_items")
    op.drop_column("anchor_plan_items", "priority")
    op.drop_column("anchor_plan_items", "anchor_type")
    op.drop_column("anchor_plan_items", "parent_item_id")
    op.drop_column("anchor_plan_items", "used_count")
    op.drop_column("anchor_plan_items", "reserved_count")
    op.drop_column("anchor_plan_items", "required_count")
