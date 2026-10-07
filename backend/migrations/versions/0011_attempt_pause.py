"""attempt pause: paused_at + paused_seconds

An interrupted attempt needs to stop the clock without burning the 45-minute
window. The timer stays server-authoritative: the effective deadline becomes
started_at + 45 minutes + paused_seconds, and while paused_at is set the
countdown is frozen at deadline - paused_at.

The score-immutability trigger is widened so a scored attempt cannot change its
pause fields either: scoring clears paused_at and finalises paused_seconds in
the same open -> scored update, which the trigger already allows.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('attempts', sa.Column('paused_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('attempts', sa.Column('paused_seconds', sa.Integer(), server_default='0', nullable=False))
    op.create_check_constraint('paused_after_start', 'attempts',
                               'paused_at IS NULL OR paused_at >= started_at')
    op.create_check_constraint('paused_only_while_open', 'attempts',
                               'scored_at IS NULL OR paused_at IS NULL')
    op.create_check_constraint('paused_seconds_nonneg', 'attempts', 'paused_seconds >= 0')

    # Widened so the pause fields freeze with the score, hand-written because
    # Alembic does not manage triggers.
    op.execute("DROP TRIGGER trg_attempts_score_immutable ON attempts")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_attempt_score_changes() RETURNS trigger AS $$
        BEGIN
            -- OLD.scored_at IS NULL: the attempt is still open, so scoring it
            -- (the one legitimate write to these columns) must go through.
            IF OLD.scored_at IS NOT NULL AND (
                NEW.s IS DISTINCT FROM OLD.s
                OR NEW.e_model IS DISTINCT FROM OLD.e_model
                OR NEW.scored_at IS DISTINCT FROM OLD.scored_at
                OR NEW.paused_at IS DISTINCT FROM OLD.paused_at
                OR NEW.paused_seconds IS DISTINCT FROM OLD.paused_seconds
            ) THEN
                RAISE EXCEPTION 'scored attempt fields are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_attempts_score_immutable
        BEFORE UPDATE OF s, e_model, scored_at, paused_at, paused_seconds ON attempts
        FOR EACH ROW EXECUTE FUNCTION prevent_attempt_score_changes()
        """
    )


def downgrade():
    op.execute("DROP TRIGGER trg_attempts_score_immutable ON attempts")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_attempt_score_changes() RETURNS trigger AS $$
        BEGIN
            IF OLD.scored_at IS NOT NULL AND (
                NEW.s IS DISTINCT FROM OLD.s
                OR NEW.e_model IS DISTINCT FROM OLD.e_model
                OR NEW.scored_at IS DISTINCT FROM OLD.scored_at
            ) THEN
                RAISE EXCEPTION 'scored attempt fields are immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_attempts_score_immutable
        BEFORE UPDATE OF s, e_model, scored_at ON attempts
        FOR EACH ROW EXECUTE FUNCTION prevent_attempt_score_changes()
        """
    )

    op.drop_constraint(op.f('ck_attempts_paused_seconds_nonneg'), 'attempts', type_='check')
    op.drop_constraint(op.f('ck_attempts_paused_only_while_open'), 'attempts', type_='check')
    op.drop_constraint(op.f('ck_attempts_paused_after_start'), 'attempts', type_='check')
    op.drop_column('attempts', 'paused_seconds')
    op.drop_column('attempts', 'paused_at')
