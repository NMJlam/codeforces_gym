"""drop cf_submissions cache

Submissions are read straight from the Codeforces API when needed (the Done
check makes one call anyway); there is no second offline reader, so the cache
table and its FK are dead weight. attempts.accepted_submission_id keeps the
CF submission id, now as a plain bigint.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    # The inbound FK must go before the table it references can be dropped.
    op.drop_constraint(
        op.f('fk_attempts_accepted_submission_id_cf_submissions'),
        'attempts', type_='foreignkey',
    )
    op.drop_index('ix_cf_submissions_lookup', table_name='cf_submissions')
    op.drop_table('cf_submissions')


def downgrade():
    op.create_table(
        'cf_submissions',
        sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('problem_id', sa.Integer(), nullable=False),
        sa.Column('verdict', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['problem_id'], ['problems.id'],
                                name=op.f('fk_cf_submissions_problem_id_problems')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'],
                                name=op.f('fk_cf_submissions_user_id_users'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cf_submissions')),
    )
    op.create_index('ix_cf_submissions_lookup', 'cf_submissions',
                    ['user_id', 'problem_id', 'submitted_at'], unique=False)
    op.create_foreign_key(
        op.f('fk_attempts_accepted_submission_id_cf_submissions'),
        'attempts', 'cf_submissions', ['accepted_submission_id'], ['id'],
    )
