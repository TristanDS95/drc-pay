"""add staff auth tables

Staff (admin) accounts, the platform's own operators who approve/reject merchant sign-ups.
``staff_credentials`` holds each staff member's username + Argon2id password hash + role (never a
plaintext password); ``staff_sessions`` holds live logins keyed by the SHA-256 of the opaque
bearer token (never the token itself). Mirrors the merchant auth tables, kept separate because
staff are not merchants.

Revision ID: f1a2b3c4d5e6
Revises: e9b3c5d7f1a2
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e9b3c5d7f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'staff_credentials',
        sa.Column('staff_id', sa.String(), primary_key=True),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_staff_credentials_username', 'staff_credentials', ['username'], unique=True)
    op.create_table(
        'staff_sessions',
        sa.Column('token_hash', sa.String(), primary_key=True),
        sa.Column('staff_id', sa.String(), sa.ForeignKey('staff_credentials.staff_id'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_staff_sessions_staff_id', 'staff_sessions', ['staff_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_staff_sessions_staff_id', table_name='staff_sessions')
    op.drop_table('staff_sessions')
    op.drop_index('ix_staff_credentials_username', table_name='staff_credentials')
    op.drop_table('staff_credentials')
