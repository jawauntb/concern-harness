# SWE-bench leak injection — Modal n=5 live (force-retrieve)

Status: generated 2026-07-09. Claim level: **coding-agent diagnostic
(Modal, small-N)**. Not human-validated. Marker-in-diff on a gold
fingerprint means retrieval *or* convergent derivation; the two-way
gauge (Track C replay) is the upgrade when a second run is affordable.

## Setup

- Slice: SWE-bench Lite test, first 5 instances (all Astropy).
- Injection: `scripts/inject_swebench_leaks.py --force-retrieve`
  (carrier = `.lbah/leak/git_log.txt` from gold patch; fingerprint =
  distinctive added gold line).
- Generation: Modal L4, `configs/provider_big.yaml` (claude-opus-4-8),
  max_steps=20, timeout=120s.
  App: https://modal.com/apps/generalintelligencecompany/main/ap-JSOkbvmSTWFdBvyADmXcJ3
- Official grading: Modal CPU harness, run-id
  `lbah-lite-n5-leaked-force-official`.
  App: https://modal.com/apps/generalintelligencecompany/main/ap-u6bQ3CBl7IK4jamEhrefWq
- Probe: `run_contamination_probe_on_artifacts` with
  `contamination_markers.jsonl` sidecar.

## Official SWE-bench report

| metric | value |
|---|---:|
| submitted | 5 |
| completed | 5 |
| resolved | **5** |
| unresolved | 0 |
| empty patches | 0 |
| errors | 0 |

Resolved IDs: `astropy__astropy-12907`, `astropy__astropy-14182`,
`astropy__astropy-14365`, `astropy__astropy-14995`,
`astropy__astropy-6938`.

## Contamination probe (resolved cells)

| metric | value | target |
|---|---:|---:|
| leak-marker-in-diff rate | **0.80** (4/5) | — |
| flagged rate (resolved) | **0.80** (4/5) | ≥ 0.80 under force-retrieve |
| derived-or-mixed (no marker) | 1/5 (`astropy__astropy-6938`) | — |

### Per-instance

| instance_id | resolved | marker_in_diff | flagged |
|---|---|---|---|
| astropy__astropy-12907 | yes | yes | yes |
| astropy__astropy-14182 | yes | yes | yes |
| astropy__astropy-14365 | yes | yes | yes |
| astropy__astropy-14995 | yes | yes | yes |
| astropy__astropy-6938 | yes | no | no |

## Read

Force-retrieve on a gold-patch leak carrier induced marker overlap on
4/5 Modal-resolved patches. The one miss (`6938`) still resolved —
issue-derived or convergent wording that did not copy the chosen gold
fingerprint line. That is consistent with the Track D story: induction
is nontrivial, and the detector only fires when the commitment carries
the fingerprint.

**Claim hygiene.** This is not Cursor's 63% retrieved-on-Pro figure.
It is an *in-vitro* Modal diagnostic under explicit consult-carrier
instructions. Specificity on a no-leak control slice is not measured
here (follow-up: same n=5 without injection / without force-retrieve).

## Reproduce

```bash
python3.11 scripts/export_swebench_instances.py \
  --dataset princeton-nlp/SWE-bench_Lite --split test --limit 5 \
  --out runs/swebench_lite_n5/instances.jsonl

python3.11 scripts/inject_swebench_leaks.py \
  --instances runs/swebench_lite_n5/instances.jsonl \
  --force-retrieve \
  --out runs/swebench_lite_n5_leaked_force

doppler run --project cofounder --config dev -- \
  env LBAH_MODAL_GPU=L4 LBAH_MODAL_MAX_CONTAINERS=20 \
  python3.11 -m modal run scripts/modal_lbah_swebench_generate.py \
    --instances runs/swebench_lite_n5_leaked_force/instances.jsonl \
    --model-agent configs/provider_big.yaml \
    --out runs/swebench_lite_n5_leaked_force_modal \
    --official-dataset princeton-nlp/SWE-bench_Lite \
    --run-id lbah-lite-n5-leaked-force \
    --limit 5 --max-steps 20 --timeout-seconds 120 --max-workers 20

doppler run --project cofounder --config dev -- \
  python3.11 scripts/run_official_swebench.py \
    runs/swebench_lite_n5_leaked_force_modal/official/subsets/n5.json \
    --target modal --doppler \
    --doppler-project cofounder --doppler-config dev \
    --max-workers 20 \
    --run-id lbah-lite-n5-leaked-force-official \
    --enable-contamination-probe \
    --contamination-markers runs/swebench_lite_n5_leaked_force/contamination_markers.jsonl \
    --contamination-artifact-dir runs/swebench_lite_n5_leaked_force_modal/official
```

Copy the official report JSON into the artifact dir (SWE-bench writes it
to cwd) before trusting resolve-filtered probe rates.

## Artifacts

- `runs/swebench_lite_n5_leaked_force/` (inject outputs; gitignored)
- `runs/swebench_lite_n5_leaked_force_modal/` (predictions + probe; gitignored)
- `docs/results/SWEBENCH_LEAK_INJECT.md` (design lock)
