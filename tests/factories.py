from datetime import UTC, date, datetime, time, timedelta
from itertools import count

from app.models import LoggedSession, LoggedSet

_ids = count(1)

# Monday 2026-10-19 is the "current" week in most tests.
TODAY = date(2026, 10, 21)
THIS_MONDAY = date(2026, 10, 19)


def s(exercise: str, weight: float | None, reps: int | None, *, muscle="chest", done=True):
    return LoggedSet(
        exercise_id=exercise.lower().replace(" ", "-"),
        exercise_name=exercise,
        muscle_group=muscle,
        weight_kg=weight,
        reps=reps,
        completed=done,
    )


def session(day: date, *sets: LoggedSet, hour: int = 18, completed: bool = True, tz=UTC):
    start = datetime.combine(day, time(hour), tzinfo=tz)
    return LoggedSession(
        id=f"s{next(_ids)}",
        started_at=start,
        completed_at=start + timedelta(hours=1) if completed else None,
        duration_seconds=3600 if completed else None,
        sets=list(sets),
    )


def weeks_ago(n: int, weekday: int = 0) -> date:
    return THIS_MONDAY - timedelta(weeks=n) + timedelta(days=weekday)
