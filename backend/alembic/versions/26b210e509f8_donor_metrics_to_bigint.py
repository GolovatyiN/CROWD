"""donor metrics to bigint

Revision ID: 26b210e509f8
Revises: 8f9091f9a055
Create Date: 2026-05-28 18:39:55.402050

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '26b210e509f8'
down_revision: Union[str, None] = '8f9091f9a055'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite stores INTEGER as a 64-bit affinity already and doesn't support
    # ALTER COLUMN TYPE. Only run on real databases (Postgres in prod).
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.alter_column('donors', 'organic_traffic',
               existing_type=sa.INTEGER(), type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column('donors', 'ref_domains',
               existing_type=sa.INTEGER(), type_=sa.BigInteger(), existing_nullable=False)
    op.alter_column('donors', 'backlinks',
               existing_type=sa.INTEGER(), type_=sa.BigInteger(), existing_nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    op.alter_column('donors', 'backlinks',
               existing_type=sa.BigInteger(), type_=sa.INTEGER(), existing_nullable=False)
    op.alter_column('donors', 'ref_domains',
               existing_type=sa.BigInteger(), type_=sa.INTEGER(), existing_nullable=False)
    op.alter_column('donors', 'organic_traffic',
               existing_type=sa.BigInteger(), type_=sa.INTEGER(), existing_nullable=False)
