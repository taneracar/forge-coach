"""Turns computed statistics into a short coaching report with Claude.

The model gets the statistics as JSON and is told to use no other numbers.
That rule is then checked in code: every number in the report must appear in
the statistics (or be a small count or a standard plate increment). A report
that invents a number is sent back once with the offending values named, and
rejected if it does it again.
"""

import json
import re
from typing import Literal, Protocol

import anthropic

from app.models import CoachReport, WeeklyStats

Lang = Literal["en", "tr"]

SYSTEM_PROMPT = """\
You are the weekly coach inside Forge, a strength-training app. You receive one \
user's training statistics as JSON, computed by the app, and write a short report \
about their week.

Rules:
- Use only numbers that appear in the statistics. Do not calculate new ones \
(no new percentages, totals, or averages) and do not estimate. Small counts like \
"two sessions" and plate jumps of 2.5 or 5 kg are fine.
- Name exercises exactly as they appear in the statistics.
- Each list has at most 3 items, each a single plain sentence a lifter would say \
out loud. Be specific to this user's data; skip generic fitness advice.
- this_week covers the week in progress, so few sessions early in the week is \
normal and not a failure.
- If a lift is stalled, suggest one concrete change (rep range, load, or frequency).
- No medical, injury, or diet advice. Never comment on body weight or appearance.
- If there is little or no history, welcome the user and tell them what the \
report will show once they log a few sessions.
- Write in {language}."""

LANGUAGES = {"en": "English", "tr": "Turkish"}

# Numbers a report may use without them being in the statistics.
FREE_NUMBERS = {*map(float, range(11)), 2.5, 5.0, 7.5}

_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?")


class CoachError(Exception):
    pass


class CoachUnavailable(CoachError):
    """Temporary: rate limited, overloaded, or unreachable. Worth retrying."""


class Coach(Protocol):
    model: str

    async def write_report(self, stats: WeeklyStats, lang: Lang) -> tuple[CoachReport, str]:
        """Returns the report and the name of the model that wrote it."""
        ...


def ungrounded_numbers(report: CoachReport, stats: WeeklyStats) -> list[str]:
    allowed = set(FREE_NUMBERS)
    for n in _NUMBER.findall(stats.model_dump_json()):
        v = float(n)
        allowed |= {v, round(v), round(v, 1)}
        allowed.add(abs(v))
    text = " ".join([report.headline, *report.wins, *report.focus_areas, *report.next_week])
    bad = []
    for n in _NUMBER.findall(text):
        v = float(n.replace(",", "."))
        if v not in allowed and round(v, 1) not in allowed:
            bad.append(n)
    return bad


class ClaudeCoach:
    def __init__(self, client: anthropic.AsyncAnthropic, model: str, effort: str = "low"):
        self._client = client
        self.model = model
        self._effort = effort

    async def write_report(self, stats: WeeklyStats, lang: Lang) -> tuple[CoachReport, str]:
        messages: list[dict] = [
            {
                "role": "user",
                "content": "Training statistics:\n"
                + json.dumps(stats.model_dump(mode="json"), indent=1),
            }
        ]
        report = await self._ask(messages, lang)
        bad = ungrounded_numbers(report, stats)
        if not bad:
            return report, self.model

        # One correction round: show the model its own answer and what was wrong.
        messages += [
            {"role": "assistant", "content": report.model_dump_json()},
            {
                "role": "user",
                "content": f"These numbers are not in the statistics: {', '.join(bad)}. "
                "Rewrite the report using only numbers from the statistics.",
            },
        ]
        report = await self._ask(messages, lang)
        if bad := ungrounded_numbers(report, stats):
            raise CoachError(f"Report used numbers not in the statistics: {bad}")
        return report, self.model

    async def _ask(self, messages: list[dict], lang: Lang) -> CoachReport:
        try:
            response = await self._client.beta.messages.parse(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT.format(language=LANGUAGES[lang]),
                messages=messages,
                output_format=CoachReport,
                output_config={"effort": self._effort},
                # If the model declines, the API retries on a fallback model
                # inside the same call instead of returning an empty report.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except (anthropic.RateLimitError, anthropic.OverloadedError) as e:
            raise CoachUnavailable("Claude is busy, try again shortly") from e
        except anthropic.APIConnectionError as e:
            raise CoachUnavailable("Could not reach Claude") from e
        except anthropic.APIStatusError as e:
            raise CoachError(f"Claude API error {e.status_code}") from e

        if response.stop_reason == "refusal":
            raise CoachError("The model declined to write this report")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise CoachError("The model returned an incomplete report")
        return response.parsed_output


class FallbackCoach:
    """Tries the primary coach and answers with the fallback if it fails.

    A failed Claude call (no key, rate limit, refusal, invented numbers) still
    gives the user a report, just a plainer one.
    """

    def __init__(self, primary: Coach, fallback: Coach):
        self._primary = primary
        self._fallback = fallback
        self.model = primary.model

    async def write_report(self, stats: WeeklyStats, lang: Lang) -> tuple[CoachReport, str]:
        try:
            return await self._primary.write_report(stats, lang)
        except CoachError:
            return await self._fallback.write_report(stats, lang)
