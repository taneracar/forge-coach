"""A coach that needs no language model.

Builds the same `CoachReport` from fixed sentences filled with numbers from
the statistics. It costs nothing, never invents a figure, and is what the
service falls back to when Claude is not configured or not reachable.
"""

from app.coach import Lang
from app.models import CoachReport, WeeklyStats

MODEL_NAME = "rules-v1"

T = {
    "en": {
        "welcome_head": "Welcome to your weekly coach.",
        "welcome_win": "Your account is set up and ready to track training.",
        "welcome_focus": "Log a few sessions so the coach has something to compare.",
        "welcome_next": "Finish one workout this week and check back here.",
        "celebrate_head": "New personal records this week.",
        "nudge_head": "Last week you trained {done} of your {target} planned days.",
        "steady_head": "{sessions} sessions so far this week, {volume} kg lifted.",
        "steady_head_empty": "No sessions yet this week, but the week is still open.",
        "pr": "{exercise}: {weight} kg for {reps}, an estimated 1RM of {e1rm} kg "
        "(previous best {prev} kg).",
        "volume_up": "Volume is up {pct}% on last week.",
        "volume_down": "Volume is down {pct}% on last week.",
        "streak": "{weeks} weeks in a row with at least one session.",
        "stalled": "{exercise} has not improved for {weeks} weeks (best estimate {e1rm} kg).",
        "stalled_next": "For {exercise}, switch to a new rep range, for example 8 to 10 reps, "
        "for the next 3 weeks.",
        "pr_next": "Keep the plan for {exercise} and add 2.5 kg once every set feels solid.",
        "target_next": "Plan {target} sessions and put them in your calendar now.",
        "default_next": "Aim for at least 3 sessions next week.",
        "consistency_focus": "Consistency first: fewer sessions than planned last week.",
        "no_focus": "Nothing is holding you back right now. Keep the same routine.",
    },
    "tr": {
        "welcome_head": "Haftalık koçuna hoş geldin.",
        "welcome_win": "Hesabın hazır, antrenmanlarını takip etmeye başlayabiliriz.",
        "welcome_focus": "Koçun karşılaştırma yapabilmesi için birkaç antrenman kaydet.",
        "welcome_next": "Bu hafta bir antrenmanı bitir ve buraya tekrar bak.",
        "celebrate_head": "Bu hafta yeni kişisel rekorların var.",
        "nudge_head": "Geçen hafta planladığın {target} günün {done} gününde antrenman yaptın.",
        "steady_head": "Bu hafta şimdiye kadar {sessions} antrenman, toplam {volume} kg.",
        "steady_head_empty": "Bu hafta henüz antrenman yok ama hafta daha bitmedi.",
        "pr": "{exercise}: {weight} kg ile {reps} tekrar, tahmini 1RM {e1rm} kg "
        "(önceki en iyi {prev} kg).",
        "volume_up": "Hacim geçen haftaya göre %{pct} arttı.",
        "volume_down": "Hacim geçen haftaya göre %{pct} azaldı.",
        "streak": "Üst üste {weeks} haftadır en az bir antrenman yapıyorsun.",
        "stalled": "{exercise} {weeks} haftadır ilerlemiyor (en iyi tahmin {e1rm} kg).",
        "stalled_next": "{exercise} için önümüzdeki 3 hafta farklı bir tekrar aralığı dene, "
        "örneğin 8 ile 10 tekrar.",
        "pr_next": "{exercise} planını koru, tüm setler sağlam hissettirince 2,5 kg ekle.",
        "target_next": "{target} antrenman planla ve şimdiden takvimine ekle.",
        "default_next": "Önümüzdeki hafta en az 3 antrenman hedefle.",
        "consistency_focus": "Önce düzen: geçen hafta planladığından az antrenman yaptın.",
        "no_focus": "Şu an seni geride tutan bir şey yok. Aynı düzenle devam et.",
    },
}


def num(x: float, lang: Lang) -> str:
    """1.0 -> "1", 62.5 -> "62.5" (or "62,5" in Turkish)."""
    s = f"{x:g}" if float(x).is_integer() else f"{x:.1f}"
    return s.replace(".", ",") if lang == "tr" else s


class RuleCoach:
    model = MODEL_NAME

    async def write_report(self, stats: WeeklyStats, lang: Lang) -> tuple[CoachReport, str]:
        return build_report(stats, lang), self.model


def build_report(stats: WeeklyStats, lang: Lang) -> CoachReport:
    t = T[lang]

    def n(x: float) -> str:
        return num(x, lang)

    if not stats.has_training:
        return CoachReport(
            headline=t["welcome_head"],
            wins=[t["welcome_win"]],
            focus_areas=[t["welcome_focus"]],
            next_week=[t["welcome_next"]],
            tone="welcome",
        )

    week = stats.this_week
    last = stats.previous_weeks[-1] if stats.previous_weeks else None
    target = stats.target_sessions_per_week
    # Only a user who was already training before last week can have "missed"
    # it; someone in their first week was simply not using the app yet.
    trained_before = any(w.sessions for w in stats.previous_weeks[:-1])
    missed = target is not None and last is not None and last.sessions < target and trained_before

    wins: list[str] = []
    for pr in stats.personal_records[:2]:
        wins.append(
            t["pr"].format(
                exercise=pr.exercise,
                weight=n(pr.weight_kg),
                reps=pr.reps,
                e1rm=n(pr.estimated_1rm_kg),
                prev=n(pr.previous_best_kg or 0),
            )
        )
    if stats.volume_change_pct is not None and stats.volume_change_pct > 0:
        wins.append(t["volume_up"].format(pct=n(stats.volume_change_pct)))
    if stats.training_streak_weeks >= 2:
        wins.append(t["streak"].format(weeks=stats.training_streak_weeks))

    focus: list[str] = []
    for lift in stats.stalled_lifts[:2]:
        focus.append(
            t["stalled"].format(
                exercise=lift.exercise,
                weeks=lift.weeks_without_progress,
                e1rm=n(lift.best_estimated_1rm_kg),
            )
        )
    # The current week is still running, so less volume only means something
    # once it has at least as many sessions as last week.
    comparable = last is not None and week.sessions >= last.sessions
    if stats.volume_change_pct is not None and stats.volume_change_pct < 0 and comparable:
        focus.append(t["volume_down"].format(pct=n(abs(stats.volume_change_pct))))
    if missed:
        focus.append(t["consistency_focus"])
    if not focus:
        focus.append(t["no_focus"])

    next_week: list[str] = []
    if stats.stalled_lifts:
        next_week.append(t["stalled_next"].format(exercise=stats.stalled_lifts[0].exercise))
    if stats.personal_records:
        next_week.append(t["pr_next"].format(exercise=stats.personal_records[0].exercise))
    next_week.append(t["target_next"].format(target=target) if target else t["default_next"])

    if stats.personal_records:
        tone, headline = "celebrate", t["celebrate_head"]
    elif missed:
        tone = "nudge"
        headline = t["nudge_head"].format(done=last.sessions, target=target)
    else:
        tone = "steady"
        headline = (
            t["steady_head"].format(sessions=week.sessions, volume=n(week.volume_kg))
            if week.sessions
            else t["steady_head_empty"]
        )

    return CoachReport(
        headline=headline,
        wins=wins[:3],
        focus_areas=focus[:3],
        next_week=next_week[:3],
        tone=tone,
    )
