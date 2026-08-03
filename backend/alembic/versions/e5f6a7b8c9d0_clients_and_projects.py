"""clients, client_projects, client_project_members + client FK columns

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-03 00:00:00.000000

Phase 2 of the internal/client split. Adds the Client / ClientProject entities
and links client anchor-plans / placements to a project. All FK columns are
nullable — existing (internal) rows stay untouched. FK constraints on the
pre-existing tables are added only on Postgres (SQLite can't ALTER-ADD a FK);
the ORM models declare the relationships so fresh create_all DBs get them too.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column) FK additions on existing tables → client_projects.id (client_id → clients.id)
FK_COLS = [
    ("anchor_plans", "client_project_id", "client_projects"),
    ("anchor_plan_items", "client_project_id", "client_projects"),
    ("placements", "client_project_id", "client_projects"),
    ("placements", "client_id", "clients"),
]


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("contact_info", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("manager_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_clients_status", "clients", ["status"])
    op.create_index("ix_clients_manager_id", "clients", ["manager_id"])

    op.create_table(
        "client_projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("promoted_domain", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("geo", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("language", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("donor_requirements", sa.Text(), nullable=False, server_default=""),
        sa.Column("planned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("manager_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_client_projects_client_id", "client_projects", ["client_id"])
    op.create_index("ix_client_projects_status", "client_projects", ["status"])

    op.create_table(
        "client_project_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_project_id", sa.Integer(), sa.ForeignKey("client_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("client_project_id", "user_id", name="uq_project_member"),
    )

    is_sqlite = op.get_bind().dialect.name == "sqlite"
    for table, col, _target in FK_COLS:
        op.add_column(table, sa.Column(col, sa.Integer(), nullable=True))
        op.create_index(f"ix_{table}_{col}", table, [col])
    if not is_sqlite:
        for table, col, target in FK_COLS:
            op.create_foreign_key(f"fk_{table}_{col}", table, target, [col], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    is_sqlite = op.get_bind().dialect.name == "sqlite"
    for table, col, _target in FK_COLS:
        if not is_sqlite:
            op.drop_constraint(f"fk_{table}_{col}", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_{col}", table_name=table)
        op.drop_column(table, col)
    op.drop_table("client_project_members")
    op.drop_index("ix_client_projects_status", table_name="client_projects")
    op.drop_index("ix_client_projects_client_id", table_name="client_projects")
    op.drop_table("client_projects")
    op.drop_index("ix_clients_manager_id", table_name="clients")
    op.drop_index("ix_clients_status", table_name="clients")
    op.drop_table("clients")
