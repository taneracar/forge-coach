"""Domain types shared by the reader, the statistics, and the coach.

Everything the model sees is a `WeeklyStats`; everything it returns is a
`CoachReport`. The two are kept apart so the numbers always come from code.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- input data


class LoggedSet(BaseModel):
    exercise_id: str
    exercise_name: str
    muscle_group: str
    weight_kg: float | None
    reps: int | None
    completed: bool


class LoggedSession(BaseModel):
    id: str
    started_at: datetime
    completed_at: datetime | None
    duration_seconds: int | None
    sets: list[LoggedSet]


class TrainingProfile(BaseModel):
    goal: str | None = None
    workout_experience: str | None = None
    preferred_training_days: int | None = None


# ---------------------------------------------------------------- statistics


class WeekSummary(BaseModel):
    week_start: date
    sessions: int
    completed_sets: int
    volume_kg: float


class PersonalRecord(BaseModel):
    exercise: str
    estimated_1rm_kg: float
    previous_best_kg: float | None
    weight_kg: float
    reps: int


class StalledLift(BaseModel):
    exercise: str
    best_estimated_1rm_kg: float
    weeks_without_progress: int


class WeeklyStats(BaseModel):
    week_start: date
    this_week: WeekSummary
    previous_weeks: list[WeekSummary]
    volume_change_pct: float | None
    sets_by_muscle_group: dict[str, int]
    personal_records: list[PersonalRecord]
    stalled_lifts: list[StalledLift]
    training_streak_weeks: int
    target_sessions_per_week: int | None
    goal: str | None
    experience: str | None

    @property
    def has_training(self) -> bool:
        return self.this_week.sessions > 0 or any(w.sessions for w in self.previous_weeks)


# ---------------------------------------------------------------- model output


class CoachReport(BaseModel):
    headline: str = Field(description="One sentence that sums up the week.")
    wins: list[str] = Field(description="Up to 3 concrete things that went well.")
    focus_areas: list[str] = Field(description="Up to 3 things to work on next week.")
    next_week: list[str] = Field(description="Up to 3 specific actions for next week.")
    tone: Literal["celebrate", "steady", "nudge", "welcome"] = Field(
        description="celebrate: records or clear progress; steady: on track; "
        "nudge: fewer sessions than planned; welcome: little or no history yet."
    )


class WeeklyCoachResponse(BaseModel):
    stats: WeeklyStats
    report: CoachReport
    model: str
    cached: bool
