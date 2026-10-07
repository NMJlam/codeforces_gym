"""session picks: allow the recall slot

A due revisit is served as a repeat of the problem the user failed. That repeat
is an unrated attempt (see ck_attempts_recall_unrated), but it still needs a
pick row so it survives a refresh: hence the fourth slot value.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f('ck_session_picks_slot_valid'), 'session_picks', type_='check')
    op.create_check_constraint('slot_valid', 'session_picks',
                               "slot IN ('warmup', 'main', 'stretch', 'recall')")


def downgrade():
    op.drop_constraint(op.f('ck_session_picks_slot_valid'), 'session_picks', type_='check')
    op.create_check_constraint('slot_valid', 'session_picks',
                               "slot IN ('warmup', 'main', 'stretch')")
