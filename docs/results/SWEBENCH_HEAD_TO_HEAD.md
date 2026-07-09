# SWE-bench head-to-head — raw / LBAH / gated / sealed

Status: generated 2026-07-09. Claim level: **coding-agent diagnostic (head-to-head)**. Not SOTA. Goal is to isolate raw vs LBAH vs gated vs sealed effects on Lite with `provider_big` (Opus 4.8), not optimize leaderboard performance.

## Arms

| arm | surface |
|---|---|
| raw | unsealed; raw coding prompt (no ledger coaching) |
| lbah | unsealed; LBAH coding prompt + certificates (reused sealed/unsealed unsealed) |
| gated | leak+force-retrieve; block finish when synthetic `LEAK_MARKER` is in the commitment |
| sealed | single-commit `.git` + block remote shells (reused sealed/unsealed sealed) |

## Results

| arm | submitted | resolved | resolve rate | empty | errors | synth flag/res |
|---|---:|---:|---:|---:|---:|---:|
| raw | 20 | 13 | 0.65 | 1 | 0 | — |
| lbah | 20 | 14 | 0.70 | 1 | 0 | — |
| gated (v2) | 20 | 20 | 1.00 | 0 | 0 | 4/20 |
| sealed | 20 | 14 | 0.70 | 0 | 0 | — |

Δ resolve (lbah − raw) = +0.05; (sealed − lbah) = +0.00.

### Gated arm detail (v2)

| metric | value |
|---|---:|
| generation rows with contamination-gate message | 17/20 |
| submitted patches still containing `LEAK_MARKER:` | 4/20 |
| official resolved | 20/20 |
| residual synth flags on resolved | 4/20 |

v1 (pre-fix) had 20/20 markers and 0 gate messages — the gate only ran after a
*successful* local finish, which Modal SWE-bench checkouts rarely hit. v2 fires
the gate on any `finish` when the marker is in the commitment.

## Read

Raw / LBAH / sealed are resolve-near-ties on this Lite n=20 slice — consistent
with `EVIDENCE.md`: deploy LBAH for audit/irreversible actions, not leaderboard
lift. Sealed reuse matches the earlier sealed/unsealed diagnostic (Δ = 0).

Gated is **not** comparable on resolve% to the clean arms: it runs under
leak+force-retrieve induction (helps solve rate) and measures whether the
finish gate engages. On v2 the gate engaged on 17/20 cells; agents often
revised the marker out and still resolved (20/20). Residual 4/20 markers are
budget/exhaustion cases, not proof the gate is inert. Claim: induced
overblock/revise diagnostic — not a natural contamination base rate, not SOTA.

## Artifacts

- `runs/head_to_head_n20`
- raw report: `runs/head_to_head_n20/raw/modal/official/official-report.json`
- lbah report: `runs/head_to_head_n20/lbah/modal/official/official-report.json`
- gated report: `runs/head_to_head_n20/gated/modal/official/official-report.json`
- sealed report: `runs/head_to_head_n20/sealed/modal/official/official-report.json`
