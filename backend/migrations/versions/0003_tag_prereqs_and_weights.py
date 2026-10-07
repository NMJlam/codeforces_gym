"""tag prereqs and tier weights

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

# tier_weight scales a tag's priority in the daily topic draw (see model/tag.py).
TIER_WEIGHTS = {
    "implementation": 1.0, "brute force": 1.0, "sortings": 1.0, "greedy": 1.0,
    "math": 1.0, "constructive algorithms": 1.0,
    "binary search": 1.0, "two pointers": 1.0, "ternary search": 0.5,
    "meet-in-the-middle": 0.5,
    "dp": 1.0, "bitmasks": 1.0, "combinatorics": 1.0, "probabilities": 1.0,
    "matrices": 0.5, "games": 1.0,
    "number theory": 1.0, "chinese remainder theorem": 0.1, "fft": 0.1,
    "geometry": 0.3,
    "graphs": 1.0, "dfs and similar": 1.0, "trees": 1.0, "dsu": 1.0,
    "shortest paths": 1.0, "2-sat": 0.1, "flows": 0.1, "graph matchings": 0.1,
    "data structures": 1.0, "divide and conquer": 0.5,
    "strings": 1.0, "hashing": 1.0, "string suffix structures": 0.1,
    "expression parsing": 1.0,
    "interactive": 0.1, "communication": 0.1, "schedules": 0.1,
}

# (tag, requires_tag, min_attempts, min_solves). A tag unlocks once every one
# of its requires edges has at least this many distinct problems
# attempted/solved; 0/0 edges never gate, they only suggest an order.
PREREQS = [
    ("binary search", "sortings", 5, 3),
    ("two pointers", "sortings", 5, 3),
    ("ternary search", "binary search", 5, 3),
    ("meet-in-the-middle", "brute force", 5, 3),
    ("meet-in-the-middle", "bitmasks", 5, 3),
    ("dp", "brute force", 5, 3),
    ("bitmasks", "math", 5, 3),
    ("combinatorics", "dp", 5, 3),
    ("combinatorics", "number theory", 5, 3),
    ("probabilities", "combinatorics", 5, 3),
    ("matrices", "dp", 5, 3),
    ("matrices", "math", 5, 3),
    ("games", "math", 5, 3),
    ("games", "dp", 1, 0),
    ("number theory", "math", 5, 3),
    ("chinese remainder theorem", "number theory", 5, 3),
    ("fft", "number theory", 5, 3),
    ("fft", "combinatorics", 5, 3),
    ("fft", "divide and conquer", 5, 3),
    ("geometry", "math", 5, 3),
    ("graphs", "implementation", 5, 3),
    ("dfs and similar", "graphs", 5, 3),
    ("trees", "dfs and similar", 5, 3),
    ("dsu", "graphs", 5, 3),
    ("shortest paths", "dfs and similar", 5, 3),
    ("2-sat", "dfs and similar", 5, 3),
    ("flows", "graphs", 5, 3),
    ("graph matchings", "dfs and similar", 5, 3),
    ("graph matchings", "flows", 1, 0),
    ("data structures", "implementation", 5, 3),
    ("divide and conquer", "data structures", 5, 3),
    ("divide and conquer", "trees", 0, 0),
    ("strings", "implementation", 5, 3),
    ("hashing", "strings", 5, 3),
    ("string suffix structures", "hashing", 5, 3),
    ("string suffix structures", "data structures", 1, 0),
    ("expression parsing", "strings", 5, 3),
    ("interactive", "binary search", 0, 0),
    ("interactive", "constructive algorithms", 0, 0),
    ("communication", "interactive", 5, 3),
    ("schedules", "greedy", 1, 0),
]


def upgrade():
    op.add_column(
        'tags',
        sa.Column('tier_weight', sa.Double(), server_default=sa.text('1.0'), nullable=False),
    )
    op.create_check_constraint(
        'ck_tags_tier_weight_range', 'tags', 'tier_weight > 0 AND tier_weight <= 1',
    )
    op.add_column(
        'tag_prereqs',
        sa.Column('min_attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )
    op.add_column(
        'tag_prereqs',
        sa.Column('min_solves', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )
    op.create_check_constraint(
        'ck_tag_prereqs_min_attempts_nonneg', 'tag_prereqs', 'min_attempts >= 0',
    )
    op.create_check_constraint(
        'ck_tag_prereqs_min_solves_range', 'tag_prereqs',
        'min_solves >= 0 AND min_solves <= min_attempts',
    )

    tags = sa.table('tags', sa.column('id'), sa.column('name'), sa.column('tier_weight'))
    tag_prereqs = sa.table(
        'tag_prereqs', sa.column('tag_id'), sa.column('requires_tag_id'),
        sa.column('min_attempts'), sa.column('min_solves'),
    )

    conn = op.get_bind()
    for name, weight in TIER_WEIGHTS.items():
        conn.execute(tags.update().where(tags.c.name == name).values(tier_weight=weight))

    tag_ids = {
        row.name: row.id
        for row in conn.execute(sa.select(tags.c.id, tags.c.name))
    }
    for tag_name, requires_name, min_attempts, min_solves in PREREQS:
        conn.execute(
            tag_prereqs.insert().values(
                tag_id=tag_ids[tag_name],
                requires_tag_id=tag_ids[requires_name],
                min_attempts=min_attempts,
                min_solves=min_solves,
            )
        )


def downgrade():
    op.drop_constraint('ck_tag_prereqs_min_solves_range', 'tag_prereqs', type_='check')
    op.drop_constraint('ck_tag_prereqs_min_attempts_nonneg', 'tag_prereqs', type_='check')
    op.drop_column('tag_prereqs', 'min_solves')
    op.drop_column('tag_prereqs', 'min_attempts')
    op.drop_constraint('ck_tags_tier_weight_range', 'tags', type_='check')
    op.drop_column('tags', 'tier_weight')
