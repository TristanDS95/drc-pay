"""add provenance to transactions

Records how a payment's outcome was established (its assurance level): "rail_verified" (pawaPay's
RFC-9421 signed callback) or "merchant_attested" (on-net — the merchant confirmed receipt). Existing
rows are all pawaPay-routed, so they default to "rail_verified". See ADR 0009.

Revision ID: a7c1e9f04b2d
Revises: f3a4b5c6d7e8
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c1e9f04b2d'
down_revision: Union[str, Sequence[str], None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'transactions',
        sa.Column('provenance', sa.String(), server_default='rail_verified', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('transactions', 'provenance')
