"""Import every model so its table is registered on db.metadata.

Alembic's autogenerate only sees tables that have been imported, so a new
model file must also be added here.
"""

from model.db import db

# Catalog (from Codeforces, re-fetchable)
from model.contest import Contest
from model.problem import Problem
from model.tag import Tag
from model.tag_group import TagGroup
from model.problem_tag import ProblemTag

# Attempt log (source of truth)
from model.user import User
from model.practice_session import PracticeSession
from model.session_pick import SessionPick
from model.attempt import Attempt
from model.attempt_tag import AttemptTag

# Rating caches (rebuilt by replay)
from model.overall_rating import OverallRating
from model.topic_rating import TopicRating
from model.calibration import Calibration

# Seen problems and revisits
from model.seen_problem import SeenProblem
from model.revisit import Revisit

__all__ = [
    "db",
    "Contest", "Problem", "Tag", "TagGroup", "ProblemTag",
    "User", "PracticeSession", "SessionPick", "Attempt", "AttemptTag",
    "OverallRating", "TopicRating", "Calibration",
    "SeenProblem", "Revisit",
]
