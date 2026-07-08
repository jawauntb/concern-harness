# LBAH — Load-Bearing Agent Harness

A general-purpose harness that wraps any LLM, local model, existing agent, or
multiagent framework and improves reliability by forcing the system to preserve
the right variables into the surfaces where actions are actually committed.

Central idea: an agent should not pass because it gives a right-looking answer.
It should pass when the right structure controlled the answer, tool call, code
diff, memory write, refusal, or action.

## Install

```
pip install -e .
```

## Quickstart

```
# Run one task
lbah run --task lbah/benches/moved_bottleneck/task_seed_1.yaml \
         --agent configs/dummy.yaml --mode guarded --out runs/one/

# Run a full suite
lbah bench --suite moved_bottleneck --agent configs/dummy.yaml \
           --mode guarded --seeds 32 --out runs/moved_dummy/

# Compare agents
lbah compare --suite moved_bottleneck \
             --agents configs/dummy.yaml configs/oracle.yaml \
             --mode guarded --seeds 32 --out runs/compare/

# Leaderboard
lbah leaderboard runs/compare/

# Replay a single run
lbah replay runs/one/run.json
```

## Layout

- `lbah/core/` schemas, runner, scorer, ledger, certificates
- `lbah/adapters/` model and agent adapters (dummy, HTTP, CLI, provider, local, MoE)
- `lbah/modules/` concern mapper, transport auditor, proxy adversary,
  reopenability governor, commitment controller, verifier, surface mapper
- `lbah/environments/` tool-use, coding, retrieval, memory, browser environments
- `lbah/validators/` deterministic gates
- `lbah/benches/` five built-in benchmark suites
- `lbah/prompts/` prompt templates for LLM-backed modules
- `configs/` YAML agent + mode configs
- `tests/` pytest suite

## The core loop

```
task
  -> concern mapper (extract variables that must survive)
  -> surface mapper (identify commitment surfaces)
  -> agent proposes action
  -> transport auditor (did the variables reach the action?)
  -> proxy adversary (could this pass for the wrong reason?)
  -> reopenability governor (any stale/ambiguous variable?)
  -> validators (deterministic surface-level gates)
  -> commitment controller (allow / block / reopen / revise / ask)
  -> environment executes
  -> load-bearing certificate emitted
```
