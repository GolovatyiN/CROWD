"""stop_list_entries: hierarchy + scoping metadata (client/project/level/source)

Revision ID: k1f2g3h4i5j6
Revises: j0e1f2g3h4i5
Create Date: 2026-08-03 00:00:00.000000

Phase B1 (Раздел 4A.8–4A.11). Adds the columns that let a stop-list entry live
at a level (global/internal/client/project/campaign) and carry client/project
scope, a match scope, a reason, a source and an active/inactive status.

Fully additive + backward compatible: existing rows are back-filled with
scope='anchor' (today's exact target_url+anchor matching), source='historical',
status='active', and level derived from the existing `kind`. client_id /
client_project_id stay NULL for legacy rows — the matcher treats a NULL-scoped
entry as global (matched by target_url), so nothing changes for old data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k1f2g3h4i5j6"
down_revision: Union[str, None] = "j0e1f2g3h4i5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stop_list_entries", sa.Column("client_id", sa.Integer(), nullable=True))
    op.add_column("stop_list_entries", sa.Column("client_project_id", sa.Integer(), nullable=True))
    op.add_column("stop_list_entries", sa.Column("level", sa.String(length=16), nullable=False, server_default="internal"))
    op.add_column("stop_list_entries", sa.Column("scope", sa.String(length=24), nullable=False, server_default="anchor"))
    op.add_column("stop_list_entries", sa.Column("reason", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("stop_list_entries", sa.Column("source", sa.String(length=24), nullable=False, server_default="manual"))
    op.add_column("stop_list_entries", sa.Column("status", sa.String(length=16), nullable=False, server_default="active"))

    op.create_index(op.f("ix_stop_list_entries_client_id"), "stop_list_entries", ["client_id"], unique=False)
    op.create_index(op.f("ix_stop_list_entries_client_project_id"), "stop_list_entries", ["client_project_id"], unique=False)
    op.create_index(op.f("ix_stop_list_entries_level"), "stop_list_entries", ["level"], unique=False)
    op.create_index(op.f("ix_stop_list_entries_status"), "stop_list_entries", ["status"], unique=False)

    # Back-fill: level from kind; legacy rows are historical.
    op.execute("UPDATE stop_list_entries SET level = kind WHERE level = 'internal'")
    op.execute("UPDATE stop_list_entries SET source = 'historical'")

    # NOTE: deliberately NO database-level foreign keys on client_id /
    # client_project_id. `ALTER TABLE ADD CONSTRAINT ... FOREIGN KEY` takes an
    # ACCESS EXCLUSIVE lock and validates the whole table — on the large
    # stop_list_entries table that stalled prod behind a lock queue. The app
    # doesn't rely on DB-level FK enforcement here (the SQLite path never had
    # it), so the columns stay plain indexed integers.


def downgrade() -> None:
    op.drop_index(op.f("ix_stop_list_entries_status"), table_name="stop_list_entries")
    op.drop_index(op.f("ix_stop_list_entries_level"), table_name="stop_list_entries")
    op.drop_index(op.f("ix_stop_list_entries_client_project_id"), table_name="stop_list_entries")
    op.drop_index(op.f("ix_stop_list_entries_client_id"), table_name="stop_list_entries")
    for col in ("status", "source", "reason", "scope", "level", "client_project_id", "client_id"):
        op.drop_column("stop_list_entries", col)
