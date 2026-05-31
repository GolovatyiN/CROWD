"""email_accounts

Revision ID: d7505871596b
Revises: 3672a6009895
Create Date: 2026-05-31 02:37:30.144764

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7505871596b"
down_revision: Union[str, None] = "3672a6009895"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_email_accounts_email"), "email_accounts", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_accounts_email"), table_name="email_accounts")
    op.drop_table("email_accounts")
