# SWE-bench Modal Probe

Date: 2026-07-08

## Run

Generated one SWE-bench Lite prediction with LBAH-Code and graded it through
the official SWE-bench Modal path:

```bash
doppler run --project cofounder --config dev -- \
  lbah code swebench \
    --instances runs/swebench_lite_n5/instances.jsonl \
    --model-agent configs/provider_big.yaml \
    --official \
    --official-dataset princeton-nlp/SWE-bench_Lite \
    --official-run-id lbah-lite-probe-n1-fixed \
    --subset-sizes 1 \
    --limit 1 \
    --max-steps 20 \
    --timeout 120 \
    --skip-pass-to-pass \
    --out runs/swebench_lite_probe_n1_fixed

python scripts/run_official_swebench.py \
  runs/swebench_lite_probe_n1_fixed/official/subsets/n1.json \
  --target modal \
  --doppler \
  --doppler-project cofounder \
  --doppler-config dev \
  --max-workers 1 \
  --run-id lbah-lite-probe-n1-fixed-official
```

## Result

Official SWE-bench report:

- Instance: `astropy__astropy-12907`
- Submitted: 1
- Completed: 1
- Resolved: 1
- Unresolved: 0
- Empty patches: 0
- Errors: 0

Modal run:
https://modal.com/apps/generalintelligencecompany/main/ap-DglSaFz72SRYbTvA74bpN1

## Notes

The local smoke evaluator reported `fail_to_pass_failed` because the local Mac
checkout did not have the official per-instance astropy environment. Modal
official grading built the correct environment and resolved the instance. This
confirms that local smoke failures can be environment noise and that official
Modal grading is the right measured path for n=5/n=20/n=50.

## L4 Parallel Generation Probe

Generated five SWE-bench Lite predictions across Modal workers with
`LBAH_MODAL_GPU=L4` and graded the resulting prediction file with the official
Modal SWE-bench harness:

```bash
doppler run --project cofounder --config dev -- \
  env LBAH_MODAL_GPU=L4 LBAH_MODAL_MAX_CONTAINERS=20 \
  python -m modal run scripts/modal_lbah_swebench_generate.py \
    --instances runs/swebench_lite_n5/instances.jsonl \
    --model-agent configs/provider_big.yaml \
    --out runs/swebench_lite_n5_modal_l4 \
    --official-dataset princeton-nlp/SWE-bench_Lite \
    --run-id lbah-lite-n5-modal-l4 \
    --limit 5 \
    --max-steps 20 \
    --timeout-seconds 120 \
    --max-workers 20

python scripts/run_official_swebench.py \
  runs/swebench_lite_n5_modal_l4/official/subsets/n5.json \
  --target modal \
  --doppler \
  --doppler-project cofounder \
  --doppler-config dev \
  --max-workers 20 \
  --run-id lbah-lite-n5-modal-l4-official
```

Official SWE-bench report:

- Submitted: 5
- Completed: 5
- Resolved: 3
- Unresolved: 2
- Empty patches: 0
- Errors: 0
- Resolved IDs: `astropy__astropy-12907`, `astropy__astropy-14995`, `astropy__astropy-6938`
- Unresolved IDs: `astropy__astropy-14182`, `astropy__astropy-14365`

Modal runs:

- L4 patch generation:
  https://modal.com/apps/generalintelligencecompany/main/ap-vhbVT4azrBjoFC7clFWebj
- Official grading:
  https://modal.com/apps/generalintelligencecompany/main/ap-EXKQXqlO7krFDM74IXwCle

The official grader is CPU-bound, so the L4s are used by the patch-generation
worker. The grading result shows the pipeline can generate, package, and score
parallel SWE-bench attempts without harness failures; remaining work is patch
quality on the unresolved instances.

## Candidate Matrix Probe

Generated three candidate patches per SWE-bench Lite instance across Modal L4
workers, then graded each candidate column with the official Modal SWE-bench
harness:

```bash
doppler run --project cofounder --config dev -- \
  env LBAH_MODAL_GPU=L4 LBAH_MODAL_MAX_CONTAINERS=40 \
  python -m modal run scripts/modal_lbah_swebench_tournament.py \
    --instances runs/swebench_lite_n5/instances.jsonl \
    --model-agent configs/provider_big.yaml \
    --out runs/swebench_lite_n5_candidates \
    --official-dataset princeton-nlp/SWE-bench_Lite \
    --run-id lbah-lite-n5-candidates \
    --candidates-per-instance 3 \
    --limit 5 \
    --max-steps 20 \
    --timeout-seconds 120 \
    --max-workers 20

python scripts/run_official_swebench.py \
  runs/swebench_lite_n5_candidates/candidates/candidate_000/official/subsets/n5.json \
  --target modal \
  --doppler \
  --doppler-project cofounder \
  --doppler-config dev \
  --max-workers 20 \
  --run-id lbah-lite-n5-candidates-candidate_000-official
```

The same official grading command was repeated for `candidate_001` and
`candidate_002`, then summarized with:

```bash
python scripts/summarize_swebench_candidates.py \
  --matrix runs/swebench_lite_n5_candidates/candidate_matrix_manifest.json \
  --report lbah-lite-n5-candidates-candidate_000.lbah-lite-n5-candidates-candidate_000-official.json \
  --report lbah-lite-n5-candidates-candidate_001.lbah-lite-n5-candidates-candidate_001-official.json \
  --report lbah-lite-n5-candidates-candidate_002.lbah-lite-n5-candidates-candidate_002-official.json \
  --out runs/swebench_lite_n5_candidates/official_candidate_summary.json
```

Official SWE-bench reports:

| Candidate | Submitted | Completed | Resolved | Unresolved | Empty | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `candidate_000` | 5 | 5 | 3 | 2 | 0 | 0 |
| `candidate_001` | 5 | 5 | 3 | 2 | 0 | 0 |
| `candidate_002` | 5 | 5 | 3 | 2 | 0 | 0 |

Post-hoc oracle union:

- Resolved: 3/5
- Unresolved: 2/5
- Resolved IDs: `astropy__astropy-12907`, `astropy__astropy-14995`, `astropy__astropy-6938`
- Unresolved IDs: `astropy__astropy-14182`, `astropy__astropy-14365`
- Every candidate column resolved and missed the same instance set.

Modal runs:

- L4 candidate generation:
  https://modal.com/apps/generalintelligencecompany/main/ap-i59BUXNg2F23Ss8U985t4U
- Official grading, `candidate_000`:
  https://modal.com/apps/generalintelligencecompany/main/ap-rmpRlqxerX2lTCBv2Ia8ZO
- Official grading, `candidate_001`:
  https://modal.com/apps/generalintelligencecompany/main/ap-nPzW2ByXkqj0cGglAPljQc
- Official grading, `candidate_002`:
  https://modal.com/apps/generalintelligencecompany/main/ap-9uA65ZDFWBbASDq7tflqzs

This is a useful negative result. Parallel candidate columns did not improve
the small Astropy slice because the candidates were not meaningfully diverse
under the current prompt. The next lever is a stronger diversity/ranking policy:
distinct search roles, explicit child test-plan/reviewer feedback, temperature
or model variation where supported, and pre-official scoring from verifier,
ledger, and diff-focus signals.
