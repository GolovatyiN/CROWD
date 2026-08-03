"""users.client_id for the 'client' role

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-03 00:00:00.000000

Phase 3. A user with role='client' belongs to exactly one Client and can only
see that client's data. Nullable — all existing internal users keep client_id
NULL. FK constraint added on Postgres only (SQLite can't ALTER-ADD a FK).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("client_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_client_id", "users", ["client_id"])
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key("fk_users_client_id", "users", "clients", ["client_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_users_client_id", "users", type_="foreignkey")
    op.drop_index("ix_users_client_id", table_name="users")
    op.drop_column("users", "client_id")
