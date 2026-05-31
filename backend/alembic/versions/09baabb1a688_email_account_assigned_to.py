"""email_account assigned_to

Revision ID: 09baabb1a688
Revises: d7505871596b
Create Date: 2026-05-31 21:32:29.411873

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "09baabb1a688"
down_revision: Union[str, None] = "d7505871596b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("email_accounts", sa.Column("assigned_to", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_email_accounts_assigned_to"), "email_accounts", ["assigned_to"], unique=False)
    # SQLite can't ALTER TABLE ADD a named FK — skip it there (column + index
    # still work; FK enforcement isn't required for the app to function).
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_email_accounts_assigned_to_users",
            "email_accounts", "users", ["assigned_to"], ["id"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_email_accounts_assigned_to_users", "email_accounts", type_="foreignkey")
    op.drop_index(op.f("ix_email_accounts_assigned_to"), table_name="email_accounts")
    op.drop_column("email_accounts", "assigned_to")
