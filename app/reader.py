"""Reads a user's training history from Supabase.

Requests go through PostgREST with the caller's own access token, so the
database's Row Level Security policies decide what comes back. The service
holds no database password and cannot read another user's rows even if a
query here were wrong.
"""

from datetime import datetime
from typing import Protocol

import httpx

from app.auth import CurrentUser
from app.models import LoggedSession, LoggedSet, TrainingProfile

SESSION_SELECT = (
    "id,started_at,completed_at,duration_seconds,"
    "workout_sets(exercise_id,weight,reps,completed,exercises(name,muscle_group))"
)


class TrainingReader(Protocol):
    async def sessions_since(self, user: CurrentUser, since: datetime) -> list[LoggedSession]: ...

    async def profile(self, user: CurrentUser) -> TrainingProfile: ...


class UpstreamError(Exception):
    pass


class SupabaseReader:
    def __init__(self, client: httpx.AsyncClient, supabase_url: str, anon_key: str):
        self._client = client
        self._rest = f"{supabase_url.rstrip('/')}/rest/v1"
        self._anon_key = anon_key

    def _headers(self, user: CurrentUser) -> dict[str, str]:
        return {"apikey": self._anon_key, "Authorization": f"Bearer {user.token}"}

    async def _get(self, user: CurrentUser, path: str, params: dict[str, str]) -> list[dict]:
        try:
            r = await self._client.get(
                f"{self._rest}/{path}", params=params, headers=self._headers(user), timeout=10
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise UpstreamError(f"Supabase request to {path} failed") from e
        return r.json()

    async def sessions_since(self, user: CurrentUser, since: datetime) -> list[LoggedSession]:
        rows = await self._get(
            user,
            "workout_sessions",
            {
                "select": SESSION_SELECT,
                "user_id": f"eq.{user.id}",
                "completed_at": "not.is.null",
                "started_at": f"gte.{since.isoformat()}",
                "order": "started_at.asc",
            },
        )
        return [_session(row) for row in rows]

    async def profile(self, user: CurrentUser) -> TrainingProfile:
        rows = await self._get(
            user,
            "profiles",
            {"select": "goal,workout_experience,preferred_training_days", "id": f"eq.{user.id}"},
        )
        return TrainingProfile(**rows[0]) if rows else TrainingProfile()


def _session(row: dict) -> LoggedSession:
    sets = []
    for st in row.get("workout_sets") or []:
        ex = st.get("exercises") or {}
        sets.append(
            LoggedSet(
                exercise_id=st["exercise_id"],
                exercise_name=ex.get("name") or "Unknown exercise",
                muscle_group=ex.get("muscle_group") or "other",
                weight_kg=float(st["weight"]) if st.get("weight") is not None else None,
                reps=st.get("reps"),
                completed=bool(st.get("completed")),
            )
        )
    return LoggedSession(
        id=row["id"],
        started_at=row["started_at"],
        completed_at=row.get("completed_at"),
        duration_seconds=row.get("duration_seconds"),
        sets=sets,
    )
