"""stop-list uniqueness per anchor (target_url + anchor_text + donor_url)

Revision ID: b1c2d3e4f5a6
Revises: 09baabb1a688
Create Date: 2026-05-31 22:10:00.000000

Widens the stop-list uniqueness from (target_url, donor_url) to
(target_url, anchor_text, donor_url). This lets the same donor be reused
across different anchors that share a target_url, while still preventing a
donor from repeating within one anchor. Widening a unique constraint never
violates existing rows, so this is safe to apply over real data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "09baabb1a688"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        # SQLite can't ALTER constraints in place — rebuild the table's
        # constraints via batch mode.
        with op.batch_alter_table("stop_list_entries", schema=None) as batch_op:
            batch_op.drop_constraint("uq_stoplist_url_donor", type_="unique")
            batch_op.create_unique_constraint(
                "uq_stoplist_anchor_donor", ["target_url", "anchor_text", "donor_url"]
            )
        op.drop_index("ix_stoplist_target_donor", table_name="stop_list_entries")
        op.create_index(
            "ix_stoplist_target_anchor_donor", "stop_list_entries",
            ["target_url", "anchor_text", "donor_url"], unique=False,
        )
    else:
        op.drop_constraint("uq_stoplist_url_donor", "stop_list_entries", type_="unique")
        op.create_unique_constraint(
            "uq_stoplist_anchor_donor", "stop_list_entries",
            ["target_url", "anchor_text", "donor_url"],
        )
        op.drop_index("ix_stoplist_target_donor", table_name="stop_list_entries")
        op.create_index(
            "ix_stoplist_target_anchor_donor", "stop_list_entries",
            ["target_url", "anchor_text", "donor_url"], unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table("stop_list_entries", schema=None) as batch_op:
            batch_op.drop_constraint("uq_stoplist_anchor_donor", type_="unique")
            batch_op.create_unique_constraint(
                "uq_stoplist_url_donor", ["target_url", "donor_url"]
            )
        op.drop_index("ix_stoplist_target_anchor_donor", table_name="stop_list_entries")
        op.create_index(
            "ix_stoplist_target_donor", "stop_list_entries",
            ["target_url", "donor_url"], unique=False,
        )
    else:
        op.drop_constraint("uq_stoplist_anchor_donor", "stop_list_entries", type_="unique")
        op.create_unique_constraint(
            "uq_stoplist_url_donor", "stop_list_entries", ["target_url", "donor_url"]
        )
        op.drop_index("ix_stoplist_target_anchor_donor", table_name="stop_list_entries")
        op.create_index(
            "ix_stoplist_target_donor", "stop_list_entries",
            ["target_url", "donor_url"], unique=False,
        )
