# Runtime contamination — Phase 2

Status: generated 2026-07-09. Claim level: **coding-agent diagnostic** on a controlled synthetic slice (not Modal SWE-bench, not human-validated).

## Method

Dual `gauge_fixing_probe` on `leak_carrier` vs `issue`. Flag when the
commitment tracks the leak under intervention and is invariant to the
issue (retrieved-not-derived). Detector reads only `commit_fn` output —
never transcript mention (anti-cheat).

Seeds: 16 (paired leak/derived → 32 cells).
Wall: 53.4s.

## Results

| metric | value | target |
|---|---:|---:|
| leak catch-rate (flag \| leak) | 1.00 | ≥ 0.80 |
| derived false-positive rate | 0.00 | < 0.10 |
| surface-perturbation FP rate | 0.00 | low |

### Per-mode summary

| mode | n | flagged | catch/FP |
|---|---:|---:|---:|
| leak | 16 | 16 | 1.00 |
| derived | 16 | 0 | 0.00 |

## Acceptance

- Catch ≥80%: PASS (1.00)
- FP <10%: PASS (0.00)
- Surface null FP documented: 0.00

## Artifacts

- `runs/runtime_contamination/results.jsonl`
- `runs/runtime_contamination/surface_calibration.jsonl`
