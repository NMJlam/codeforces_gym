"""drop tag_prereqs dependency map

Topic order is left to the rating: a tag's difficulty is handled by its topic
rating, reachability by emergence_rating, and exploration by RD uncertainty
(an untouched tag sits at the RD cap, so it is drawn). A hand-written
prerequisite graph duplicates that and would wall off experienced users.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('tag_prereqs')


def downgrade():
    op.create_table(
        'tag_prereqs',
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('requires_tag_id', sa.Integer(), nullable=False),
        sa.Column('min_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('min_solves', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.CheckConstraint('tag_id <> requires_tag_id', name=op.f('ck_tag_prereqs_not_self')),
        sa.CheckConstraint('min_attempts >= 0', name=op.f('ck_tag_prereqs_min_attempts_nonneg')),
        sa.CheckConstraint('min_solves >= 0 AND min_solves <= min_attempts',
                           name=op.f('ck_tag_prereqs_min_solves_range')),
        sa.ForeignKeyConstraint(['requires_tag_id'], ['tags.id'],
                                name=op.f('fk_tag_prereqs_requires_tag_id_tags'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'],
                                name=op.f('fk_tag_prereqs_tag_id_tags'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tag_id', 'requires_tag_id', name=op.f('pk_tag_prereqs')),
    )
