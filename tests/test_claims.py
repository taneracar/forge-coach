from datetime import UTC

from app.claims import unsupported_claims
from app.models import CoachReport, TrainingProfile
from app.stats import compute_weekly_stats
from tests.factories import TODAY, s, session, weeks_ago


def report(*lines: str) -> CoachReport:
    return CoachReport(headline="x", wins=list(lines), focus_areas=[], next_week=[], tone="steady")


def stats(sessions, goal="build_muscle"):
    return compute_weekly_stats(sessions, TrainingProfile(goal=goal), TODAY, UTC)


ONE_WEEK_OFF = [
    session(weeks_ago(3), s("Bench Press", 60, 5)),
    session(weeks_ago(2), s("Bench Press", 60, 5)),
    session(TODAY, s("Bench Press", 60, 5), s("Squat", 80, 5, muscle="legs")),
]


def test_wrong_goal_is_caught_in_both_languages():
    st = stats(ONE_WEEK_OFF, goal="build_muscle")
    assert unsupported_claims(report("Good for your strength goal."), st)
    assert unsupported_claims(report("Güç hedefin için iyi."), st)
    assert unsupported_claims(report("Kas geliştirme hedefin için iyi."), st) == []


def test_break_length_must_match():
    st = stats(ONE_WEEK_OFF)
    assert unsupported_claims(report("Back after a week off."), st) == []
    assert unsupported_claims(report("Back after two weeks off."), st)
    assert unsupported_claims(report("İki haftalık aradan sonra döndün."), st)
    assert unsupported_claims(report("Bir haftalık aradan sonra döndün."), st) == []


def test_muscle_group_that_was_trained_cannot_be_called_skipped():
    st = stats(ONE_WEEK_OFF)
    assert unsupported_claims(report("Legs got no work this week."), st)
    assert unsupported_claims(report("Bu hafta bacak hiç çalışmadı."), st)
    assert unsupported_claims(report("Sırt bu hafta hiç çalışmadı."), st) == []


def test_first_week_claim_needs_no_history():
    st = stats(ONE_WEEK_OFF)
    assert unsupported_claims(report("Great start to your first week."), st)
    assert unsupported_claims(report("Five sessions in your first week back."), st) == []
    first = stats([session(TODAY, s("Bench Press", 60, 5))])
    assert unsupported_claims(report("Great start to your first week."), first) == []
