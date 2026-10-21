from datetime import UTC
from types import SimpleNamespace

import pytest

from app.coach import CoachError, FallbackCoach
from app.local import LocalCoach
from app.main import build_coach
from app.models import CoachReport, TrainingProfile
from app.rules import RuleCoach
from app.stats import compute_weekly_stats
from tests.factories import TODAY, s, session, weeks_ago


@pytest.fixture
def stats():
    return compute_weekly_stats(
        [
            session(weeks_ago(1), s("Bench Press", 60, 5)),
            session(TODAY, s("Bench Press", 65, 5)),
        ],
        TrainingProfile(goal="build_muscle"),
        TODAY,
        UTC,
    )


def raw(*wins: str, tone="steady") -> str:
    r = CoachReport(
        headline="Solid week.", wins=list(wins), focus_areas=[], next_week=[], tone=tone
    )
    return "<think>\n\n</think>\n\n" + r.model_dump_json()


class Scripted:
    """Returns the given outputs in order and records each temperature."""

    def __init__(self, *outputs: str):
        self.outputs = list(outputs)
        self.temperatures = []

    def __call__(self, system, user, temperature):
        self.temperatures.append(temperature)
        return self.outputs.pop(0)


async def test_returns_a_report_that_passes_the_checks(stats):
    gen = Scripted(raw("Bench Press went up."))
    report, model = await LocalCoach(gen, "local:test").write_report(stats, "en")
    assert report.wins == ["Bench Press went up."]
    assert model == "local:test"
    assert gen.temperatures == [0.0]


async def test_retries_with_sampling_after_a_failed_check(stats):
    gen = Scripted(raw("Volume up 140%."), raw("Bench Press went up."))
    report, _ = await LocalCoach(gen, "local:test").write_report(stats, "en")
    assert report.wins == ["Bench Press went up."]
    assert gen.temperatures == [0.0, 0.7]


@pytest.mark.parametrize(
    "bad",
    [
        raw("Volume up 140%."),  # invented number
        raw("Great for your strength goal."),  # wrong goal
        raw("a", "b", "c", "d"),  # too many items
        raw("Cut calories this week."),  # diet advice
        "not json at all",
    ],
)
async def test_gives_up_after_two_bad_reports(stats, bad):
    gen = Scripted(bad, bad)
    with pytest.raises(CoachError):
        await LocalCoach(gen, "local:test").write_report(stats, "en")


async def test_rule_coach_answers_when_the_local_model_fails(stats):
    coach = FallbackCoach(LocalCoach(Scripted("junk", "junk"), "local:test"), RuleCoach())
    report, model = await coach.write_report(stats, "en")
    assert model == "rules-v1"
    assert report.tone == "celebrate"


def settings(**kw):
    base = dict(
        anthropic_api_key=None,
        coach_model="claude-opus-5-5",
        coach_effort="low",
        local_coach_adapter=None,
        local_coach_base="base",
    )
    return SimpleNamespace(**{**base, **kw})


def test_build_coach_layers(monkeypatch):
    monkeypatch.setattr("app.local.mlx_generator", lambda base, adapter: Scripted())
    assert isinstance(build_coach(settings(), None), RuleCoach)

    local = build_coach(settings(local_coach_adapter="training/adapters/labels-v2"), None)
    assert local.model == "local:labels-v2"

    both = build_coach(
        settings(anthropic_api_key="k", local_coach_adapter="training/adapters/labels-v2"), None
    )
    assert both.model == "claude-opus-5-5"
    assert both._fallback.model == "local:labels-v2"
