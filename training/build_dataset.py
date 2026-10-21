"""Turns labelled examples into chat-format JSONL for fine-tuning.

    python -m training.build_dataset                 # labelled examples only
    python -m training.build_dataset --rules 300     # plus 300 rule-coach examples
    python -m training.build_dataset --rules 300 --rules-eval 40   # pipeline smoke test
    python -m training.build_dataset --rules 300 --rules-eval 40 --label-repeat 3

Every line is {"messages": [system, user, assistant]}, the format mlx-lm and
most fine-tuning tools read. The system and user turns are built by the same
functions the service uses, so training and serving see identical prompts.

Splits are fixed per seed by a hash (about 10% test, 10% validation), so a
seed never appears in two splits and every archetype and language shows up in
each of them.
"""

import json
import sys
from pathlib import Path

from app.coach import Lang, stats_message, system_prompt
from app.models import CoachReport
from app.rules import build_report
from training.label import LABELS, parse, validate
from training.scenarios import generate, lang_for, split_for

OUT = Path(__file__).parent / "data"


def example(seed: int, lang: Lang, report: CoachReport) -> dict:
    stats = generate(seed).stats()
    return {
        "messages": [
            {"role": "system", "content": system_prompt(lang)},
            {"role": "user", "content": stats_message(stats)},
            {"role": "assistant", "content": report.model_dump_json()},
        ]
    }


def build(rule_examples: int = 0, rule_eval: int = 0, label_repeat: int = 1) -> dict[str, int]:
    splits: dict[str, list[dict]] = {"train": [], "valid": [], "test": []}
    used: set[int] = set()

    for path in sorted(LABELS.glob("*.md")):
        status, problems = validate(path)
        if status != "done" or problems:
            continue
        seed, lang, _, report = parse(path.read_text())
        split = split_for(seed)
        # Hand-written examples are few next to the rule ones; repeating them in
        # train lets their style win without changing valid or test.
        copies = label_repeat if split == "train" else 1
        splits[split].extend([example(seed, lang, report)] * copies)
        used.add(seed)

    # Rule-coach reports teach the format and the grounding rule cheaply. They
    # go to train only, from seeds far away from the labelled ones.
    # rule_eval adds the same kind of examples to valid and test, which is only
    # useful for checking that the training pipeline runs end to end.
    wanted = {"train": rule_examples, "valid": rule_eval, "test": rule_eval}
    seed = 100_000
    while any(wanted.values()):
        split = split_for(seed)
        if wanted[split] > 0 and seed not in used:
            lang: Lang = lang_for(seed)
            splits[split].append(example(seed, lang, build_report(generate(seed).stats(), lang)))
            wanted[split] -= 1
        seed += 1

    OUT.mkdir(exist_ok=True)
    for name, rows in splits.items():
        with open(OUT / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {name: len(rows) for name, rows in splits.items()}


if __name__ == "__main__":

    def flag(name: str) -> int:
        return int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else 0

    print(build(flag("--rules"), flag("--rules-eval"), flag("--label-repeat") or 1))
