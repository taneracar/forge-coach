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

## Baseline: Qwen3-4B-Instruct-2507 (4-bit MLX), no fine-tuning (2026-10-20)

Three scenarios, with the JSON schema added to the system prompt. Every
answer was valid JSON, at 3.5–8.4 s per report on an M4 Pro.

| seed | case | tone | invented numbers |
|---|---|---|---|
| 3 (tr) | record week | `steady` (should be `celebrate`) | 75, 35, 45, 12 and others |
| 4 (en) | stalled lifts | `nudge` | 70%, 75% of 1RM; read 8730 kg as "8.73 kg" |
| 0 (en) | new user | `welcome` | none |

Other problems: the Turkish is ungrammatical ("ağıyla", "repetisyon",
third person), there is generic programming advice, and it uses Turkish
thousands separators ("11.485"), which the grounding check reads as a decimal.
This is the gap fine-tuning has to close.

## Smoke run: LoRA on 400 rule-coach examples (2026-10-20)

Run with `training/train.sh rules-smoke 300`: 16 layers, rank-default LoRA,
7.3M trainable parameters (0.18%), batch 2 × grad-accum 2, lr 1e-4, prompt
masked. It took about 15 minutes on an M4 Pro, and validation loss fell from
2.91 to 0.021.

Test split: 40 rule-coach examples (25 tr / 15 en, every tone), scored by
`python -m training.evaluate`.

| | base (schema hint) | rules-smoke adapter |
|---|---|---|
| valid JSON | 95% | 100% |
| grounded numbers | 15% | **100%** |
| tone matches reference | 32% | 75% |
| no medical/diet advice | 95% | 100% |
| lists ≤ 3 | 95% | 100% |
| seconds per report | 6.0 | 3.7 |

The adapter learned the format and the grounding rule. It also copies the
rule coach's sentences word for word (20/40 reports are identical), which is
expected because those were its only teacher. Most tone misses are `nudge`
read as `steady` (8/10), where the rule depends on weeks before last week.

What this run did not prove is better writing. That has to come from the
hand-written labels, with the rule examples kept only as format support.

A first attempt split the data by `seed % 10`, the same digit that picks the
archetype, so every test example was a new user and training had none. Splits
and languages are now hashed per seed, and a test guards it.

## labels-v1: 26 hand-approved labels ×3 + 300 rule examples (2026-10-20)

`build_dataset --rules 300 --rules-eval 40 --label-repeat 3` gave 378 train
rows (78 from labels, 300 from rules), 43 valid, and 41 test (40 rule + 1 label).
Training used the same settings as the smoke run, and final validation loss
was 0.026.

| | rules-smoke | labels-v1 |
|---|---|---|
| valid JSON | 100% | 100% |
| grounded numbers | 100% | 100% |
| tone matches reference | 76% | 78% |
| safe | 100% | 100% |
| identical to rule report | 49% | **24%** |
| seconds per report | 3.8 | 3.7 |

The side-by-side on six unseen seeds (`python -m training.compare`, written to
eval/compare.md) shows the limit plainly: labels-v1 still writes the rule
coach's sentences and differs mostly by dropping or swapping a line. With 300
rule rows against 78 label rows, the templates dominate the style.

Next: train with far fewer rule rows (or none) so the hand-written style
carries, and keep adding labels.

## labels-v2: 55 approved labels ×2 + 50 rule examples, 150 iters (2026-10-21)

160 train rows (110 from labels). The test set is the same as v1.

| | rules-smoke | labels-v1 | labels-v2 |
|---|---|---|---|
| valid JSON | 100% | 100% | 98% |
| grounded numbers | 100% | 100% | 98% |
| tone matches reference | 76% | 78% | 68% |
| safe | 100% | 100% | 98% |
| lists ≤ 3 | 100% | 100% | 93% |
| identical to rule report | 49% | 24% | **2%** |
| final val loss | 0.021 | 0.026 | 0.273 |

v2 stopped copying the rule coach, but the side-by-side shows it now invents
facts that the number check cannot catch:
- a goal the user does not have
- "two weeks off" when only one week was missed
- muscle groups that were in fact trained
- nonsense lines such as "keep Barbell Squat at 5 kg per rep"

Validation loss was still falling at step 150, so the model is undertrained,
and 55 labels are too few to teach the facts-to-sentences mapping.

Takeaways:
1. Grounding of numbers is not enough. Claims about goals, breaks, and muscle
   groups need checks too, or the service must keep falling back to the rule
   coach.
2. More labels (hundreds, not tens) and longer training come before any
   serving use.
