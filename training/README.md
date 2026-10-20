# Training a local coach model

Goal: a small open model, fine-tuned on Forge's own examples, that writes the
weekly report as well as the rule-based coach or better, runs on a laptop, and
passes the same grounding checks as Claude.

1. **Scenarios** (`scenarios.py`): seeded synthetic training histories across ten
   lifter archetypes, pushed through the real `compute_weekly_stats`.
2. **Labels** (`label.py`): one Markdown file per example in `labels/`, starting
   from a rule-coach draft that a person rewrites. `check` rejects any number
   not in the statistics.

   ```bash
   .venv/bin/python -m training.label new 10
   .venv/bin/python -m training.label check
   ```
3. **Dataset** (`build_dataset.py`): chat-format JSONL with the exact system and
   user prompts the service sends. Seeds ending in 0 are the test set and 1 is
   validation, so a seed never leaks across splits.

   ```bash
   .venv/bin/python -m training.build_dataset --rules 300
   ```
4. **Fine-tune** (next): LoRA with MLX on Apple Silicon, then evaluate on the
   test split with the same checks as `tests/test_live_eval.py`.
