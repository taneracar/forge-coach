"""Hand-labelling workflow for the coach dataset.

    python -m training.label new 10     # write 10 new example files to label
    python -m training.label check      # validate every labelled file

Each example is a Markdown file in training/labels/. The top shows the week's
statistics in plain form; below it is a draft from the rule-based coach. Rewrite
the draft the way a good coach would say it, then change `status: draft` to
`status: done`. `check` refuses a file whose numbers are not in the statistics,
whose lists have more than 3 items, or whose tone is not one of the four.
"""

import re
import sys
from pathlib import Path

from app.coach import Lang, ungrounded_numbers
from app.models import CoachReport, WeeklyStats
from app.rules import build_report
from training.scenarios import ARCHETYPES, Scenario, generate

LABELS = Path(__file__).parent / "labels"
SECTIONS = ["headline", "wins", "focus_areas", "next_week", "tone"]
TONES = ["celebrate", "steady", "nudge", "welcome"]


def example_path(seed: int, lang: Lang) -> Path:
    return LABELS / f"s{seed:04d}-{lang}.md"


def summarize(sc: Scenario, stats: WeeklyStats) -> str:
    w = stats.this_week
    lines = [
        f"archetype: {sc.archetype} | today: {sc.today:%a %Y-%m-%d} | "
        f"goal: {stats.goal} | level: {stats.experience} | "
        f"target: {stats.target_sessions_per_week} sessions/week",
        f"this week (in progress): {w.sessions} sessions, {w.completed_sets} sets, "
        f"{w.volume_kg} kg volume",
        "previous weeks (oldest first): "
        + ", ".join(f"{p.sessions}s/{p.volume_kg}kg" for p in stats.previous_weeks),
        f"volume change vs last week: {stats.volume_change_pct}%",
        f"training streak: {stats.training_streak_weeks} weeks",
    ]
    for pr in stats.personal_records:
        lines.append(
            f"RECORD {pr.exercise}: {pr.weight_kg} kg x {pr.reps}, "
            f"e1RM {pr.estimated_1rm_kg} (was {pr.previous_best_kg})"
        )
    for st in stats.stalled_lifts:
        lines.append(
            f"STALLED {st.exercise}: best e1RM {st.best_estimated_1rm_kg}, "
            f"{st.weeks_without_progress} weeks"
        )
    if stats.sets_by_muscle_group:
        lines.append(
            "sets this week: "
            + ", ".join(f"{k} {v}" for k, v in stats.sets_by_muscle_group.items())
        )
    return "\n".join(lines)


def render(seed: int, lang: Lang) -> str:
    sc = generate(seed)
    stats = sc.stats()
    draft = build_report(stats, lang)
    body = [
        f"<!-- seed: {seed} | lang: {lang} | status: draft -->",
        f"# {sc.id} ({lang})",
        "",
        "```",
        summarize(sc, stats),
        "```",
        "",
        "## headline",
        draft.headline,
        "",
    ]
    for key in ["wins", "focus_areas", "next_week"]:
        body += [f"## {key}", *[f"- {line}" for line in getattr(draft, key)], ""]
    body += ["## tone", draft.tone, ""]
    return "\n".join(body)


def parse(text: str) -> tuple[int, Lang, str, CoachReport]:
    meta = re.search(r"seed: (\d+) \| lang: (\w+) \| status: (\w+)", text)
    if not meta:
        raise ValueError("missing the <!-- seed | lang | status --> line")
    seed, lang, status = int(meta[1]), meta[2], meta[3]

    parts: dict[str, list[str]] = {}
    current = None
    for line in text.split("```", 2)[-1].splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            parts[current] = []
        elif current and line.strip():
            parts[current].append(line.strip())
    missing = [s for s in SECTIONS if s not in parts]
    if missing:
        raise ValueError(f"missing sections: {missing}")

    def items(key: str) -> list[str]:
        return [ln[2:].strip() if ln.startswith("- ") else ln for ln in parts[key]]

    report = CoachReport(
        headline=" ".join(parts["headline"]),
        wins=items("wins"),
        focus_areas=items("focus_areas"),
        next_week=items("next_week"),
        tone=(parts["tone"] or [""])[0],
    )
    return seed, lang, status, report


def validate(path: Path) -> tuple[str, list[str]]:
    """Returns (status, problems)."""
    try:
        seed, lang, status, report = parse(path.read_text())
    except Exception as e:  # noqa: BLE001 - shown to the person labelling
        return "broken", [str(e).splitlines()[0]]
    problems = []
    stats = generate(seed).stats()
    if bad := ungrounded_numbers(report, stats):
        problems.append(f"numbers not in the statistics: {bad}")
    for key in ["wins", "focus_areas", "next_week"]:
        if len(getattr(report, key)) > 3:
            problems.append(f"{key} has more than 3 items")
    if not report.headline:
        problems.append("empty headline")
    return status, problems


def cmd_new(count: int) -> None:
    LABELS.mkdir(exist_ok=True)
    made, seed = 0, 0
    while made < count:
        lang: Lang = "tr" if seed % 2 else "en"
        path = example_path(seed, lang)
        if not path.exists():
            path.write_text(render(seed, lang))
            print(f"new  {path.name}  ({ARCHETYPES[seed % len(ARCHETYPES)]})")
            made += 1
        seed += 1


def cmd_check() -> int:
    counts = {"done": 0, "draft": 0, "broken": 0}
    failed = 0
    for path in sorted(LABELS.glob("*.md")):
        status, problems = validate(path)
        counts[status] = counts.get(status, 0) + 1
        if problems:
            failed += 1
            print(f"FIX  {path.name}: " + "; ".join(problems))
    print(f"done {counts['done']} | draft {counts['draft']} | broken {counts['broken']}")
    return 1 if failed else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["new"]:
        cmd_new(int(args[1]) if len(args) > 1 else 10)
    elif args[:1] == ["check"]:
        sys.exit(cmd_check())
    else:
        print(__doc__)
