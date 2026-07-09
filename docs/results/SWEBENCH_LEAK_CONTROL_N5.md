# SWE-bench leak control matrix — n=5 Lite

Status: generated 2026-07-09. Claim level: **coding-agent diagnostic (Modal, small-N)**. Not SOTA. Not a natural contamination base rate. Primary gate = synthetic `LEAK_MARKER`; gold-line overlap is a secondary noisy diagnostic.

## Arms

| arm | setup | primary gate |
|---|---|---|
| A0 | clean export, no carrier | synthetic FP (must be low) |
| A1 | leak carrier, no force-retrieve | induction without prompting |
| A2 | leak + force-retrieve | sensitivity (target ≥ 0.80) |

Pre-registered gates: A0 synthetic flag rate < 0.20; A2 synthetic flag rate ≥ 0.80.

## Results

| arm | resolved | synth flagged | synth rate | gold overlap | gold rate |
|---|---:|---:|---:|---:|---:|
| A0 (clean (no leak)) | 2/5 | 0 | 0.00 | 1 | 0.50 |
| A1 | — | — | — | — | — |
| A2 (leak + force-retrieve) | 5/5 | 5 | 1.00 | 5 | 1.00 |

## Acceptance

- A0 synthetic FP < 0.20: PASS (0.00)
- A0 gold-line overlap (secondary): 0.50 — noisy; do not use gold-line for specificity gate
- A2 synthetic catch ≥ 0.80: PASS (1.00)

## Read

Specificity (synthetic) and sensitivity (force-retrieve) both hold on this
n=5 slice. Gold-line overlap on A0 is 0.50 — as expected when the correct
fix converges; per user lock, specificity gates on synthetic only.

A1 (leak, no force) was **not** launched: budget was ≤2×n=5 and A0+A2
consumed it (A2 needed a fresh synthetic-marker run; old gold-line A2
was not reusable for the primary gate).

B2 label hunt (timeboxed) **failed** for runtime-retrieve base rate —
see `docs/results/B2_LABEL_HUNT.md`. Next external contrast when budget
allows: sealed-vs-unsealed n=20 (honest sealed/unsealed diagnostic).
Head-to-head raw/LBAH/gated/sealed remains open; no SOTA language.

## Artifacts

- Matrix root: `runs/leak_control_n5`
- A0 probe: `runs/leak_control_n5/A0_clean/modal/contamination_probe.jsonl`
- A2 probe: `runs/leak_control_n5/A2_force/modal/contamination_probe.jsonl`
