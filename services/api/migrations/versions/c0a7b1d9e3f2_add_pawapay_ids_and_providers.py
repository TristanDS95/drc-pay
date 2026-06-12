"""add pawaPay op-ids and resolved providers to transactions

Revision ID: c0a7b1d9e3f2
Revises: b79d18ed3797
Create Date: 2026-06-11 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0a7b1d9e3f2'
down_revision: Union[str, Sequence[str], None] = 'b79d18ed3797'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Resolved mobile-money operators: payer's (collection + refund formatting) and
    # payee's (payout). Captured at start so the later webhook-driven legs have them.
    op.add_column('transactions', sa.Column('payer_provider', sa.String(), nullable=True))
    op.add_column('transactions', sa.Column('payee_provider', sa.String(), nullable=True))
    # pawaPay operation ids: correlate async callbacks back to the transaction and let a
    # refund reference the original deposit.
    op.add_column('transactions', sa.Column('deposit_id', sa.String(), nullable=True))
    op.add_column('transactions', sa.Column('payout_id', sa.String(), nullable=True))
    op.add_column('transactions', sa.Column('refund_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('transactions', 'refund_id')
    op.drop_column('transactions', 'payout_id')
    op.drop_column('transactions', 'deposit_id')
    op.drop_column('transactions', 'payee_provider')
    op.drop_column('transactions', 'payer_provider')
