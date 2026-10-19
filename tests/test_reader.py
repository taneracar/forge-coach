from datetime import UTC, datetime

import httpx
import pytest

from app.auth import CurrentUser
from app.reader import SupabaseReader, UpstreamError

USER = CurrentUser(id="user-1", token="user-token")


def reader(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SupabaseReader(client, "https://example.supabase.co/", "anon-key")


async def test_reads_sessions_with_the_users_own_token():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = request.url
        seen["headers"] = request.headers
        return httpx.Response(
            200,
            json=[
                {
                    "id": "s1",
                    "started_at": "2026-10-20T18:00:00+00:00",
                    "completed_at": "2026-10-20T19:00:00+00:00",
                    "duration_seconds": 3600,
                    "workout_sets": [
                        {
                            "exercise_id": "e1",
                            "weight": "62.5",
                            "reps": 8,
                            "completed": True,
                            "exercises": {"name": "Bench Press", "muscle_group": "chest"},
                        },
                        {"exercise_id": "e2", "weight": None, "reps": 15, "completed": False},
                    ],
                }
            ],
        )

    [session] = await reader(handler).sessions_since(USER, datetime(2026, 9, 1, tzinfo=UTC))

    assert seen["url"].path == "/rest/v1/workout_sessions"
    assert seen["url"].params["user_id"] == "eq.user-1"
    assert seen["url"].params["completed_at"] == "not.is.null"
    assert seen["headers"]["authorization"] == "Bearer user-token"
    assert seen["headers"]["apikey"] == "anon-key"

    bench, unknown = session.sets
    assert bench.weight_kg == 62.5 and bench.exercise_name == "Bench Press"
    assert unknown.weight_kg is None and unknown.muscle_group == "other"


async def test_profile_defaults_when_missing():
    profile = await reader(lambda r: httpx.Response(200, json=[])).profile(USER)
    assert profile.preferred_training_days is None


async def test_upstream_failure_is_wrapped():
    with pytest.raises(UpstreamError):
        await reader(lambda r: httpx.Response(500)).profile(USER)
