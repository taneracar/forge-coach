from datetime import UTC
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.coach import ClaudeCoach, CoachError, CoachUnavailable, ungrounded_numbers
from app.models import CoachReport, TrainingProfile
from app.stats import compute_weekly_stats
from tests.factories import TODAY, s, session, weeks_ago


@pytest.fixture
def stats():
    return compute_weekly_stats(
        [
            session(weeks_ago(1), s("Bench Press", 60, 5)),
            session(TODAY, s("Bench Press", 65, 5), s("Bench Press", 65, 5)),
        ],
        TrainingProfile(preferred_training_days=4),
        TODAY,
        UTC,
    )


def report(*sentences: str, headline="Good week.") -> CoachReport:
    return CoachReport(
        headline=headline, wins=list(sentences), focus_areas=[], next_week=[], tone="steady"
    )


def test_numbers_from_the_stats_are_grounded(stats):
    # 65 kg x 5 is a record, estimated 75.8 vs 70.0; volume 650 vs 300.
    r = report("New best on Bench Press: 65 kg for 5, an estimated 75.8 kg.", "Volume 650 kg.")
    assert ungrounded_numbers(r, stats) == []


def test_small_counts_and_plate_jumps_are_allowed(stats):
    assert ungrounded_numbers(report("Add 2.5 kg and aim for 4 sessions."), stats) == []


def test_invented_numbers_are_caught(stats):
    r = report("Your volume went up 140% to 712 kg.")
    assert ungrounded_numbers(r, stats) == ["140", "712"]


def test_turkish_decimal_comma_is_understood(stats):
    assert ungrounded_numbers(report("Tahmini 75,8 kg."), stats) == []
    assert ungrounded_numbers(report("Tahmini 81,3 kg."), stats) == ["81,3"]


class FakeMessages:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def ok(r: CoachReport, stop_reason="end_turn"):
    return SimpleNamespace(parsed_output=r, stop_reason=stop_reason)


def coach_with(*outcomes):
    messages = FakeMessages(*outcomes)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return ClaudeCoach(client, "claude-opus-5-5"), messages


async def test_returns_a_grounded_report(stats):
    coach, messages = coach_with(ok(report("Bench Press is moving.")))
    result, model = await coach.write_report(stats, "tr")
    assert model == "claude-opus-5-5"
    assert result.wins == ["Bench Press is moving."]
    [call] = messages.calls
    assert call["output_format"] is CoachReport
    assert "Turkish" in call["system"]
    assert '"volume_kg": 650.0' in call["messages"][0]["content"]


async def test_retries_once_when_a_number_is_invented(stats):
    coach, messages = coach_with(ok(report("Up 140%.")), ok(report("Bench Press went up.")))
    result, _ = await coach.write_report(stats, "en")
    assert result.wins == ["Bench Press went up."]
    correction = messages.calls[1]["messages"][-1]["content"]
    assert "140" in correction


async def test_gives_up_after_a_second_invented_number(stats):
    coach, _ = coach_with(ok(report("Up 140%.")), ok(report("Up 141%.")))
    with pytest.raises(CoachError):
        await coach.write_report(stats, "en")


async def test_refusal_is_an_error(stats):
    coach, _ = coach_with(ok(None, stop_reason="refusal"))
    with pytest.raises(CoachError):
        await coach.write_report(stats, "en")


async def test_rate_limit_is_temporary(stats):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.RateLimitError(
        "slow down", response=httpx.Response(429, request=request), body=None
    )
    coach, _ = coach_with(error)
    with pytest.raises(CoachUnavailable):
        await coach.write_report(stats, "en")
