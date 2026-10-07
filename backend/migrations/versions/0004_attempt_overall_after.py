"""attempts.overall_after for the rating-over-time chart

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('attempts', sa.Column('overall_after', sa.Double(), nullable=True))
    op.create_check_constraint(
        op.f('ck_attempts_rated_has_overall_after'), 'attempts',
        'scored_at IS NULL OR NOT rated OR overall_after IS NOT NULL',
    )


def downgrade():
    op.drop_constraint(op.f('ck_attempts_rated_has_overall_after'), 'attempts', type_='check')
    op.drop_column('attempts', 'overall_after')
