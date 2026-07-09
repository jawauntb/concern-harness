# B2 spike — external leakage labels (timeboxed)

Status: 2026-07-09. Outcome: **not quickly usable for LBAH base-rate (c)**.
Fall back per plan: sealed-vs-unsealed n=20 (separate budget; not launched here).

## What we looked for

Instance-level labels that say a *resolved patch was retrieved rather than
derived at runtime* (Cursor 2026-06-25 sense), so our synthetic/gold probe
could be scored against an external ground truth.

## What exists

| Source | What it labels | Usable for (c)? |
|---|---|---|
| SWE-Bench+ / SoluLeakDetector ([arXiv:2410.06992](https://arxiv.org/abs/2410.06992); Zenodo [13879453](https://zenodo.org/records/13879453)) | **Issue-text** solution leak / hint in the problem statement | **No** for runtime retrieve. Different failure mode (input contamination vs harness retrieve). Dataset is a *filtered clean* slice, not a per-instance retrieved/derived tag on agent patches. |
| Cursor blog (2026-06-25) | Aggregate 63% retrieved on Pro (Opus 4.8 Max); sealed drop 87.1→73.0 | **No public instance-level dump** of which trajectories were retrieve vs derive. |
| SWE-bench Pro paper | Harder tasks / held-out repos | No retrieve labels. |

## Decision

B2 fails the timebox for *runtime* contamination base rate. Do **not**
pretend issue-text SoluLeak labels validate the Track D marker probe.

Next external contrast (when budget approved beyond the A-matrix 2×n=5):
**sealed-vs-unsealed n=20** on Lite with `provider_big`, claim level =
`coding-agent diagnostic (sealed/unsealed)` — not “natural contamination
base rate” and not Cursor 63%.

## Artifacts

- This note only. No Modal spend for B2.
