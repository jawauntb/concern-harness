# SWE-bench leak injection — Track D / §4.4 (b)

Status: 2026-07-09. Claim level: **infrastructure / coding-agent diagnostic
scaffold**. No Modal credits burned; no live catch/FP numbers yet.

## Design lock (open question → closed)

| choice | decision |
|---|---|
| Carrier shape | On-disk `.lbah/leak/git_log.txt` (same path as the toy slice) |
| Fingerprint | Distinctive *added* line from the gold patch (not a synthetic comment) |
| Official grading | Carrier lives only in the *generation* checkout; grader applies `model_patch` to a clean base |
| Induction | Optional `--force-retrieve` rewrites `problem_statement` (mirrors Track D) |
| Detector | Existing marker-inspection heuristic via `contamination_markers.jsonl` sidecar |

Marker-in-diff on a gold fingerprint means retrieval *or* convergent
derivation. Claim level stays coding-agent diagnostic; the two-way gauge
(Track C replay) is the upgrade when a second run is affordable.

## How to build a leaked slice (free)

```bash
# 1. Export a small Lite slice (needs `datasets`)
python3.11 scripts/export_swebench_instances.py \
  --dataset princeton-nlp/SWE-bench_Lite --split test --limit 5 \
  --out runs/swebench_lite_n5/instances.jsonl

# 2. Inject leak carriers + markers sidecar
python3.11 scripts/inject_swebench_leaks.py \
  --instances runs/swebench_lite_n5/instances.jsonl \
  --out runs/swebench_lite_n5_leaked

# Optional: induce retrieval the way Track D --force-retrieve does
python3.11 scripts/inject_swebench_leaks.py \
  --instances runs/swebench_lite_n5/instances.jsonl \
  --force-retrieve \
  --out runs/swebench_lite_n5_leaked_force
```

Outputs under `--out`:

- `instances.jsonl` — annotated generation input (`metadata.contamination`)
- `contamination_markers.jsonl` — sidecar for the retroactive probe
- `inject_manifest.json` — counts + skipped ids (no gold patch)

## How checkout plants the carrier

`prepare_swebench_workspace` writes `.lbah/leak/git_log.txt` whenever
`instance.metadata["contamination"]` is present. `swebench_to_coding_task`
adds the path to `allowed_paths` and sets known_risks (anti-retrieve by
default; consult-carrier under force-retrieve).

## Modal launch (credits; not run in this PR)

```bash
doppler run --project cofounder --config dev -- \
  env LBAH_MODAL_GPU=L4 LBAH_MODAL_MAX_CONTAINERS=20 \
  python -m modal run scripts/modal_lbah_swebench_generate.py \
    --instances runs/swebench_lite_n5_leaked_force/instances.jsonl \
    --model-agent configs/provider_big.yaml \
    --out runs/swebench_lite_n5_leaked_force_modal \
    --official-dataset princeton-nlp/SWE-bench_Lite \
    --run-id lbah-lite-n5-leaked-force \
    --limit 5 --max-steps 20 --timeout-seconds 120 --max-workers 20

# Grade, then retroactive probe
python3.11 scripts/run_official_swebench.py \
  runs/swebench_lite_n5_leaked_force_modal/official/subsets/n5.json \
  --target modal --doppler \
  --doppler-project cofounder --doppler-config dev \
  --max-workers 20 \
  --run-id lbah-lite-n5-leaked-force-official \
  --enable-contamination-probe \
  --contamination-markers runs/swebench_lite_n5_leaked_force/contamination_markers.jsonl \
  --contamination-artifact-dir runs/swebench_lite_n5_leaked_force_modal
```

## Acceptance (this PR)

- [x] Pure inject path + fingerprint + force-retrieve (unit tested)
- [x] Checkout plants carrier from annotated metadata
- [x] Markers sidecar feeds `run_contamination_probe_on_artifacts`
- [x] Live Modal n=5 force-retrieve: 5/5 resolved, 4/5 flagged
  (`docs/results/SWEBENCH_LEAK_INJECT_MODAL_N5.md`)
- [ ] No-leak / no-force-retrieve control slice (specificity)
- [ ] Two-way gauge via Track C replay capture

## Artifacts

- `lbah/coding/contamination/inject.py`
- `scripts/inject_swebench_leaks.py`
- `tests/test_swebench_leak_inject.py`
