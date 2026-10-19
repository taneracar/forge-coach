import pytest
from fastapi.testclient import TestClient

from app.auth import CurrentUser, current_user
from app.coach import CoachError, CoachUnavailable
from app.main import ReportCache, app, get_cache, get_coach, get_reader
from app.models import CoachReport, TrainingProfile
from app.reader import UpstreamError
from tests.factories import s, session

REPORT = CoachReport(headline="Solid week.", wins=[], focus_areas=[], next_week=[], tone="steady")


class FakeReader:
    def __init__(self, sessions=(), fail=False):
        self.sessions = list(sessions)
        self.fail = fail
        self.since = None

    async def sessions_since(self, user, since):
        if self.fail:
            raise UpstreamError("down")
        self.since = since
        return self.sessions

    async def profile(self, user):
        return TrainingProfile(preferred_training_days=3)


class FakeCoach:
    model = "fake-model"

    def __init__(self, error=None):
        self.calls = 0
        self.error = error

    async def write_report(self, stats, lang):
        self.calls += 1
        if self.error:
            raise self.error
        return REPORT, self.model


@pytest.fixture
def wire():
    def _wire(reader=None, coach=None, user=True):
        reader = reader or FakeReader()
        coach = coach or FakeCoach()
        app.dependency_overrides = {
            get_reader: lambda: reader,
            get_coach: lambda: coach,
            get_cache: lambda: cache,
        }
        if user:
            app.dependency_overrides[current_user] = lambda: CurrentUser("user-1", "token")
        return TestClient(app), reader, coach

    cache = ReportCache(ttl_seconds=60)
    yield _wire
    app.dependency_overrides = {}


def test_health(wire):
    client, *_ = wire()
    assert client.get("/health").json() == {"status": "ok"}


def test_requires_a_token(wire):
    client, *_ = wire(user=False)
    assert client.get("/v1/coach/weekly").status_code == 401


def test_returns_stats_and_report(wire):
    from datetime import date

    client, reader, coach = wire(reader=FakeReader([session(date.today(), s("Bench", 60, 5))]))
    body = client.get("/v1/coach/weekly", params={"tz": "America/Los_Angeles"}).json()
    assert body["report"]["headline"] == "Solid week."
    assert body["stats"]["target_sessions_per_week"] == 3
    assert body["model"] == "fake-model"
    assert body["cached"] is False
    assert reader.since.tzinfo is not None


def test_second_request_with_same_data_is_cached(wire):
    client, _, coach = wire()
    client.get("/v1/coach/weekly")
    second = client.get("/v1/coach/weekly").json()
    assert second["cached"] is True
    assert coach.calls == 1


def test_language_is_part_of_the_cache_key(wire):
    client, _, coach = wire()
    client.get("/v1/coach/weekly", params={"lang": "en"})
    client.get("/v1/coach/weekly", params={"lang": "tr"})
    assert coach.calls == 2


def test_rejects_unknown_language_and_time_zone(wire):
    client, *_ = wire()
    assert client.get("/v1/coach/weekly", params={"lang": "de"}).status_code == 422
    assert client.get("/v1/coach/weekly", params={"tz": "Mars/Base"}).status_code == 422


@pytest.mark.parametrize(
    "reader,coach,code",
    [
        (FakeReader(fail=True), None, 502),
        (None, FakeCoach(CoachUnavailable("busy")), 503),
        (None, FakeCoach(CoachError("bad")), 502),
    ],
)
def test_upstream_failures(wire, reader, coach, code):
    client, *_ = wire(reader=reader, coach=coach)
    assert client.get("/v1/coach/weekly").status_code == code


class FallingBackCoach(FakeCoach):
    async def write_report(self, stats, lang):
        self.calls += 1
        return REPORT, "rules-v1"


def test_fallback_reports_are_not_cached(wire):
    client, _, coach = wire(coach=FallingBackCoach())
    first = client.get("/v1/coach/weekly").json()
    client.get("/v1/coach/weekly")
    assert first["model"] == "rules-v1"
    assert coach.calls == 2
