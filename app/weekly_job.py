"""Writes last week's report for every premium member.

GitHub Actions runs this on Monday (`python -m app.weekly_job`). It is the only
code that holds the service-role key, which bypasses Row Level Security, so it
reads just the users listed in `premium_members` and filters every query by
user id. Running it again for the same week changes nothing.

The repository is public and so are its workflow logs: nothing printed here may
identify a user or carry their data, including error messages.
"""

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anthropic
import httpx

from app.auth import CurrentUser
from app.coach import ClaudeCoach, Coach, CoachError, CoachUnavailable, Lang
from app.models import CoachReport
from app.reader import SupabaseReader, TrainingReader, UpstreamError
from app.stats import compute_weekly_stats, week_start

HISTORY_WEEKS = 8
DEFAULT_MODEL = "claude-opus-5-5"


@dataclass(frozen=True)
class Member:
    user_id: str
    lang: Lang
    time_zone: str


class ReportStore(Protocol):
    async def members(self) -> list[Member]: ...

    async def has_report(self, user_id: str, week: date) -> bool: ...

    async def save(
        self, user_id: str, week: date, lang: Lang, model: str, report: CoachReport
    ) -> None: ...


class SupabaseReportStore:
    def __init__(self, client: httpx.AsyncClient, supabase_url: str, service_key: str):
        self._client = client
        self._rest = f"{supabase_url.rstrip('/')}/rest/v1"
        self._headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        try:
            r = await self._client.request(
                method, f"{self._rest}/{path}", headers=headers, timeout=10, **kwargs
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise UpstreamError(f"Supabase request to {path} failed") from e
        return r

    async def members(self) -> list[Member]:
        r = await self._request(
            "GET",
            "premium_members",
            params={"select": "user_id,lang,time_zone", "order": "granted_at.asc"},
        )
        return [Member(**row) for row in r.json()]

    async def has_report(self, user_id: str, week: date) -> bool:
        r = await self._request(
            "GET",
            "weekly_reports",
            params={
                "select": "user_id",
                "user_id": f"eq.{user_id}",
                "week_start": f"eq.{week.isoformat()}",
            },
        )
        return bool(r.json())

    async def save(
        self, user_id: str, week: date, lang: Lang, model: str, report: CoachReport
    ) -> None:
        await self._request(
            "POST",
            "weekly_reports",
            params={"on_conflict": "user_id,week_start"},
            headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
            json={
                "user_id": user_id,
                "week_start": week.isoformat(),
                "lang": lang,
                "model": model,
                "report": report.model_dump(mode="json"),
            },
        )


def last_finished_sunday(today: date) -> date:
    return week_start(today) - timedelta(days=1)


async def write_member_report(
    member: Member,
    token: str,
    now: datetime,
    store: ReportStore,
    reader: TrainingReader,
    coach: Coach,
) -> str:
    zone = ZoneInfo(member.time_zone)
    sunday = last_finished_sunday(now.astimezone(zone).date())
    week = week_start(sunday)

    if await store.has_report(member.user_id, week):
        return "already written"

    user = CurrentUser(id=member.user_id, token=token)
    first_week = week - timedelta(weeks=HISTORY_WEEKS - 1)
    since = datetime.combine(first_week, datetime.min.time(), zone)
    sessions = await reader.sessions_since(user, since)
    profile = await reader.profile(user)

    stats = compute_weekly_stats(sessions, profile, sunday, zone, HISTORY_WEEKS, week_finished=True)
    if not stats.has_training:
        return "no training history"

    report, model = await coach.write_report(stats, member.lang)
    await store.save(member.user_id, week, member.lang, model, report)
    return "written"


async def run(
    store: ReportStore, reader: TrainingReader, coach: Coach, token: str, now: datetime
) -> int:
    """Returns how many members failed. One failure never stops the others."""
    members = await store.members()
    failed = 0
    for number, member in enumerate(members, start=1):
        try:
            outcome = await write_member_report(member, token, now, store, reader, coach)
        except (
            CoachError,
            CoachUnavailable,
            UpstreamError,
            ZoneInfoNotFoundError,
            ValueError,
        ) as e:
            # The type only: messages can hold a user's numbers or id.
            outcome = f"failed ({type(e).__name__})"
            failed += 1
        print(f"Member {number} of {len(members)}: {outcome}")
    return failed


async def main() -> int:
    supabase_url = os.environ["SUPABASE_URL"]
    service_key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    model = os.environ.get("COACH_MODEL", DEFAULT_MODEL)

    async with (
        httpx.AsyncClient() as http,
        anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"]) as claude,
    ):
        store = SupabaseReportStore(http, supabase_url, service_key)
        reader = SupabaseReader(http, supabase_url, service_key)
        coach = ClaudeCoach(claude, model)
        failed = await run(store, reader, coach, service_key, datetime.now().astimezone())
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
