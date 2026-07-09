# SWE-bench sealed vs unsealed — Lite n=20

Status: generated 2026-07-09. Claim level: **coding-agent diagnostic (sealed/unsealed)**. Not SOTA. Not Cursor's natural 63% retrieved base rate — this is a harness-surface contrast on Lite with `provider_big` (Opus 4.8).

## Method

* **unsealed:** full git clone history retained; `.git` readable; remote shells allowed.
* **sealed:** after checkout + test_patch, wipe `.git` and reinit as a single commit; block curl/wget/`git clone|fetch|pull` in `CodingWorkspace.run_command` (best-effort; not a full network proxy).
* Same instances, model, max_steps, timeout. Official Modal grading.

## Results

| arm | submitted | resolved | resolve rate | empty | errors |
|---|---:|---:|---:|---:|---:|
| unsealed | 20 | 14 | 0.70 | 1 | 0 |
| sealed | 20 | 14 | 0.70 | 0 | 0 |

**Δ resolve (unsealed − sealed):** +0.00

### Resolve-set differences (same rate, different cells)

| only unsealed | only sealed |
|---|---|
| `django__django-11283` | `astropy__astropy-12907` |

Shared resolves: 13 IDs. Unsealed also had 1 empty patch (`astropy__astropy-12907`); sealed completed all 20 with 0 empty.

## Read

Headline resolve rates match (14/20 = 0.70). The history/network surface
did **not** inflate Lite n=20 the way Cursor's sealed drop did on Pro
(87.1→73.0). Two cells swapped rather than a one-sided sealed collapse.

Honest claim: on this Lite slice with Opus 4.8 / `provider_big`, sealing
git history + blocking remote shells is approximately resolve-neutral.
That is a **negative result for "Lite behaves like Pro under seal"** —
not evidence against Cursor on Pro, and not a natural-contamination base
rate. Next credibility steps remain: Pro (if accessible), larger N, or
the raw/LBAH/gated head-to-head — still no SOTA language.

## Artifacts

- `runs/sealed_unsealed_n20`
- unsealed report: `runs/sealed_unsealed_n20/unsealed/modal/official/official-report.json`
- sealed report: `runs/sealed_unsealed_n20/sealed/modal/official/official-report.json`
