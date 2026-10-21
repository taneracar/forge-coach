"""Checks the factual claims in a report that the number check cannot see.

`ungrounded_numbers` catches invented figures. A model can still say "you
missed two weeks" after one, call a muscle-building goal a strength goal, or
say chest got no work when it got nine sets. These rules look for those
phrasings in English and Turkish and test them against the statistics. They
are deliberately narrow: a claim they do not recognise passes.
"""

import re

from app.models import CoachReport, WeeklyStats

GROUPS = {
    "chest": ["chest", "göğüs", "göğse", "göğsü"],
    "back": ["back", "sırt"],
    "legs": ["legs", "leg", "bacak"],
    "shoulders": ["shoulders", "shoulder", "omuz"],
    "arms": ["arms", "arm", "kol"],
}

GOALS = {
    "get_stronger": [r"strength goal", r"güç hedef"],
    "build_muscle": [r"(building|build) muscle", r"kas geliştirme hedef", r"kas kazan"],
    "stay_fit": [r"stay(ing)? fit", r"formda kal"],
    "lose_fat": [r"fat loss", r"yağ yak", r"lose fat"],
}

NUMBER_WORDS = {
    "a": 1, "one": 1, "bir": 1, "two": 2, "iki": 2, "three": 3, "üç": 3,
    "four": 4, "dört": 4, "five": 5, "beş": 5,
}  # fmt: skip


def _text(report: CoachReport) -> str:
    return " ".join([report.headline, *report.wins, *report.focus_areas, *report.next_week])


def _weeks_off(stats: WeeklyStats) -> int:
    """Empty weeks right before the most recent trained week."""
    weeks = [*stats.previous_weeks, stats.this_week]
    if weeks[-1].sessions == 0:
        weeks = weeks[:-1]
    while weeks and weeks[-1].sessions == 0:
        weeks.pop()
    if not weeks:
        return 0
    weeks.pop()  # the most recent trained week itself
    gap = 0
    while weeks and weeks[-1].sessions == 0:
        gap += 1
        weeks.pop()
    return gap if weeks else 0  # a gap with no earlier training is not a break


def unsupported_claims(report: CoachReport, stats: WeeklyStats) -> list[str]:
    text = _text(report)
    # Python lowercases "İ" to "i" plus a combining dot, so "İki" would never
    # match "iki"; fold it first.
    low = text.replace("İ", "i").lower()
    problems: list[str] = []

    for goal, patterns in GOALS.items():
        for pat in patterns:
            if re.search(pat, low) and stats.goal != goal:
                problems.append(f"mentions goal '{goal}' but the user's goal is {stats.goal}")

    trained = set(stats.sets_by_muscle_group)
    for group, words in GROUPS.items():
        alt = "|".join(words)
        said_none = re.search(
            rf"\bno ({alt}) (sets|work)\b|\b({alt}) got no\b|\bno ({alt}) or\b"
            rf"|\b({alt})\w* (bu hafta )?hiç çalış|\bhiç ({alt})",
            low,
        )
        if said_none and group in trained:
            problems.append(
                f"says {group} got no work, but it had {stats.sets_by_muscle_group[group]} sets"
            )

    for m in re.finditer(
        r"\b(a|one|two|three|four|five|\d+) weeks? off\b|\b(bir|iki|üç|dört|beş|\d+) haftalık ara",
        low,
    ):
        word = m.group(1) or m.group(2)
        n = int(word) if word.isdigit() else NUMBER_WORDS.get(word, -1)
        actual = _weeks_off(stats)
        if n != actual:
            problems.append(f"says {n} weeks off, but the break was {actual}")

    had_history = any(w.sessions for w in stats.previous_weeks)
    if had_history and re.search(r"\byour first week\b(?! back)|\bilk haftan", low):
        problems.append("calls this the first week, but there is earlier training")

    return problems
