# LBAH-Code

LBAH-Code is the path from a safety/bookkeeping harness to a performance
harness for software engineering agents. The first slice is intentionally small:
real workspace operations, a verify-and-iterate runner, concern-led working
state, and reproducible traces.

## What It Adds

```
coding task
  -> CodingLedger
  -> CodingHarnessRunner
       -> inspect/search/read/edit/run_tests actions
       -> CodingWorkspace rooted at a repo
       -> CodingVerifier
       -> retry feedback on failed finish
  -> CodingRunResult with trace, checks, final diff
```

Recursive child harnessing, candidate patch tournaments, and SWE-bench smoke
evaluation now exist as bounded Python API layers on top of the same parent
loop.

## CLI Quickstart

Create a task file:

```yaml
task_id: toy_add
instruction: Fix add so it returns the sum.
test_commands:
  - [python, -m, pytest, -q]
allowed_paths: [math_utils.py, test_math_utils.py]
success_criteria:
  - pytest passes
known_risks:
  - Do not weaken tests.
max_steps: 8
```

Create scripted actions:

```yaml
name: scripted
actions:
  - action_id: inspect
    action_type: inspect
  - action_id: edit
    action_type: edit_file
    payload:
      path: math_utils.py
      old: return a - b
      new: return a + b
    rationale: The implementation subtracts; the task requires addition.
    concerns_addressed: [task, risk_0]
  - action_id: tests
    action_type: run_tests
  - action_id: finish
    action_type: finish
```

Run it:

```bash
lbah code run \
  --task task.yaml \
  --repo /path/to/repo \
  --actions scripted-actions.yaml \
  --out runs/code_one/
```

Or run the same task with a model-backed coding agent:

```bash
lbah code run \
  --task task.yaml \
  --repo /path/to/repo \
  --model-agent configs/local_coding_agent.yaml \
  --out runs/code_model/
```

Outputs:

- `coding_run.json` — trace, ledger, checks, modified files, timing
- `final.diff` — source diff against the workspace snapshot at run start

## Harness Contract

An agent only needs two methods:

```text
propose_action(state, ledger) -> CodingAction
observe(observation) -> None
```

`state` includes the last observation, workspace summary, and the live ledger.
`ledger` contains open concerns, evidence, and recent events. A failed
`finish` action returns structured verifier feedback, and the agent can keep
working until the step budget is exhausted.

## Recursive Child Harnesses

`RecursiveCodingHarnessRunner` runs typed child roles before the parent coding
loop:

```
coding task
  -> ChildTaskSpec repo_navigator / test_planner / patch_proposer / reviewer
  -> child agent returns ChildTaskResult
  -> validate required evidence, concern links, and ledger updates
  -> reduce child evidence into CodingLedger
  -> parent CodingHarnessRunner receives the recursive summary as context
```

Child tasks can be supplied explicitly through `CodingTask.metadata`:

```yaml
metadata:
  recursive_children:
    - child_id: nav
      role: repo_navigator
      goal: Find relevant implementation and tests.
      concerns: [task]
      evidence_required: [math_utils.py]
```

The runner blocks before any parent edits when a required child returns the
wrong role, wrong id, failed/skipped status, missing evidence, invalid ledger
updates, or proposed actions without rationale and concern linkage. This keeps
recursive planning load-bearing: child work has to carry usable evidence into
the parent patch loop rather than merely adding more prose.

## Candidate Patch Tournaments

`CandidatePatchTournamentRunner` runs multiple candidate agents in isolated
copies of the target repository, scores each patch, and only copies the winning
verified patch back to the real workspace:

```
coding task
  -> candidate_0 repo copy -> CodingHarnessRunner -> verifier checks
  -> candidate_1 repo copy -> CodingHarnessRunner -> verifier checks
  -> score checks + concern coverage + diff focus
  -> select best verified candidate
  -> apply winner files to the target workspace
```

Candidates are ranked by weighted verifier pass rate, high-concern ledger
coverage, diff focus, reviewer gates, and whether a diff exists. A candidate
that fails its own verification can still appear in tournament artifacts, but it
is never applied to the target workspace.

Candidate actions or observations can include `review_signals`:

```json
{
  "review_signals": [
    {
      "reviewer": "adversarial",
      "severity": "major",
      "summary": "Patch may overfit the visible test.",
      "evidence": ["Only one example was considered."]
    }
  ]
}
```

Open `blocker`, `major`, and `minor` findings subtract from the candidate score.
`addressed` and `rejected` findings remain in artifacts but do not penalize the
candidate. This is the tournament-level hook for recursive adversarial review:
tests can pass while reviewer concerns still change which patch wins.

At SWE-bench scale, the same idea is operationalized as a candidate matrix:
generate several independent patches per instance, write one official
prediction file per candidate column, then grade those columns with the
official harness. This keeps the benchmark contract honest: each candidate is a
normal SWE-bench prediction file, and selection/voting can happen outside the
single-candidate generation loop.

## SWE-Bench Adapters

`SWEBenchInstance` and `swebench_to_coding_task()` convert SWE-bench-style
JSON/JSONL rows into fixed-budget `CodingTask`s:

```python
from lbah.coding import SWEBenchInstance, swebench_to_coding_task

instance = SWEBenchInstance.from_mapping(row)
task = swebench_to_coding_task(instance, repo_path="/repos/django", max_steps=40)
```

The adapter normalizes `FAIL_TO_PASS` / `PASS_TO_PASS`, creates a pytest command
over the failing tests, and preserves benchmark metadata in the task. It does
not constrain `allowed_paths` from the gold patch by default; gold-patch path
inference is available only when explicitly requested for oracle/dev
comparisons. `swebench_run_artifact()` and `write_swebench_run_artifact()`
serialize comparable outputs with instance id, repo, base commit, final diff,
modified files, and the full LBAH-Code run.

This adapter is the benchmark contract layer. The smoke evaluator below adds
checkout, test-patch, execution, and artifact orchestration around it.

## SWE-Bench Smoke Evaluation

`run_swebench_instance()` prepares a per-instance workspace, applies the
SWE-bench `test_patch`, runs the LBAH-Code verify-and-iterate loop, then runs
FAIL_TO_PASS and PASS_TO_PASS tests as benchmark evidence:

```python
from lbah.coding import SWEBenchEvaluationOptions, run_swebench_instance

result = run_swebench_instance(instance, agent_factory, SWEBenchEvaluationOptions(
    repo_root="/repos",
    out_dir="runs/swebench_smoke",
    max_steps=40,
))
```

The evaluator can clone from a single `repo_source`, resolve repos under a
`repo_root` by `owner/name`, `owner__name`, or `name`, or fall back to
`https://github.com/{repo}.git`. It supports a local backend and a Docker test
backend that wraps configured test commands with `docker run -v
<repo>:/workspace -w /workspace <image> ...`.

The smoke-suite CLI runs JSON/JSONL subsets:

```bash
lbah code swebench \
  --instances swebench-lite.jsonl \
  --repo-root /repos \
  --model-agent configs/local_coding_agent.yaml \
  --official \
  --official-dataset princeton-nlp/SWE-bench_Verified \
  --limit 5 \
  --out runs/swebench_smoke/
```

Artifacts include:

- `summary.json` and `runs.jsonl` for the suite
- `instances/<id>/evaluation.json`
- `instances/<id>/coding_run.json`
- `instances/<id>/final.diff`
- `instances/<id>/logs/fail_to_pass.json`
- `instances/<id>/logs/pass_to_pass.json`
- `official/predictions.jsonl` when `--official` is enabled
- `official/run_evaluation_command.json`
- `official/subsets/n5.json`, `n20.json`, and `n50.json`

Failure taxonomy is explicit: checkout failure, test patch failure, harness
error, agent verifier failure, no patch, FAIL_TO_PASS failure, PASS_TO_PASS
regression, or success. This turns failed benchmark runs into sortable
engineering signal instead of one opaque score.

The smoke evaluator is the fast local signal. With `--official`, LBAH also
writes the official SWE-bench harness inputs:

```bash
python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --predictions_path runs/swebench_smoke/official/predictions.jsonl \
  --max_workers 8 \
  --run_id lbah-code \
  --cache_level env \
  --instance_ids ...
```

This mirrors the official Docker harness contract: a prediction row contains
`instance_id`, `model_name_or_path`, and `model_patch`, and the official
`swebench.harness.run_evaluation` command owns the base/env/instance image
setup, patch application, test execution, and grading. The generated subset
manifests make n=5, n=20, and n=50 runs repeatable while scaling toward full
Verified or Lite runs.

The remaining leaderboard step is operational rather than architectural:
install the official `swebench` package, provision Docker storage/CPU, and run
the generated command against the desired subset or full dataset.

### Official Runner Workflow

Install the optional benchmark dependencies when you are ready to run measured
subsets:

```bash
python -m pip install -e '.[swebench]'
```

Export a small public subset for the LBAH smoke runner:

```bash
python scripts/export_swebench_instances.py \
  --dataset princeton-nlp/SWE-bench_Lite \
  --split test \
  --limit 5 \
  --out runs/swebench_lite_n5/instances.jsonl
```

Generate LBAH patches and official replay artifacts:

```bash
doppler run --project cofounder --config dev -- \
  lbah code swebench \
    --instances runs/swebench_lite_n5/instances.jsonl \
    --model-agent configs/provider_big.yaml \
    --official \
    --official-dataset princeton-nlp/SWE-bench_Lite \
    --official-run-id lbah-lite-n5 \
    --subset-sizes 5 \
    --out runs/swebench_lite_n5
```

Grade those patches with the official harness on Modal:

```bash
python scripts/run_official_swebench.py \
  runs/swebench_lite_n5/official/subsets/n5.json \
  --target modal \
  --doppler \
  --doppler-project cofounder \
  --doppler-config dev \
  --max-workers 8
```

Use local execution only for tiny validation runs on machines with Docker and
enough disk. On ARM Macs, the runner defaults local commands to `--namespace ''`
so official images build locally instead of pulling incompatible x86 images.
This repository's default path is Modal for n=5/n=20/n=50 sweeps.

Official SWE-bench Modal grading is CPU/build/test bound. The upstream
`swebench.harness.modal_eval` runner parallelizes instances with
`--max_workers`, but its Modal sandbox currently hardcodes CPU execution and
does not expose L4/GPU selection. Use high `--max-workers` for official grading;
reserve L4s for a separate Modal patch-generation worker when running local or
open-weight coding models.

For parallel L4-backed patch generation, use the Modal generation script:

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
    --max-steps 20
```

Then grade the generated predictions with official CPU-parallel Modal:

```bash
python scripts/run_official_swebench.py \
  runs/swebench_lite_n5_modal_l4/official/run_evaluation_command.json \
  --target modal \
  --doppler \
  --doppler-project cofounder \
  --doppler-config dev \
  --max-workers 20 \
  --run-id lbah-lite-n5-official
```

For self-consistency runs, generate a candidate matrix instead of one patch per
instance:

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
```

That writes:

- `candidate_generation_results.json` for every `(instance, candidate)` worker
- `candidate_matrix_manifest.json` with all candidate replay commands
- `candidates/candidate_000/official/run_evaluation_command.json`
- `candidates/candidate_001/official/run_evaluation_command.json`
- `candidates/candidate_002/official/run_evaluation_command.json`
- one `subsets/n*.json` manifest per candidate column

Grade each candidate column with `scripts/run_official_swebench.py`. The next
ranking layer should compare the official reports by instance:

```bash
python scripts/summarize_swebench_candidates.py \
  --matrix runs/swebench_lite_n5_candidates/candidate_matrix_manifest.json \
  --report candidate_000=path/to/candidate_000-official.json \
  --report candidate_001=path/to/candidate_001-official.json \
  --report candidate_002=path/to/candidate_002-official.json \
  --out runs/swebench_lite_n5_candidates/official_candidate_summary.json
```

The summary reports per-candidate resolved counts, per-instance candidate
classifications, and the post-hoc oracle union. Use that oracle union to test
whether candidate diversity exists and to tune the pre-official scoring policy;
avoid treating post-hoc official labels as a valid test-set submission strategy.

The first Modal proofs are recorded in `docs/results/SWEBENCH_MODAL_PROBE.md`:
a one-instance SWE-bench Lite run resolved `astropy__astropy-12907`, and an
L4-parallel n=5 generation plus official Modal grading run resolved 3/5 with
zero empty patches or harness errors.

## Model-Backed Agents

`ModelCodingAgent` wraps any existing `ModelAdapter` that exposes `complete()`.
It sends the workspace summary, recent observations, and live ledger to the
model, asks for one JSON action, validates it into `CodingAction`, and feeds
malformed responses back through the runner as retry observations.

The model must return a JSON object such as:

```json
{
  "action_type": "edit_file",
  "payload": {
    "path": "math_utils.py",
    "old": "return a - b",
    "new": "return a + b"
  },
  "rationale": "The function subtracts; tests require addition.",
  "concerns_addressed": ["task", "risk_0"]
}
```

If the response is fenced markdown or includes surrounding prose, the parser
extracts the first JSON object. If no JSON object is present, the runner records
a `proposal_error` observation and gives the model another step.

## Verification

The MVP verifier checks:

- configured test commands pass
- edits stay within `allowed_paths` when provided
- a diff exists
- the diff does not add obvious skip/xfail/pass weakening
- high-concern ledger items have evidence or are addressed

Python bytecode caches are invalidated after edits so rapid edit-test loops do
not accidentally test stale same-size source files.

## Next SOTA Steps

1. Run the generated official SWE-bench commands on n=5, n=20, and n=50 subsets
   with Docker provisioned, then track solve-rate and failure-taxonomy deltas.
