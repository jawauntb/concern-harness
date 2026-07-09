# Concern mapper eval — Phase 4

Status: generated 2026-07-09. Claim level: **synthetic diagnostic** (EchoModel returns baseline JSON; proves wiring + gauge-on-mapped-concerns, not frontier LLM quality).

## Method

`LLMConcernMapper` loads `lbah/prompts/concern_mapper.txt`. Metadata is
stripped so the model path runs. Quality is id-overlap vs hand-authored
`metadata.concern_variables`. Gauge probe then runs on the mapped ledger.

Seeds: 8. Wall: 0.0s.

## Mapping quality vs metadata baseline

| metric | LLM (Echo→baseline) | metadata |
|---|---:|---:|
| mean recall | 1.00 | 1.00 |
| mean F1 | 1.00 | 1.00 |

## Gauge on mapped concerns

| metric | value |
|---|---:|
| held-out catch | 1.00 |
| held-out gauge catch | 1.00 |
| good allow | 1.00 |

## Acceptance

- End-to-end LLM mapper path (prompt file + extract): PASS
- Quality reported vs metadata baseline: PASS (F1=1.00)
- Gauge catch-rate on mapped concerns: PASS (1.00)

## Artifacts

- `runs/concern_mapper_eval/quality.jsonl`
- `runs/concern_mapper_eval/heldout_mapped.jsonl`
