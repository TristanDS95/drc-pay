"""add operator_till to merchants

Adds the merchant's own operator "buy goods" till on their settlement network — what an on-net
(same-network) customer pays directly. Optional (nullable): merchants without a till fall back to
send-to-number. Existing rows have no till, so the column is nullable with no default. See ADR 0009.

Revision ID: c3e8f1a9b7d2
Revises: a7c1e9f04b2d
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e8f1a9b7d2'
down_revision: Union[str, Sequence[str], None] = 'a7c1e9f04b2d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('merchants', sa.Column('operator_till', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('merchants', 'operator_till')
