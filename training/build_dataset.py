"""Turns labelled examples into chat-format JSONL for fine-tuning.

    python -m training.build_dataset                 # labelled examples only
    python -m training.build_dataset --rules 300     # plus 300 rule-coach examples

Every line is {"messages": [system, user, assistant]}, the format mlx-lm and
most fine-tuning tools read. The system and user turns are built by the same
functions the service uses, so training and serving see identical prompts.

Splits are fixed by seed: seeds ending in 0 are the test set, seeds ending in
1 are validation, the rest train. A seed never appears in two splits, so the
test set measures examples the model has not seen.
"""

import json
import sys
from pathlib import Path

from app.coach import Lang, stats_message, system_prompt
from app.models import CoachReport
from app.rules import build_report
from training.label import LABELS, parse, validate
from training.scenarios import generate

OUT = Path(__file__).parent / "data"


def split_for(seed: int) -> str:
    return {0: "test", 1: "valid"}.get(seed % 10, "train")


def example(seed: int, lang: Lang, report: CoachReport) -> dict:
    stats = generate(seed).stats()
    return {
        "messages": [
            {"role": "system", "content": system_prompt(lang)},
            {"role": "user", "content": stats_message(stats)},
            {"role": "assistant", "content": report.model_dump_json()},
        ]
    }


def build(rule_examples: int = 0) -> dict[str, int]:
    splits: dict[str, list[dict]] = {"train": [], "valid": [], "test": []}
    used: set[int] = set()

    for path in sorted(LABELS.glob("*.md")):
        status, problems = validate(path)
        if status != "done" or problems:
            continue
        seed, lang, _, report = parse(path.read_text())
        splits[split_for(seed)].append(example(seed, lang, report))
        used.add(seed)

    # Rule-coach reports teach the format and the grounding rule cheaply. They
    # go to train only, from seeds far away from the labelled ones.
    seed = 100_000
    while rule_examples > 0:
        if split_for(seed) == "train" and seed not in used:
            lang: Lang = "tr" if seed % 2 else "en"
            splits["train"].append(example(seed, lang, build_report(generate(seed).stats(), lang)))
            rule_examples -= 1
        seed += 1

    OUT.mkdir(exist_ok=True)
    for name, rows in splits.items():
        with open(OUT / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {name: len(rows) for name, rows in splits.items()}


if __name__ == "__main__":
    rules = int(sys.argv[sys.argv.index("--rules") + 1]) if "--rules" in sys.argv else 0
    print(build(rules))
