"""tag emergence_rating, and the missing generic flag

PRD: tags carry emergence_rating, computed by POST /sync/catalog, used by
picking as the reachability gate ("emergence rating reached").

Also: 0002 seeded is_generic for only 4 of the 5 PRD-generic tags; constructive
algorithms was left at weight 1.0 instead of 0.25, skewing the rating update.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tags', sa.Column('emergence_rating', sa.Integer(), nullable=True))
    op.execute("UPDATE tags SET is_generic = true WHERE name = 'constructive algorithms'")


def downgrade():
    op.execute("UPDATE tags SET is_generic = false WHERE name = 'constructive algorithms'")
    op.drop_column('tags', 'emergence_rating')
