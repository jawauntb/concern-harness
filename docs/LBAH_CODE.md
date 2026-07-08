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

Recursive child harnessing and candidate patch tournaments now exist as bounded
Python API layers on top of the same parent loop. SWE-bench adapters are still
next steps.

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
coverage, diff focus, and whether a diff exists. A candidate that fails its own
verification can still appear in tournament artifacts, but it is never applied
to the target workspace.

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

1. Add reviewer gates to candidate tournaments so adversarial child output can
   down-rank patches that only satisfy tests accidentally.
2. Add SWE-bench Lite/Verified adapters with fixed budgets and comparable
   artifacts.
