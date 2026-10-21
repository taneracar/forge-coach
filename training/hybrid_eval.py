"""Measures the hybrid coach (local model, rule fallback) on the test split.

    python -m training.hybrid_eval labels-v2

Reports how often the local model's report was served, how often the rule
coach had to answer, and how long a report took. Every served report has
passed the checks by construction.
"""

import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

from app.coach import FallbackCoach
from app.local import LocalCoach, mlx_generator
from app.rules import RuleCoach
from training.evaluate import BASE, stats_from_prompt

ROOT = Path(__file__).parent


async def main(adapter: str) -> None:
    generate = mlx_generator(BASE, str(ROOT / "adapters" / adapter))
    coach = FallbackCoach(LocalCoach(generate, f"local:{adapter}"), RuleCoach())
    rows = [json.loads(line) for line in (ROOT / "data" / "test.jsonl").read_text().splitlines()]
    served, seconds = Counter(), []
    for row in rows:
        system, user, _ = row["messages"]
        lang = "tr" if "Turkish" in system["content"] else "en"
        start = time.time()
        _, model = await coach.write_report(stats_from_prompt(user["content"]), lang)
        seconds.append(time.time() - start)
        served[model] += 1
    n = len(rows)
    print(f"hybrid {adapter}: {n} reports")
    for model, count in served.most_common():
        print(f"  {model:22} {count / n:.0%}")
    print(f"  avg seconds  {sum(seconds) / n:.1f}, max {max(seconds):.1f}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "labels-v2"))
