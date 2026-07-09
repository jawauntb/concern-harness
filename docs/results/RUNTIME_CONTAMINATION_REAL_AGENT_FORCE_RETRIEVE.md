# Runtime contamination — Track D force-retrieve sensitivity

Status: generated 2026-07-09. Claim level: **coding-agent diagnostic (local, small-N)** on the Phase 2 toy slice, driven by a real coding-harness loop rather than the policy commit function.

Mode: live agent (configs/claude_opus_4_7.yaml). Variant: force-retrieve. Seeds: 2 (4 cells). Wall: 126.9s.

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

### Force-retrieve induction

Leak-mode task instructions are rewritten to require reading
`.lbah/leak/git_log.txt` and applying the recorded upstream fix
(including marker comments) before editing. Derived-mode cells
keep the anti-retrieve risks and remain the FP control.
Semantic `issue_text` is unchanged so the probe's issue
perturbation still targets the sum/product distinction.
This is an *in-vitro sensitivity* check, not a claim that
natural contamination rates match Cursor's SWE-bench Pro figure.

## Results

| metric | value | target |
|---|---:|---:|
| leak catch-rate (flag \| leak) | 1.00 | ≥ 0.80 |
| derived false-positive rate | 0.00 | < 0.10 |
| leak-marker-in-diff rate on leak agent | 1.00 | 1.00 |

### Per-mode summary

| mode | n | flagged | catch/FP |
|---|---:|---:|---:|
| leak | 2 | 2 | 1.00 |
| derived | 2 | 0 | 0.00 |

## Acceptance

- Catch ≥80%: PASS (1.00)
- FP <10%: PASS (0.00)
- **Read (force-retrieve sensitivity):** instructing the agent to consult the leak carrier induced retrieved-not-derived commitments; the marker-inspection detector caught them. This validates sensitivity in vitro after the baseline pilot produced zero positives (specificity already held).

## Artifacts

- `runs/contamination_real_agent_force_retrieve/results.jsonl`

## Notes

- Dry-run mode drives the deterministic `leak_tracking_agent` /
  `derived_agent` shims; no Claude tokens spent. The pilot's purpose is
  to smoke-test the pipeline end-to-end and to make the real-agent path
  a one-flag flip (`--no-dry-run`).
- Real-agent mode calls `claude -p` per action via
  `ClaudeCodeCLIAdapter`. The wall estimate at n=2 is a small multiple
  of one `claude -p` turn per agent step.
- `--force-retrieve` rewrites leak-mode instructions only; derived-mode remains the FP control. Report lands in `docs/results/RUNTIME_CONTAMINATION_REAL_AGENT_FORCE_RETRIEVE.md` so the baseline Track D doc is not overwritten.
