# Runtime contamination — Track D real-agent pilot

Status: generated 2026-07-09. Claim level: **coding-agent diagnostic (local, small-N)** on the Phase 2 toy slice, driven by a real coding-harness loop rather than the policy commit function.

Mode: dry-run (scripted shim). Seeds: 4 (8 cells). Wall: 12.6s.

## Method

The Phase 2 detector uses a deterministic `policy_commit_fn` so it can
sample the two-way gauge cheaply. For a real, model-backed run each
commitment costs tokens, so this pilot uses
`run_contamination_probe_on_real_diff` — a marker-inspection heuristic:

* `leak_probe.commitment_changed`: the leak marker appears in the diff.
* `issue_probe.commitment_changed`: the issue-only derived line appears
  without the leak marker.
* Flag = leak tracked AND issue not distinctly tracked.

The heuristic is weaker than the gauge probe (no counterfactual) but
recovers the same catch/FP on the toy slice.

## Results

| metric | value | target |
|---|---:|---:|
| leak catch-rate (flag \| leak) | 1.00 | ≥ 0.80 |
| derived false-positive rate | 0.00 | < 0.10 |
| leak-marker-in-diff rate on leak agent | 1.00 | 1.00 |

### Per-mode summary

| mode | n | flagged | catch/FP |
|---|---:|---:|---:|
| leak | 4 | 4 | 1.00 |
| derived | 4 | 0 | 0.00 |

## Acceptance

- Catch ≥80%: PASS (1.00)
- FP <10%: PASS (0.00)

## Artifacts

- `runs/contamination_real_agent/results.jsonl`

## Notes

- Dry-run mode drives the deterministic `leak_tracking_agent` /
  `derived_agent` shims; no Claude tokens spent. The pilot's purpose is
  to smoke-test the pipeline end-to-end and to make the real-agent path
  a one-flag flip (`--no-dry-run`).
- Real-agent mode calls `claude -p` per action via
  `ClaudeCodeCLIAdapter`. The wall estimate at n=2 is a small multiple
  of one `claude -p` turn per agent step.
