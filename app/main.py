import hashlib
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anthropic
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.auth import CurrentUser, current_user
from app.coach import ClaudeCoach, Coach, CoachError, CoachUnavailable, Lang
from app.config import get_settings
from app.models import WeeklyCoachResponse
from app.reader import SupabaseReader, TrainingReader, UpstreamError
from app.stats import compute_weekly_stats, week_start


class ReportCache:
    """In-process cache keyed by user and by the exact statistics.

    New training changes the statistics and so the key; refreshing the page
    with nothing new reuses the last report instead of paying for another.
    """

    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._items: dict[str, tuple[float, WeeklyCoachResponse]] = {}

    def get(self, key: str) -> WeeklyCoachResponse | None:
        hit = self._items.get(key)
        if hit is None or hit[0] < time.monotonic():
            self._items.pop(key, None)
            return None
        return hit[1]

    def put(self, key: str, value: WeeklyCoachResponse) -> None:
        self._items[key] = (time.monotonic() + self._ttl, value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    async with httpx.AsyncClient() as http, anthropic.AsyncAnthropic() as claude:
        app.state.reader = SupabaseReader(http, settings.supabase_url, settings.supabase_anon_key)
        app.state.coach = ClaudeCoach(claude, settings.coach_model, settings.coach_effort)
        app.state.cache = ReportCache(settings.cache_ttl_seconds)
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="forge-coach", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
        allow_methods=["GET"],
        allow_headers=["Authorization"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/coach/weekly", response_model=WeeklyCoachResponse)
    async def weekly(
        user: Annotated[CurrentUser, Depends(current_user)],
        reader: Annotated[TrainingReader, Depends(get_reader)],
        coach: Annotated[Coach, Depends(get_coach)],
        cache: Annotated[ReportCache, Depends(get_cache)],
        lang: Lang = "en",
        tz: Annotated[str, Query(description="IANA time zone, e.g. America/Los_Angeles")] = "UTC",
    ) -> WeeklyCoachResponse:
        try:
            zone = ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown time zone"
            ) from None

        weeks = get_settings().history_weeks
        today = datetime.now(zone).date()
        since = datetime.combine(
            week_start(today) - timedelta(weeks=weeks - 1), datetime.min.time(), zone
        )

        try:
            sessions = await reader.sessions_since(user, since)
            profile = await reader.profile(user)
        except UpstreamError:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "Could not load training data"
            ) from None

        stats = compute_weekly_stats(sessions, profile, today, zone, weeks)
        key = hashlib.sha256(f"{user.id}|{lang}|{stats.model_dump_json()}".encode()).hexdigest()
        if cached := cache.get(key):
            return cached.model_copy(update={"cached": True})

        try:
            report = await coach.write_report(stats, lang)
        except CoachUnavailable as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
        except CoachError:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not write the report") from None

        result = WeeklyCoachResponse(stats=stats, report=report, model=coach.model, cached=False)
        cache.put(key, result)
        return result

    return app


def get_reader(request: Request) -> TrainingReader:
    return request.app.state.reader


def get_coach(request: Request) -> Coach:
    return request.app.state.coach


def get_cache(request: Request) -> ReportCache:
    return request.app.state.cache


app = create_app()
