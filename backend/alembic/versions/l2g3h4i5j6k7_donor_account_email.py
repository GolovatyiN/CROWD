"""donor_accounts.email_account_id — link per-donor accounts to the mailbox pool

Revision ID: l2g3h4i5j6k7
Revises: k1f2g3h4i5j6
Create Date: 2026-08-03 00:00:00.000000

Connects EmailAccount (shared mailbox pool) ↔ DonorAccount (which account is used
on which donor), so we can see which mailbox served which donor, reuse it on
repeat placements, and build per-employee stats. Additive; back-fills existing
donor-accounts to the pool mailbox whose email matches login_email.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l2g3h4i5j6k7"
down_revision: Union[str, None] = "k1f2g3h4i5j6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("donor_accounts", sa.Column("email_account_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_donor_accounts_email_account_id"), "donor_accounts", ["email_account_id"], unique=False)

    # Back-fill: link to the pool mailbox with a matching email (case-insensitive).
    op.execute(
        "UPDATE donor_accounts SET email_account_id = ("
        "  SELECT ea.id FROM email_accounts ea"
        "  WHERE lower(ea.email) = lower(donor_accounts.login_email) LIMIT 1"
        ") WHERE login_email IS NOT NULL AND login_email <> ''"
    )

    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_donor_accounts_email_account", "donor_accounts", "email_accounts",
            ["email_account_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_donor_accounts_email_account", "donor_accounts", type_="foreignkey")
    op.drop_index(op.f("ix_donor_accounts_email_account_id"), table_name="donor_accounts")
    op.drop_column("donor_accounts", "email_account_id")
