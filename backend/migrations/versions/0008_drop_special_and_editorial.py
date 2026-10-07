"""drop special problems and editorial tracking

Special problems are excluded (PRD: Exclude *special) by not ingesting them at
all, so problems.is_special is dead. Codeforces exposes no editorial flag, so
problems.has_editorial is dropped too; the app returns a search string instead
(Problem.editorial_search).

Downgrade restores the columns but not the deleted rows.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    # Problems tagged "*special" that earlier syncs ingested. The tag is a
    # Codeforces convention, so it identifies exactly the special problems.
    op.execute(
        "DELETE FROM problems WHERE id IN ("
        "  SELECT pt.problem_id FROM problem_tags pt"
        "  JOIN tags t ON t.id = pt.tag_id WHERE t.name = '*special')"
    )
    op.execute("DELETE FROM tags WHERE name = '*special'")

    op.drop_index('ix_problems_rating_candidates', table_name='problems')
    op.drop_column('problems', 'is_special')
    op.drop_column('problems', 'has_editorial')
    op.create_index(
        'ix_problems_rating_candidates', 'problems', ['rating'], unique=False,
        postgresql_where=sa.text('rating IS NOT NULL'),
    )


def downgrade():
    op.drop_index('ix_problems_rating_candidates', table_name='problems')
    op.add_column('problems', sa.Column('has_editorial', sa.Boolean(),
                                        server_default=sa.text('false'), nullable=False))
    op.add_column('problems', sa.Column('is_special', sa.Boolean(),
                                        server_default=sa.text('false'), nullable=False))
    op.create_index(
        'ix_problems_rating_candidates', 'problems', ['rating'], unique=False,
        postgresql_where=sa.text('rating IS NOT NULL AND NOT is_special'),
    )
