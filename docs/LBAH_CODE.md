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

This is not yet SWE-bench integration or recursive child harnessing. It is the
core loop those features need.

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

1. Add a model-backed coding adapter that emits `CodingAction`.
2. Add recursive child harnesses for inspection, patch proposal, review, and
   test planning.
3. Add candidate patch tournaments scored by tests, diff focus, concern
   coverage, and reviewer gates.
4. Add SWE-bench Lite/Verified adapters with fixed budgets and comparable
   artifacts.
