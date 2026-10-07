from model import Contest, Problem, db


def test_editorial_search_uses_the_contest_name_not_the_id(app):
    # The contest id is not the round number (contest 1900 is Round 911).
    db.session.add(Contest(id=999777, name="Codeforces Round 911 (Div. 2)"))
    db.session.add(Problem(contest_id=999777, problem_index="C", name="X", rating=1500))
    db.session.flush()

    p = Problem.query.filter_by(contest_id=999777, problem_index="C").one()
    assert p.editorial_search == "Codeforces Round 911 (Div. 2) editorial"
