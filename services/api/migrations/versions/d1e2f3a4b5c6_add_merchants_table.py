"""add merchants table

Revision ID: d1e2f3a4b5c6
Revises: c0a7b1d9e3f2
Create Date: 2026-06-11 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c0a7b1d9e3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'merchants',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('short_code', sa.String(), nullable=False),
        sa.Column('settlement_msisdn', sa.String(), nullable=False),
        sa.Column('settlement_provider', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('short_code'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('merchants')
