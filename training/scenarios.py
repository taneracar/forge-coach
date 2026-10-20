"""Synthetic training histories for building the coach dataset.

Each scenario is a lifter archetype (new user, steady progress, stalled lift,
missed week, comeback, ...) turned into eight weeks of logged sessions with a
seeded random generator, so the same seed always gives the same example. The
sessions go through the real `compute_weekly_stats`, so the model is trained on
exactly the input it will see in production.
"""

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.models import LoggedSession, LoggedSet, TrainingProfile, WeeklyStats
from app.stats import compute_weekly_stats, week_start

# (name, muscle group, starting kg for a beginner, reps per set)
EXERCISES = [
    ("Barbell Bench Press", "chest", 40, 8),
    ("Incline Dumbbell Press", "chest", 14, 10),
    ("Barbell Squat", "legs", 50, 5),
    ("Romanian Deadlift", "legs", 50, 8),
    ("Leg Press", "legs", 80, 10),
    ("Deadlift", "back", 60, 5),
    ("Barbell Row", "back", 40, 8),
    ("Lat Pulldown", "back", 35, 10),
    ("Overhead Press", "shoulders", 25, 6),
    ("Lateral Raise", "shoulders", 6, 12),
    ("Barbell Curl", "arms", 20, 10),
    ("Triceps Pushdown", "arms", 20, 12),
    ("Pull Up", "back", None, 8),
    ("Push Up", "chest", None, 15),
]

ARCHETYPES = [
    "new_user",
    "first_week",
    "steady_progress",
    "record_week",
    "stalled_lift",
    "missed_last_week",
    "comeback",
    "volume_drop",
    "inconsistent",
    "early_week",
]

GOALS = ["build_muscle", "get_stronger", "lose_fat", "stay_fit", None]
LEVELS = ["beginner", "intermediate", "advanced", None]


@dataclass
class Scenario:
    id: str
    archetype: str
    today: date
    profile: TrainingProfile
    sessions: list[LoggedSession]

    def stats(self) -> WeeklyStats:
        return compute_weekly_stats(self.sessions, self.profile, self.today, UTC)


def _round_plate(kg: float) -> float:
    return max(2.5, round(kg / 2.5) * 2.5)


def generate(seed: int) -> Scenario:
    rng = random.Random(seed)
    archetype = ARCHETYPES[seed % len(ARCHETYPES)]

    # Any day of the week, so "this week" is sometimes one day old, sometimes six.
    today = date(2026, 6, 1) + timedelta(days=rng.randrange(0, 120))
    if archetype == "early_week":
        today = week_start(today)
    current = week_start(today)

    level = rng.choice(LEVELS)
    target = rng.choice([2, 3, 3, 4, 4, 5, None])
    profile = TrainingProfile(
        goal=rng.choice(GOALS), workout_experience=level, preferred_training_days=target
    )
    strength = {"beginner": 1.0, "intermediate": 1.6, "advanced": 2.2}.get(level or "", 1.3)

    if archetype == "new_user":
        return Scenario(f"s{seed:04d}", archetype, today, profile, [])

    exercises = rng.sample(EXERCISES, rng.randint(4, 7))
    stalled = exercises[0][0] if archetype == "stalled_lift" else None
    # Chance that a lift goes up one plate in a given trained week.
    p_up = {"beginner": 0.55, "intermediate": 0.3, "advanced": 0.15}.get(level or "", 0.35)
    # How quickly this archetype progresses compared with a steady lifter.
    pace = {
        "steady_progress": 1.0,
        "record_week": 0.4,
        "stalled_lift": 0.15,
        "missed_last_week": 0.5,
        "volume_drop": 0.25,
        "inconsistent": 0.4,
        "early_week": 0.5,
    }.get(archetype, 1.0)
    p_up *= pace
    p_reps = 0.25 * pace

    # Sessions per week, oldest to newest (index 7 is the current week).
    base = target or 3
    plan = [max(1, base + rng.choice([-1, 0, 0, 0, 1])) for _ in range(8)]
    history_start = rng.randint(0, 4)
    if archetype == "first_week":
        history_start = 7
    elif archetype == "missed_last_week":
        plan[6] = rng.choice([0, 1])
    elif archetype == "comeback":
        gap = rng.randint(2, 3)
        for w in range(7 - gap, 7):
            plan[w] = 0
    elif archetype == "inconsistent":
        plan = [rng.choice([0, 1, 1, 2, 3]) for _ in range(8)]
    elif archetype == "volume_drop":
        plan[7] = plan[6]

    # Working weight and reps per exercise, carried from week to week.
    state = {
        name: [_round_plate(start * strength) if start else None, reps]
        for name, _, start, reps in exercises
    }
    trained_weeks = 0
    was_off = False

    days_so_far = (today - current).days + 1
    sessions: list[LoggedSession] = []
    for w in range(history_start, 8):
        monday = current - timedelta(weeks=7 - w)
        count = plan[w]
        if w == 7:
            count = min(count, days_so_far)
            if archetype == "early_week":
                count = rng.choice([0, 1])
        if count == 0:
            was_off = trained_weeks > 0
            continue

        for name, _, _, base_reps in exercises:
            weight, reps = state[name]
            if weight is None:
                state[name][1] = base_reps + rng.choice([-1, 0, 1])
                continue
            if was_off:
                # Back after a break: drop the load a little.
                state[name][0] = _round_plate(weight * rng.uniform(0.85, 0.95))
            elif name == stalled and trained_weeks >= 2:
                state[name][1] = base_reps - rng.choice([0, 0, 1])
            elif (
                trained_weeks
                and rng.random() < p_up
                and not (archetype == "volume_drop" and w == 7)
            ):
                state[name] = [weight + 2.5, base_reps]
            elif archetype == "volume_drop" and w == 7:
                pass
            elif trained_weeks and rng.random() < p_reps:
                state[name][1] = min(base_reps + 2, reps + 1)
        if archetype == "record_week" and w == 7:
            for name in rng.sample([e[0] for e in exercises if e[2]], 2):
                state[name][0] += rng.choice([2.5, 5.0])
        was_off = False
        trained_weeks += 1

        days = sorted(rng.sample(range(7 if w < 7 else days_so_far), min(count, 7)))
        for d in days:
            day = monday + timedelta(days=d)
            picks = rng.sample(exercises, min(len(exercises), rng.randint(3, 4)))
            sets = []
            for name, muscle, _, _ in picks:
                weight, reps = state[name]
                n_sets = rng.choice([3, 3, 4])
                if archetype == "volume_drop" and w == 7:
                    n_sets = 2
                for _ in range(n_sets):
                    sets.append(
                        LoggedSet(
                            exercise_id=name.lower().replace(" ", "-"),
                            exercise_name=name,
                            muscle_group=muscle,
                            weight_kg=weight,
                            reps=reps,
                            completed=rng.random() > 0.05,
                        )
                    )
            start_at = datetime.combine(day, time(rng.choice([6, 7, 12, 17, 18, 19])), UTC)
            sessions.append(
                LoggedSession(
                    id=f"s{seed:04d}-{w}-{d}",
                    started_at=start_at,
                    completed_at=start_at + timedelta(minutes=rng.randint(40, 90)),
                    duration_seconds=None,
                    sets=sets,
                )
            )
    return Scenario(f"s{seed:04d}", archetype, today, profile, sessions)
