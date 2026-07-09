# Concern mapper eval — Phase 4

Status: generated 2026-07-09. Claim level: **real-LLM diagnostic** on a controlled synthetic suite (moved_bottleneck). Real `claude -p` invoked per seed.

## Method

`LLMConcernMapper` loads `lbah/prompts/concern_mapper.txt`. Metadata is
stripped so the model path runs. Two quality lenses:

1. **ID-overlap** — precision/recall/F1 on the mapper's chosen variable
   IDs vs the hand-authored baseline. Meaningful only when the model
   is told to reuse baseline IDs — real LLMs invent their own.
2. **Value-recall + critical-rank** — id-agnostic. Value-recall = fraction of baseline values recovered anywhere in the mapper's output. Critical-rank passes when the concern the mapper assigns to the
   load-bearing distinction exceeds its mean concern for distractors.

Gauge probe then runs on the mapped ledger.

Model: `claude`. Seeds: 8. Total wall: 73.6s. Mean wall/seed: 9.19s.

## Mapping quality vs metadata baseline

| metric | LLM | metadata |
|---|---:|---:|
| id-overlap recall | 0.44 | 1.00 |
| id-overlap F1 | 0.48 | 1.00 |
| value-recall | 0.94 | 1.00 |
| critical-rank correct | 1.00 | 1.00 |
| mean critical concern | 1.00 | 1.00 |
| mean distractor concern | 0.04 | 0.20 |

## Gauge on mapped concerns

| metric | value |
|---|---:|
| held-out catch | 1.00 |
| held-out gauge catch | 1.00 |
| good allow | 0.62 |

## Acceptance

- End-to-end LLM mapper path (prompt file + extract): PASS
- Quality reported vs metadata baseline: value-recall=0.94, rank-correct=1.00
- Gauge catch-rate on mapped concerns: 1.00

## Artifacts

- `runs/concern_mapper_eval_claude/quality.jsonl`
- `runs/concern_mapper_eval_claude/heldout_mapped.jsonl`
- `runs/concern_mapper_eval_claude/mapped_variables.jsonl`
