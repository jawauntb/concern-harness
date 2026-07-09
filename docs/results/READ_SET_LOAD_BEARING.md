# Read-set load-bearingness — Phase 2 (Law 2 at the coding surface)

Status: generated 2026-07-09. Claim level: **synthetic diagnostic** on a controlled multi-read slice (not a human-validated benchmark, not Modal SWE-bench).

## Method

For each instance we plant K read carriers in the task metadata: one
issue-derived (ground-truth load-bearing), one leak-tracking, and the
rest pure distractors. A synthetic `commit_fn` signs the diff with the
value of each ground-truth load-bearing read only. We run one
`gauge_fixing_probe` per read and predict *load_bearing* iff perturbing
the read moved the commitment, else *redundant*. Set precision /
recall / F1 are scored against the ground-truth load-bearing set.

Seeds: 8, reads per task: 4, total instances: 8.
Wall: 0.01s.

## Results

| metric | value | target |
|---|---:|---:|
| set precision (macro) | 1.000 | ≥ 0.95 |
| set recall (macro) | 1.000 | ≥ 0.95 |
| set F1 (macro) | 1.000 | ≥ 0.95 |

### Per-read confusion

| label \ verdict | load_bearing | redundant |
|---|---:|---:|
| load_bearing (truth) | 8 | 0 |
| distractor (truth)   | 0 | 24 |

Total per-read decisions: 32.

## Acceptance

- F1 ≥ 0.95: PASS (1.000)
- Precision ≥ 0.95: PASS (1.000)
- Recall ≥ 0.95: PASS (1.000)

## Artifacts

- `runs/read_set_load_bearing/results.jsonl` — one row per instance with per-read verdicts
