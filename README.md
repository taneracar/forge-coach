# forge-coach

Weekly training summaries for [Forge](https://forgerep.app) users. A small
FastAPI service reads a user's last eight weeks of workouts, computes the
statistics in Python, and asks Claude to write a short report about them.

```
GET /v1/coach/weekly?lang=en&tz=America/Los_Angeles
Authorization: Bearer <Supabase access token>
```

```json
{
  "stats":  { "this_week": { "sessions": 3, "volume_kg": 8450.0 }, "personal_records": [...], "stalled_lifts": [...] },
  "report": { "headline": "...", "wins": [...], "focus_areas": [...], "next_week": [...], "tone": "celebrate" },
  "model": "claude-opus-5-5",
  "cached": false
}
```

## Design

**Code does the math, the model does the words.** Volume, week-over-week
change, personal records (Epley estimated 1RM, sets of 12 reps or fewer),
stalled lifts, and the training streak all come from `app/stats.py`, which is
pure and covered by unit tests. The model receives that JSON and nothing else.

**Numbers are checked, not trusted.** The prompt tells the model to use only
numbers from the statistics; `ungrounded_numbers` then verifies it. A report
that invents a figure is sent back once with the bad values named, and rejected
if it happens again.

**Works without a model.** `app/rules.py` builds the same report from fixed
English and Turkish sentences filled with numbers from the statistics. With no
`ANTHROPIC_API_KEY` the service runs on it alone, at no cost. With a key,
Claude writes the reports and the rule-based coach answers whenever Claude
fails (rate limit, refusal, invented numbers). The response's `model` field
says which one wrote it, and fallback reports are not cached, so the better
report comes back as soon as Claude does.

**Structured output.** The response is parsed straight into the `CoachReport`
Pydantic model, so the API never returns free text the clients would have to
parse.

**The service cannot see other users' data.** It reads through Supabase's REST
API with the caller's own access token, so Row Level Security decides which
rows come back. There is no database password or service-role key in the
service. Tokens are verified against the project's public JWKS (ES256, issuer,
`authenticated` audience, expiry).

**Cost.** Reports are cached per user and per exact statistics, so refreshing
with no new training is free. Weeks are computed in the user's time zone.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env   # Supabase URL and anon key; the Anthropic key is optional
.venv/bin/uvicorn app.main:app --reload --port 8080
```

## Tests

```bash
.venv/bin/pytest            # unit and API tests, no network
.venv/bin/pytest -m live    # evaluation scenarios against the real Claude API
```

The live suite runs realistic weeks (new user, record week, stalled squat,
missed week) in English and Turkish and checks grounding, list lengths, tone,
and that no medical or diet advice slips in.

## Deploy

The Dockerfile builds a small non-root image that listens on `$PORT`. CI runs
lint, tests, builds the image, and checks that the container answers `/health`.
