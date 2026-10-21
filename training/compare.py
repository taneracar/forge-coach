"""Side-by-side reports from several adapters on scenarios no model has seen.

    python -m training.compare rules-smoke labels-v1 --seeds 900-905

Writes training/eval/compare.md with the statistics summary and each model's
report for every seed, so a person can judge the writing, not only the scores.
"""

import sys
from pathlib import Path

from mlx_lm import generate, load

from app.coach import parse_report, stats_message, system_prompt, ungrounded_numbers
from app.rules import build_report
from training.evaluate import BASE
from training.label import summarize
from training.scenarios import generate as scenario
from training.scenarios import lang_for

ROOT = Path(__file__).parent


def render(report) -> str:
    lines = [f"**{report.headline}** _({report.tone})_"]
    for key in ["wins", "focus_areas", "next_week"]:
        lines += [f"- {key}: {x}" for x in getattr(report, key)]
    return "\n".join(lines)


def main(adapters: list[str], seeds: list[int]) -> None:
    out = ["# Side-by-side reports", ""]
    models = {name: load(BASE, adapter_path=str(ROOT / "adapters" / name)) for name in adapters}
    for seed in seeds:
        sc = scenario(seed)
        stats, lang = sc.stats(), lang_for(seed)
        out += [f"## seed {seed} ({lang}, {sc.archetype})", "", "```", summarize(sc, stats), "```"]
        out += ["", "### rules-v1", render(build_report(stats, lang)), ""]
        for name, (model, tok) in models.items():
            msgs = [
                {"role": "system", "content": system_prompt(lang)},
                {"role": "user", "content": stats_message(stats)},
            ]
            prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
            raw = generate(model, tok, prompt=prompt, max_tokens=700, verbose=False)
            try:
                report = parse_report(raw)
                bad = ungrounded_numbers(report, stats)
                body = render(report) + (f"\n\n⚠️ invented numbers: {bad}" if bad else "")
            except Exception:  # noqa: BLE001 - show whatever came back
                body = "INVALID:\n" + raw[:500]
            out += [f"### {name}", body, ""]
    path = ROOT / "eval" / "compare.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    args = sys.argv[1:]
    seeds_arg = args[args.index("--seeds") + 1] if "--seeds" in args else "900-905"
    lo, hi = map(int, seeds_arg.split("-"))
    names = [a for a in args if not a.startswith("--") and a != seeds_arg]
    main(names, list(range(lo, hi + 1)))
