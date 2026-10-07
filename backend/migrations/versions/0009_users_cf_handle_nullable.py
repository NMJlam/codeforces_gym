"""users.cf_handle becomes nullable

A verified Cloudflare email now creates a user immediately (no invite/allow
list), and that user has no Codeforces handle until they set one through
PUT /api/users/me. The unique constraint stays: several NULLs are allowed,
non-null handles remain unique.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('users', 'cf_handle', existing_type=sa.Text(), nullable=True)


def downgrade():
    # Fails if handle-less users exist; that is the honest behaviour for a
    # column that used to be required.
    op.alter_column('users', 'cf_handle', existing_type=sa.Text(), nullable=False)
