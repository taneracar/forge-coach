"""A coach backed by the locally fine-tuned model.

The model is trusted for wording only. Every report it writes goes through
the same checks as Claude's (invented numbers, unsupported claims), plus list
length and the medical/diet filter. A report that fails is thrown away; after
a second, sampled attempt also fails, the caller's fallback (the rule-based
coach) answers instead. Users never see an unchecked model report.

MLX runs only on Apple Silicon, so mlx-lm is an optional dependency and is
imported when the coach is first used.
"""

import asyncio
import re
from collections.abc import Callable

from app.coach import CoachError, Lang, parse_report, report_problems, stats_message, system_prompt
from app.models import CoachReport, WeeklyStats

MEDICAL = re.compile(r"\b(injur|pain|doctor|physio|calorie|diet|lose weight|fat loss)", re.I)

# First attempt is greedy; the retry samples, so it can produce a different report.
TEMPERATURES = (0.0, 0.7)

Generate = Callable[[str, str, float], str]  # (system, user, temperature) -> raw text


def check(report: CoachReport, stats: WeeklyStats) -> list[str]:
    problems = report_problems(report, stats)
    if max(len(report.wins), len(report.focus_areas), len(report.next_week)) > 3:
        problems.append("A list has more than 3 items.")
    body = " ".join([report.headline, *report.wins, *report.focus_areas, *report.next_week])
    if MEDICAL.search(body):
        problems.append("Mentions medical or diet topics.")
    return problems


def mlx_generator(base: str, adapter_path: str, max_tokens: int = 700) -> Generate:
    """Loads the model once and returns a blocking generate function.

    MLX binds a model's streams to the thread that created it, so loading and
    every generation run on one dedicated worker thread.
    """
    from concurrent.futures import ThreadPoolExecutor

    from mlx_lm import generate, load
    from mlx_lm.sample_utils import make_sampler

    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mlx")
    model, tok = worker.submit(load, base, adapter_path=adapter_path).result()

    def _run(system: str, user: str, temperature: float) -> str:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
        return generate(
            model,
            tok,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=make_sampler(temp=temperature),
            verbose=False,
        )

    def run(system: str, user: str, temperature: float) -> str:
        return worker.submit(_run, system, user, temperature).result()

    return run


class LocalCoach:
    def __init__(self, generate: Generate, model: str):
        self._generate = generate
        self.model = model
        # One model in memory, one generation at a time.
        self._lock = asyncio.Lock()

    async def write_report(self, stats: WeeklyStats, lang: Lang) -> tuple[CoachReport, str]:
        problems: list[str] = []
        for temperature in TEMPERATURES:
            async with self._lock:
                raw = await asyncio.to_thread(
                    self._generate, system_prompt(lang), stats_message(stats), temperature
                )
            try:
                report = parse_report(raw)
            except Exception:  # noqa: BLE001 - any unparseable output is a failed attempt
                problems = ["Output was not a valid report."]
                continue
            problems = check(report, stats)
            if not problems:
                return report, self.model
        raise CoachError(f"Local model report failed checks: {problems}")
