from datetime import UTC, date
from zoneinfo import ZoneInfo

import pytest

from app.models import TrainingProfile
from app.stats import compute_weekly_stats, estimated_1rm, week_start
from tests.factories import THIS_MONDAY, TODAY, s, session, weeks_ago

LA = ZoneInfo("America/Los_Angeles")
PROFILE = TrainingProfile(
    goal="build_muscle", workout_experience="beginner", preferred_training_days=4
)


def stats(sessions, tz=UTC, today=TODAY, profile=PROFILE):
    return compute_weekly_stats(sessions, profile, today, tz, history_weeks=8)


def test_week_starts_on_monday():
    assert week_start(date(2026, 10, 25)) == THIS_MONDAY  # Sunday
    assert week_start(THIS_MONDAY) == THIS_MONDAY


def test_estimated_1rm_single_rep_is_the_weight():
    assert estimated_1rm(100, 1) == 100
    assert estimated_1rm(100, 10) == pytest.approx(133.33, abs=0.01)


def test_empty_history():
    st = stats([])
    assert st.this_week.sessions == 0
    assert len(st.previous_weeks) == 7
    assert st.volume_change_pct is None
    assert st.training_streak_weeks == 0
    assert not st.has_training


def test_volume_counts_only_completed_weighted_sets():
    st = stats(
        [
            session(
                TODAY, s("Bench", 60, 10), s("Bench", 60, 8, done=False), s("Push Up", None, 20)
            ),
        ]
    )
    assert st.this_week.sessions == 1
    assert st.this_week.completed_sets == 2  # the unfinished set is out, push ups count as a set
    assert st.this_week.volume_kg == 600


def test_unfinished_sessions_are_ignored():
    st = stats([session(TODAY, s("Bench", 60, 10), completed=False)])
    assert st.this_week.sessions == 0


def test_sessions_outside_the_window_are_ignored():
    st = stats([session(weeks_ago(8), s("Bench", 60, 10))])
    assert not st.has_training


def test_volume_change_against_last_week():
    st = stats(
        [
            session(weeks_ago(1), s("Bench", 50, 10)),  # 500
            session(TODAY, s("Bench", 60, 10)),  # 600
        ]
    )
    assert st.volume_change_pct == 20.0


def test_no_volume_change_without_a_previous_week():
    assert stats([session(TODAY, s("Bench", 60, 10))]).volume_change_pct is None


def test_sets_by_muscle_group_sorted_by_count():
    st = stats(
        [
            session(
                TODAY,
                s("Squat", 80, 5, muscle="legs"),
                s("Bench", 60, 8),
                s("Squat", 80, 5, muscle="legs"),
                s("Row", 50, 10, muscle="back"),
            )
        ]
    )
    assert list(st.sets_by_muscle_group.items()) == [("legs", 2), ("back", 1), ("chest", 1)]


def test_late_sunday_session_belongs_to_the_local_week():
    # Sunday 2026-10-18, 20:00 in Los Angeles is Monday 03:00 UTC.
    sunday_night = session(date(2026, 10, 18), s("Bench", 60, 10), hour=20, tz=LA)
    assert stats([sunday_night], tz=LA).this_week.sessions == 0
    assert stats([sunday_night], tz=UTC).this_week.sessions == 1


def test_personal_record_beats_earlier_best():
    st = stats(
        [
            session(weeks_ago(2), s("Bench", 60, 5)),
            session(TODAY, s("Bench", 65, 5)),
        ]
    )
    [pr] = st.personal_records
    assert pr.exercise == "Bench"
    assert pr.weight_kg == 65 and pr.reps == 5
    assert pr.previous_best_kg == 70.0
    assert pr.estimated_1rm_kg == pytest.approx(75.8, abs=0.05)


def test_first_time_lift_is_not_a_record():
    assert stats([session(TODAY, s("Bench", 60, 5))]).personal_records == []


def test_matching_the_old_best_is_not_a_record():
    st = stats([session(weeks_ago(1), s("Bench", 60, 5)), session(TODAY, s("Bench", 60, 5))])
    assert st.personal_records == []


def test_high_rep_sets_do_not_count_for_strength():
    st = stats(
        [
            session(weeks_ago(1), s("Bench", 60, 5)),
            session(TODAY, s("Bench", 50, 20)),  # Epley would say 83 kg; we do not trust it
        ]
    )
    assert st.personal_records == []


def test_stalled_lift_after_three_weeks_without_progress():
    st = stats(
        [
            session(weeks_ago(3), s("Squat", 100, 5, muscle="legs")),
            session(weeks_ago(2), s("Squat", 95, 5, muscle="legs")),
            session(weeks_ago(1), s("Squat", 97.5, 5, muscle="legs")),
            session(TODAY, s("Squat", 100, 4, muscle="legs")),
        ]
    )
    [stall] = st.stalled_lifts
    assert stall.exercise == "Squat"
    assert stall.weeks_without_progress == 3
    assert stall.best_estimated_1rm_kg == pytest.approx(116.7, abs=0.05)


def test_lift_that_was_dropped_is_not_stalled():
    st = stats(
        [
            session(weeks_ago(5), s("Squat", 100, 5, muscle="legs")),
            session(weeks_ago(4), s("Squat", 95, 5, muscle="legs")),
            session(weeks_ago(3), s("Squat", 95, 5, muscle="legs")),
        ]
    )
    assert st.stalled_lifts == []


def test_streak_does_not_break_on_the_week_in_progress():
    sessions = [session(weeks_ago(n), s("Bench", 60, 5)) for n in (1, 2, 3)]
    assert stats(sessions).training_streak_weeks == 3
    assert stats([*sessions, session(TODAY, s("Bench", 60, 5))]).training_streak_weeks == 4


def test_streak_breaks_on_an_empty_week():
    sessions = [session(weeks_ago(n), s("Bench", 60, 5)) for n in (1, 3, 4)]
    assert stats(sessions).training_streak_weeks == 1


def test_profile_fields_are_carried_through():
    st = stats([])
    assert st.target_sessions_per_week == 4
    assert st.goal == "build_muscle"
    assert st.experience == "beginner"
