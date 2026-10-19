"""Evaluation against the real Claude API.

Not part of the normal run (it costs money): `pytest -m live`.
Each scenario is a realistic week; the checks are things a wrong report
would get wrong, not exact wording.
"""

import os
import re
from datetime import UTC

import anthropic
import pytest

from app.coach import ClaudeCoach, ungrounded_numbers
from app.models import TrainingProfile
from app.stats import compute_weekly_stats
from tests.factories import TODAY, s, session, weeks_ago

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("ANTHROPIC_API_KEY", "test-key") == "test-key",
        reason="needs a real ANTHROPIC_API_KEY",
    ),
]

MEDICAL = re.compile(r"\b(injur|pain|doctor|physio|calorie|diet|lose weight|fat loss)", re.I)

PROFILE = TrainingProfile(
    goal="build_muscle", workout_experience="intermediate", preferred_training_days=4
)


def legs(w, reps=5):
    return s("Barbell Squat", w, reps, muscle="legs")


SCENARIOS = {
    "new_user": ([], "welcome"),
    "record_week": (
        [
            session(weeks_ago(2), s("Bench Press", 80, 5), legs(100)),
            session(weeks_ago(1), s("Bench Press", 82.5, 5), legs(105)),
            session(TODAY, s("Bench Press", 87.5, 5), legs(110)),
        ],
        "celebrate",
    ),
    "stalled_squat": (
        [
            session(weeks_ago(4), legs(120)),
            session(weeks_ago(3), legs(115)),
            session(weeks_ago(2), legs(117.5)),
            session(weeks_ago(1), legs(115)),
            session(TODAY, legs(117.5)),
        ],
        None,
    ),
    "missed_last_week": (
        [session(weeks_ago(n), s("Bench Press", 80, 5)) for n in (2, 3, 4, 5)],
        None,
    ),
}


@pytest.fixture(scope="module")
def coach():
    return ClaudeCoach(anthropic.AsyncAnthropic(), "claude-opus-5-5")


@pytest.mark.parametrize("lang", ["en", "tr"])
@pytest.mark.parametrize("name", list(SCENARIOS))
async def test_scenario(coach, name, lang):
    sessions, expected_tone = SCENARIOS[name]
    stats = compute_weekly_stats(sessions, PROFILE, TODAY, UTC)

    report = await coach.write_report(stats, lang)
    text = " ".join([report.headline, *report.wins, *report.focus_areas, *report.next_week])

    assert ungrounded_numbers(report, stats) == []
    assert max(len(report.wins), len(report.focus_areas), len(report.next_week)) <= 3
    assert not MEDICAL.search(text), text
    if expected_tone:
        assert report.tone == expected_tone
    if name == "stalled_squat":
        assert "Barbell Squat" in text
    if name == "record_week":
        assert "Bench Press" in text or "Barbell Squat" in text
