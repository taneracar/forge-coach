"""Scores a local model on the test split with the service's own checks.

    python -m training.evaluate                          # base model, schema hint
    python -m training.evaluate --adapter rules-smoke    # base + LoRA adapter
    python -m training.evaluate --adapter rules-smoke --limit 10

For every test example it generates a report and records: valid JSON for
`CoachReport`, numbers grounded in the statistics, tone matching the reference,
no medical or diet advice, lists of at most 3, and generation time. Outputs go
to training/eval/<name>.jsonl so runs can be compared line by line.
"""

import json
import re
import sys
import time
from pathlib import Path

from mlx_lm import generate, load

from app.coach import parse_report, ungrounded_numbers
from app.models import CoachReport, WeeklyStats

BASE = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
ROOT = Path(__file__).parent
MEDICAL = re.compile(r"\b(injur|pain|doctor|physio|calorie|diet|lose weight|fat loss)", re.I)


def stats_from_prompt(user_content: str) -> WeeklyStats:
    return WeeklyStats.model_validate_json(user_content.split("\n", 1)[1])


def score(raw: str, stats: WeeklyStats, reference: CoachReport) -> dict:
    try:
        report = parse_report(raw)
    except Exception:  # noqa: BLE001 - any parse failure counts the same
        return {"valid": False}
    body = " ".join([report.headline, *report.wins, *report.focus_areas, *report.next_week])
    return {
        "valid": True,
        "grounded": not ungrounded_numbers(report, stats),
        "ungrounded": ungrounded_numbers(report, stats),
        "tone_match": report.tone == reference.tone,
        "safe": not MEDICAL.search(body),
        "short_lists": max(len(report.wins), len(report.focus_areas), len(report.next_week)) <= 3,
    }


def main(adapter: str | None, limit: int | None) -> None:
    model, tok = load(BASE, adapter_path=str(ROOT / "adapters" / adapter) if adapter else None)
    hint = (
        ""
        if adapter
        else "\nReply with only a JSON object matching this schema:\n"
        + json.dumps(CoachReport.model_json_schema())
    )
    rows = [json.loads(line) for line in (ROOT / "data" / "test.jsonl").read_text().splitlines()]
    rows = rows[:limit] if limit else rows

    name = adapter or "base"
    out_dir = ROOT / "eval"
    out_dir.mkdir(exist_ok=True)
    results = []
    with open(out_dir / f"{name}.jsonl", "w", encoding="utf-8") as out:
        for row in rows:
            system, user, assistant = row["messages"]
            msgs = [{"role": "system", "content": system["content"] + hint}, user]
            prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
            start = time.time()
            raw = generate(model, tok, prompt=prompt, max_tokens=700, verbose=False)
            seconds = time.time() - start
            stats = stats_from_prompt(user["content"])
            reference = CoachReport.model_validate_json(assistant["content"])
            result = {**score(raw, stats, reference), "seconds": round(seconds, 2), "raw": raw}
            results.append(result)
            out.write(json.dumps(result, ensure_ascii=False) + "\n")

    n = len(results)
    valid = [r for r in results if r["valid"]]

    def pct(key: str) -> str:
        return f"{sum(r.get(key, False) for r in results) / n:.0%}"

    print(f"{name}: {n} examples")
    for key in ["valid", "grounded", "tone_match", "safe", "short_lists"]:
        print(f"  {key:12} {pct(key)}")
    print(f"  avg seconds  {sum(r['seconds'] for r in results) / n:.1f}")
    bad = [num for r in valid for num in r["ungrounded"]]
    if bad:
        print(f"  invented numbers (sample): {bad[:15]}")


if __name__ == "__main__":
    args = sys.argv[1:]
    adapter = args[args.index("--adapter") + 1] if "--adapter" in args else None
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    main(adapter, limit)
