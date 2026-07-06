"""add merchant auth tables

Per-merchant authentication (security roadmap, Gate A): ``merchant_credentials`` holds each
merchant's username + Argon2id password hash (never a plaintext password), and
``merchant_sessions`` holds live logins keyed by the SHA-256 of the opaque bearer token
(never the token itself). Sessions carry their own expiry.

Revision ID: e9b3c5d7f1a2
Revises: c3e8f1a9b7d2
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9b3c5d7f1a2'
down_revision: Union[str, Sequence[str], None] = 'c3e8f1a9b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'merchant_credentials',
        sa.Column('merchant_id', sa.String(), sa.ForeignKey('merchants.id'), primary_key=True),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_merchant_credentials_username', 'merchant_credentials', ['username'], unique=True)
    op.create_table(
        'merchant_sessions',
        sa.Column('token_hash', sa.String(), primary_key=True),
        sa.Column('merchant_id', sa.String(), sa.ForeignKey('merchants.id'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_merchant_sessions_merchant_id', 'merchant_sessions', ['merchant_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_merchant_sessions_merchant_id', table_name='merchant_sessions')
    op.drop_table('merchant_sessions')
    op.drop_index('ix_merchant_credentials_username', table_name='merchant_credentials')
    op.drop_table('merchant_credentials')
