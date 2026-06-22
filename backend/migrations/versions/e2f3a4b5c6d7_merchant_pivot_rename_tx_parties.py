"""merchant pivot: rename transaction parties to customer/merchant, add merchant_id

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-11 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # A transaction is now a customer paying a merchant (was a generic payer→payee).
    op.alter_column('transactions', 'payer_msisdn', new_column_name='customer_msisdn')
    op.alter_column('transactions', 'payee_msisdn', new_column_name='merchant_msisdn')
    op.alter_column('transactions', 'payer_provider', new_column_name='customer_provider')
    op.alter_column('transactions', 'payee_provider', new_column_name='merchant_provider')
    # Link the transaction to the registered merchant it settles to.
    op.add_column('transactions', sa.Column('merchant_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('transactions', 'merchant_id')
    op.alter_column('transactions', 'merchant_provider', new_column_name='payee_provider')
    op.alter_column('transactions', 'customer_provider', new_column_name='payer_provider')
    op.alter_column('transactions', 'merchant_msisdn', new_column_name='payee_msisdn')
    op.alter_column('transactions', 'customer_msisdn', new_column_name='payer_msisdn')
