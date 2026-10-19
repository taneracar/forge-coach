from datetime import UTC

import pytest

from app.coach import CoachError, FallbackCoach, ungrounded_numbers
from app.models import CoachReport, TrainingProfile
from app.rules import RuleCoach, build_report, num
from app.stats import compute_weekly_stats
from tests.factories import TODAY, s, session, weeks_ago


def legs(w, reps=5):
    return s("Barbell Squat", w, reps, muscle="legs")


SCENARIOS = {
    "new_user": [],
    "record_week": [
        session(weeks_ago(2), s("Bench Press", 80, 5), legs(100)),
        session(weeks_ago(1), s("Bench Press", 82.5, 5), legs(105)),
        session(TODAY, s("Bench Press", 87.5, 5), legs(110)),
    ],
    "stalled_squat": [
        session(weeks_ago(4), legs(120)),
        session(weeks_ago(3), legs(115)),
        session(weeks_ago(2), legs(117.5)),
        session(weeks_ago(1), legs(115)),
        session(TODAY, legs(117.5)),
    ],
    "missed_last_week": [session(weeks_ago(n), s("Bench Press", 80, 5)) for n in (1, 2, 3)],
    # Same number of sessions as last week, lighter work: a real drop.
    "volume_drop": [
        *[
            session(weeks_ago(1, d), s("Bench Press", 80, 5), s("Bench Press", 80, 5))
            for d in (0, 2, 4, 5)
        ],
        *[
            session(weeks_ago(0, d), s("Bench Press", 70, 5), hour=h)
            for d, h in ((0, 9), (0, 18), (1, 9), (2, 9))
        ],
    ],
}

PROFILE = TrainingProfile(preferred_training_days=4)


def stats_for(name, profile=PROFILE):
    return compute_weekly_stats(SCENARIOS[name], profile, TODAY, UTC)


@pytest.mark.parametrize("lang", ["en", "tr"])
@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_number_comes_from_the_stats(name, lang):
    stats = stats_for(name)
    report = build_report(stats, lang)
    assert ungrounded_numbers(report, stats) == []
    assert max(len(report.wins), len(report.focus_areas), len(report.next_week)) <= 3
    assert report.next_week


@pytest.mark.parametrize(
    "name,tone",
    [
        ("new_user", "welcome"),
        ("record_week", "celebrate"),
        ("missed_last_week", "nudge"),
        ("volume_drop", "steady"),
    ],
)
def test_tone(name, tone):
    assert build_report(stats_for(name), "en").tone == tone


def test_records_are_named_with_their_numbers():
    report = build_report(stats_for("record_week"), "en")
    # Records are ordered by estimated 1RM, so the squat comes first.
    assert report.wins[0].startswith("Barbell Squat: 110 kg for 5")
    assert report.wins[1].startswith("Bench Press: 87.5 kg for 5")
    assert any("Barbell Squat" in line for line in report.next_week)


def test_stalled_lift_gets_a_concrete_change():
    report = build_report(stats_for("stalled_squat"), "en")
    assert "Barbell Squat has not improved for 4 weeks" in report.focus_areas[0]
    assert "rep range" in report.next_week[0]


def test_nudge_headline_counts_last_week():
    report = build_report(stats_for("missed_last_week"), "tr")
    assert report.headline == "Geçen hafta planladığın 4 günün 1 gününde antrenman yaptın."


def test_volume_drop_is_a_focus_area():
    report = build_report(stats_for("volume_drop"), "en")
    assert any(line.startswith("Volume is down") for line in report.focus_areas)


def test_without_a_target_suggests_a_default():
    stats = stats_for("record_week", TrainingProfile())
    assert build_report(stats, "en").next_week[-1] == "Aim for at least 3 sessions next week."


def test_turkish_numbers_use_a_decimal_comma():
    assert num(62.5, "tr") == "62,5"
    assert num(62.5, "en") == "62.5"
    assert num(100.0, "en") == "100"


class Broken:
    model = "claude-opus-5-5"

    async def write_report(self, stats, lang):
        raise CoachError("no")


class Works:
    model = "claude-opus-5-5"

    async def write_report(self, stats, lang):
        return CoachReport(headline="x", wins=[], focus_areas=[], next_week=[], tone="steady"), (
            self.model
        )


async def test_fallback_answers_when_the_primary_fails():
    report, model = await FallbackCoach(Broken(), RuleCoach()).write_report(
        stats_for("record_week"), "en"
    )
    assert model == "rules-v1"
    assert report.tone == "celebrate"


async def test_fallback_is_not_used_when_the_primary_works():
    _, model = await FallbackCoach(Works(), RuleCoach()).write_report(stats_for("new_user"), "en")
    assert model == "claude-opus-5-5"


def test_a_week_in_progress_is_not_called_a_volume_drop():
    report = build_report(stats_for("missed_last_week"), "en")
    assert not any(line.startswith("Volume is down") for line in report.focus_areas)
