import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx

from app.coach import CoachError, system_prompt
from app.models import CoachReport, TrainingProfile
from app.stats import compute_weekly_stats
from app.weekly_job import Member, SupabaseReportStore, last_finished_sunday, run
from tests.factories import s, session

# Monday morning, the week after 2026-10-19 to 2026-10-25.
MONDAY = datetime(2026, 10, 26, 12, tzinfo=UTC)
LAST_WEEK = date(2026, 10, 19)
MEMBER = Member("user-1", "en", "UTC")
REPORT = CoachReport(headline="h", wins=[], focus_areas=[], next_week=[], tone="steady")


class FakeStore:
    def __init__(self, members=(MEMBER,), existing=()):
        self._members = list(members)
        self.existing = set(existing)
        self.saved = []

    async def members(self):
        return self._members

    async def has_report(self, user_id, week):
        return (user_id, week) in self.existing

    async def save(self, user_id, week, lang, model, report):
        self.saved.append((user_id, week, lang, model, report))


class FakeReader:
    def __init__(self, sessions):
        self.sessions = sessions
        self.users = []

    async def sessions_since(self, user, since):
        self.users.append(user)
        return self.sessions

    async def profile(self, user):
        return TrainingProfile()


class FakeCoach:
    def __init__(self, fail_for=None):
        self.stats = []
        self._fail_for = fail_for

    async def write_report(self, stats, lang):
        self.stats.append(stats)
        if self._fail_for is not None and len(self.stats) == self._fail_for:
            raise CoachError("secret-user-number 87.5")
        return REPORT, "test-model"


def trained():
    return [session(date(2026, 10, 21), s("Bench Press", 80, 5))]


def test_last_finished_sunday_does_not_depend_on_the_run_day():
    assert last_finished_sunday(date(2026, 10, 26)) == date(2026, 10, 25)
    assert last_finished_sunday(date(2026, 10, 27)) == date(2026, 10, 25)
    assert last_finished_sunday(date(2026, 11, 1)) == date(2026, 10, 25)


async def test_reports_the_finished_week_and_saves_it():
    store, coach = FakeStore(), FakeCoach()
    reader = FakeReader(trained())

    assert await run(store, reader, coach, "service", MONDAY) == 0

    assert coach.stats[0].week_start == LAST_WEEK
    assert coach.stats[0].week_finished is True
    assert coach.stats[0].this_week.sessions == 1
    assert reader.users[0].id == "user-1"
    assert store.saved == [("user-1", LAST_WEEK, "en", "test-model", REPORT)]


async def test_a_session_from_the_new_week_is_left_out():
    sessions = [*trained(), session(date(2026, 10, 26), s("Bench Press", 200, 5), hour=6)]
    coach = FakeCoach()

    await run(FakeStore(), FakeReader(sessions), coach, "service", MONDAY)

    assert coach.stats[0].this_week.sessions == 1
    assert coach.stats[0].this_week.volume_kg == 400


async def test_the_week_follows_the_members_time_zone():
    # Still Sunday in Los Angeles, so the finished week is the one before.
    early = datetime(2026, 10, 26, 3, tzinfo=UTC)
    member = Member("user-1", "en", "America/Los_Angeles")
    coach = FakeCoach()

    sessions = [session(date(2026, 10, 14), s("Bench Press", 80, 5))]
    await run(FakeStore([member]), FakeReader(sessions), coach, "service", early)

    assert coach.stats[0].week_start == date(2026, 10, 12)


async def test_running_again_does_not_pay_for_a_second_report():
    store = FakeStore(existing={("user-1", LAST_WEEK)})
    coach = FakeCoach()

    assert await run(store, FakeReader(trained()), coach, "service", MONDAY) == 0

    assert coach.stats == []
    assert store.saved == []


async def test_a_member_with_no_history_gets_no_report():
    store, coach = FakeStore(), FakeCoach()

    assert await run(store, FakeReader([]), coach, "service", MONDAY) == 0

    assert coach.stats == []
    assert store.saved == []


async def test_one_failure_does_not_stop_the_others_and_is_reported(capsys):
    members = [MEMBER, Member("user-2", "tr", "UTC")]
    store = FakeStore(members)

    failed = await run(store, FakeReader(trained()), FakeCoach(fail_for=1), "service", MONDAY)

    assert failed == 1
    assert [row[0] for row in store.saved] == ["user-2"]
    assert "failed (CoachError)" in capsys.readouterr().out


async def test_an_unknown_time_zone_fails_only_that_member():
    members = [Member("user-1", "en", "Not/AZone"), Member("user-2", "tr", "UTC")]
    store = FakeStore(members)

    failed = await run(store, FakeReader(trained()), FakeCoach(), "service", MONDAY)

    assert failed == 1
    assert [row[0] for row in store.saved] == ["user-2"]


async def test_logs_carry_no_user_id_or_user_data(capsys):
    members = [Member("user-secret-id", "en", "UTC"), Member("user-other-id", "en", "UTC")]

    await run(FakeStore(members), FakeReader(trained()), FakeCoach(fail_for=1), "svc", MONDAY)

    out = capsys.readouterr().out
    assert "user-secret-id" not in out
    assert "user-other-id" not in out
    assert "87.5" not in out


async def test_the_store_speaks_postgrest_with_the_service_key():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(201)
        if "premium_members" in request.url.path:
            return httpx.Response(
                200, json=[{"user_id": "u1", "lang": "tr", "time_zone": "Europe/Istanbul"}]
            )
        return httpx.Response(200, json=[{"user_id": "u1"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = SupabaseReportStore(client, "https://example.supabase.co/", "service-key")
        assert await store.members() == [Member("u1", "tr", "Europe/Istanbul")]
        assert await store.has_report("u1", LAST_WEEK) is True
        await store.save("u1", LAST_WEEK, "tr", "m", REPORT)

    assert all(r.headers["apikey"] == "service-key" for r in seen)
    assert seen[1].url.params["user_id"] == "eq.u1"
    assert seen[1].url.params["week_start"] == "eq.2026-10-19"
    assert seen[2].url.params["on_conflict"] == "user_id,week_start"
    assert "ignore-duplicates" in seen[2].headers["prefer"]
    body = json.loads(seen[2].content)
    assert body["user_id"] == "u1"
    assert body["report"]["headline"] == "h"


def test_a_finished_empty_week_breaks_the_streak_but_a_running_one_does_not():
    zone = ZoneInfo("UTC")
    sessions = [session(date(2026, 10, 14), s("Bench Press", 80, 5))]
    sunday = date(2026, 10, 25)

    running = compute_weekly_stats(sessions, TrainingProfile(), sunday, zone)
    finished = compute_weekly_stats(sessions, TrainingProfile(), sunday, zone, week_finished=True)

    assert running.training_streak_weeks == 1
    assert finished.training_streak_weeks == 0


def test_the_prompt_treats_a_finished_week_differently():
    assert "week_finished is true" in system_prompt("en")
    assert "Never suggest adding sessions" in system_prompt("en").replace("\\\n", "")
