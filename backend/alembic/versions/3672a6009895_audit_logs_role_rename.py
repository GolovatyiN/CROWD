"""audit_logs + role rename

Revision ID: 3672a6009895
Revises: 26b210e509f8
Create Date: 2026-05-29 17:08:31.715939

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3672a6009895"
down_revision: Union[str, None] = "26b210e509f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Audit log table
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("target_label", sa.String(length=255), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_logs_target_id"), "audit_logs", ["target_id"], unique=False)

    # 2. Role rename. The earlier MVP used 'employee'; the new RBAC names it
    #    'user' to match the 3-tier model (user / admin / super_admin).
    op.execute("UPDATE users SET role='user' WHERE role='employee'")

    # 3. Promote the bootstrap admin account to super_admin if it's still
    #    on the old 'admin' role. This guarantees there's at least one
    #    super-admin who can manage users after the migration.
    op.execute("UPDATE users SET role='super_admin' WHERE email='admin@crowd.local' AND role='admin'")


def downgrade() -> None:
    # Roll back the role rename — best effort, only restores 'employee' from
    # rows that were 'user'; can't distinguish original super_admins.
    op.execute("UPDATE users SET role='employee' WHERE role='user'")
    op.drop_index(op.f("ix_audit_logs_target_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_actor_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")
