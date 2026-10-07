"""tag groups

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

# Dashboard radar chart: one axis per group, so every tag maps to exactly one.
# is_generic tags (see model/tag.py) keep their existing flag.
GROUPS = {
    "Graphs": ["graphs", "dfs and similar", "trees", "dsu", "shortest paths",
               "flows", "graph matchings", "2-sat"],
    "DP & counting": ["dp", "combinatorics", "probabilities", "bitmasks",
                       "matrices", "meet-in-the-middle", "brute force"],
    "Greedy & search": ["greedy", "sortings", "binary search", "two pointers",
                          "data structures", "divide and conquer"],
    "Geometry": ["geometry", "ternary search"],
    "Number theory": ["math", "number theory", "fft",
                        "chinese remainder theorem"],
    "Strings": ["strings", "hashing", "string suffix structures"],
    "Constructive & interactive": ["constructive algorithms", "interactive",
                                     "communication"],
    "Implementation": ["implementation", "expression parsing", "schedules"],
    "Games": ["games"],
}
GENERIC_TAGS = {"greedy", "implementation", "math", "brute force"}


def upgrade():
    op.create_table(
        'tag_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_tag_groups')),
        sa.UniqueConstraint('name', name=op.f('uq_tag_groups_name')),
    )
    op.add_column('tags', sa.Column('group_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f('fk_tags_group_id_tag_groups'), 'tags', 'tag_groups',
        ['group_id'], ['id'],
    )

    tag_groups = sa.table(
        'tag_groups', sa.column('id'), sa.column('name'),
    )
    tags = sa.table(
        'tags', sa.column('id'), sa.column('name'), sa.column('is_generic'),
        sa.column('group_id'),
    )

    for group_name in GROUPS:
        op.execute(
            tag_groups.insert().values(name=group_name)
        )

    conn = op.get_bind()
    for group_name, tag_names in GROUPS.items():
        group_id = conn.execute(
            sa.select(tag_groups.c.id).where(tag_groups.c.name == group_name)
        ).scalar_one()
        for tag_name in tag_names:
            existing = conn.execute(
                sa.select(tags.c.id).where(tags.c.name == tag_name)
            ).scalar_one_or_none()
            if existing is None:
                conn.execute(
                    tags.insert().values(
                        name=tag_name,
                        is_generic=tag_name in GENERIC_TAGS,
                        group_id=group_id,
                    )
                )
            else:
                conn.execute(
                    tags.update()
                    .where(tags.c.id == existing)
                    .values(group_id=group_id)
                )


def downgrade():
    op.drop_constraint(op.f('fk_tags_group_id_tag_groups'), 'tags', type_='foreignkey')
    op.drop_column('tags', 'group_id')
    op.drop_table('tag_groups')
