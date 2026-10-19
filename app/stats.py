"""Training statistics, computed in plain Python.

The coach never does arithmetic. Every number in a report is produced here,
tested here, and handed to the model as data to talk about.

Weeks start on Monday in the user's own time zone, so a late Sunday session
in Los Angeles is not counted as Monday's.
"""

from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from app.models import (
    LoggedSession,
    PersonalRecord,
    StalledLift,
    TrainingProfile,
    WeeklyStats,
    WeekSummary,
)

# Epley's estimate drifts badly past about a dozen reps, so higher-rep sets
# are left out of strength comparisons (they still count toward volume).
MAX_REPS_FOR_1RM = 12

# A lift is "stalled" once its best estimate is this many weeks old, and only
# if it has been trained since then.
STALL_WEEKS = 3


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def estimated_1rm(weight_kg: float, reps: int) -> float:
    if reps == 1:
        return weight_kg
    return weight_kg * (1 + reps / 30)


def _r(x: float) -> float:
    return round(x, 1)


def compute_weekly_stats(
    sessions: list[LoggedSession],
    profile: TrainingProfile,
    today: date,
    tz: ZoneInfo,
    history_weeks: int = 8,
) -> WeeklyStats:
    current = week_start(today)
    weeks = [current - timedelta(weeks=i) for i in range(history_weeks - 1, -1, -1)]
    first_week = weeks[0]

    by_week: dict[date, list[LoggedSession]] = defaultdict(list)
    for s in sessions:
        if s.completed_at is None:
            continue
        wk = week_start(s.started_at.astimezone(tz).date())
        if first_week <= wk <= current:
            by_week[wk].append(s)

    summaries = [_summarize(wk, by_week[wk]) for wk in weeks]
    this_week, previous = summaries[-1], summaries[:-1]

    last_week = previous[-1] if previous else None
    volume_change = None
    if last_week and last_week.volume_kg > 0:
        volume_change = _r((this_week.volume_kg - last_week.volume_kg) / last_week.volume_kg * 100)

    muscle_sets: dict[str, int] = defaultdict(int)
    for s in by_week[current]:
        for st in s.sets:
            if st.completed:
                muscle_sets[st.muscle_group] += 1

    # Best estimated 1RM per exercise per week, plus the set that produced it.
    best: dict[str, dict[date, tuple[float, float, int]]] = defaultdict(dict)
    names: dict[str, str] = {}
    for wk, week_sessions in by_week.items():
        for s in week_sessions:
            for st in s.sets:
                if not (st.completed and st.weight_kg and st.reps):
                    continue
                if st.weight_kg <= 0 or not 1 <= st.reps <= MAX_REPS_FOR_1RM:
                    continue
                e = estimated_1rm(st.weight_kg, st.reps)
                names[st.exercise_id] = st.exercise_name
                prev = best[st.exercise_id].get(wk)
                if prev is None or e > prev[0]:
                    best[st.exercise_id][wk] = (e, st.weight_kg, st.reps)

    records: list[PersonalRecord] = []
    stalled: list[StalledLift] = []
    for ex_id, per_week in best.items():
        earlier = [v[0] for wk, v in per_week.items() if wk < current]
        if current in per_week and earlier:
            e, w, reps = per_week[current]
            if e > max(earlier):
                records.append(
                    PersonalRecord(
                        exercise=names[ex_id],
                        estimated_1rm_kg=_r(e),
                        previous_best_kg=_r(max(earlier)),
                        weight_kg=w,
                        reps=reps,
                    )
                )

        best_week = max(per_week, key=lambda wk: (per_week[wk][0], -wk.toordinal()))
        weeks_since = (current - best_week).days // 7
        trained_after = sum(1 for wk in per_week if wk > best_week)
        recently = current in per_week or (current - timedelta(weeks=1)) in per_week
        if weeks_since >= STALL_WEEKS and trained_after >= 2 and recently:
            stalled.append(
                StalledLift(
                    exercise=names[ex_id],
                    best_estimated_1rm_kg=_r(per_week[best_week][0]),
                    weeks_without_progress=weeks_since,
                )
            )

    return WeeklyStats(
        week_start=current,
        this_week=this_week,
        previous_weeks=previous,
        volume_change_pct=volume_change,
        sets_by_muscle_group=dict(sorted(muscle_sets.items(), key=lambda kv: (-kv[1], kv[0]))),
        personal_records=sorted(records, key=lambda r: -r.estimated_1rm_kg),
        stalled_lifts=sorted(stalled, key=lambda s: -s.weeks_without_progress),
        training_streak_weeks=_streak(summaries),
        target_sessions_per_week=profile.preferred_training_days,
        goal=profile.goal,
        experience=profile.workout_experience,
    )


def _summarize(wk: date, sessions: list[LoggedSession]) -> WeekSummary:
    sets = [st for s in sessions for st in s.sets if st.completed]
    volume = sum((st.weight_kg or 0) * (st.reps or 0) for st in sets)
    return WeekSummary(
        week_start=wk, sessions=len(sessions), completed_sets=len(sets), volume_kg=_r(volume)
    )


def _streak(summaries: list[WeekSummary]) -> int:
    """Consecutive weeks with at least one session, ending now.

    The current week is still in progress, so an empty one does not break the
    streak; counting simply starts from last week.
    """
    weeks = list(summaries)
    if weeks and weeks[-1].sessions == 0:
        weeks.pop()
    streak = 0
    for w in reversed(weeks):
        if w.sessions == 0:
            break
        streak += 1
    return streak
