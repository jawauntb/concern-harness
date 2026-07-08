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
