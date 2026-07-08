# LBAH — Load-Bearing Agent Harness

A general-purpose harness that wraps any LLM, local model, existing agent, or
multiagent framework and improves reliability by forcing the system to preserve
the right variables into the surfaces where actions are actually committed.

Central idea: an agent should not pass because it gives a right-looking answer.
It should pass when the right structure controlled the answer, tool call, code
diff, memory write, refusal, or action.

**Why does this exist?** LBAH operationalizes the *load-bearing standard for
representation claims* (Brown, 2026). The paper argues that most claims of
the form "the system has X" are supported by evidence of *availability* (X is
decodable, an activation correlates with it, a rationale mentions it) rather
than evidence of *use* (X causally controls what the system commits to). It
proposes a four-obligation contract — concern, transport, gauge, commitment
— that a claim must meet to count as load-bearing. See
[`docs/THEORY.md`](docs/THEORY.md) for the full mapping onto the code,
and [`docs/A Load-Bearing Standard for Representation Claims.pdf`](docs/A%20Load-Bearing%20Standard%20for%20Representation%20Claims.pdf)
for the paper.

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

## External harnesses and SOTA comparisons

LBAH can wrap black-box agent harnesses that expose an OpenAI-compatible chat
endpoint. This lets systems such as Fugu-style learned orchestrators,
OpenHands servers, or internal harness APIs propose actions while LBAH keeps
the concern ledger, transport checks, proxy adversary, freshness gates,
validators, and load-bearing certificates.

```
export SAKANA_API_KEY=...
lbah run --task moved_bottleneck:0 \
         --agent configs/fugu_openai_compatible.yaml \
         --mode audit --out runs/fugu_one/
```

Run a small model-harness matrix and generate an improvement report:

```
python scripts/harness_effects_matrix.py \
  --suite moved_bottleneck \
  --agents configs/dummy.yaml configs/oracle.yaml configs/fugu_openai_compatible.yaml \
  --modes guarded,audit \
  --seeds 16 \
  --out runs/harness_matrix/

lbah diagnose runs/harness_matrix/runs.jsonl \
  --out runs/harness_matrix/diagnostic_report.md
```

See [`docs/SOTA_HARNESS_INTEGRATION.md`](docs/SOTA_HARNESS_INTEGRATION.md)
for the research grounding, orchestration trace contract, and install path.

## LBAH-Code: verify-and-iterate coding harness

LBAH-Code is the first real-repository coding harness slice. It runs a bounded
inspect/edit/test/finish loop over a workspace, keeps the concern ledger as
working state, converts failed verification into retry feedback, and emits a
trace plus final diff.

```
lbah code run \
  --task task.yaml \
  --repo /path/to/repo \
  --actions scripted-actions.yaml \
  --out runs/code_one/
```

The same runner can use a model-backed coding agent:

```
lbah code run \
  --task task.yaml \
  --repo /path/to/repo \
  --model-agent configs/local_coding_agent.yaml \
  --out runs/code_model/
```

Scripted actions remain useful for reproducible tests and demos; model-backed
coding agents plug into the same `CodingHarnessRunner` contract. See
[`docs/LBAH_CODE.md`](docs/LBAH_CODE.md).

For stronger scaffolding, `RecursiveCodingHarnessRunner` can run bounded child
roles for repo navigation, test planning, patch proposal, and adversarial
review, then reduce validated child evidence into the same concern ledger
before the parent edit/test loop begins.

`CandidatePatchTournamentRunner` can also run multiple candidate agents in
isolated repo copies, score their verified patches by checks, concern coverage,
and diff focus, then apply only the best verified patch back to the target
workspace. Open reviewer or adversarial findings can down-rank otherwise passing
candidates through `review_signals`.

For benchmark comparability, `SWEBenchInstance` and
`swebench_to_coding_task()` convert SWE-bench-style JSON/JSONL rows into
fixed-budget coding tasks and comparable run artifacts. `lbah code swebench`
then runs smoke subsets by cloning/checking out each repo, applying
`test_patch`, running the harness, and writing per-instance failure taxonomy,
test logs, diffs, and suite summaries.

```
lbah code swebench \
  --instances swebench-lite.jsonl \
  --repo-root /repos \
  --model-agent configs/local_coding_agent.yaml \
  --official \
  --limit 5 \
  --out runs/swebench_smoke/
```

The `--official` flag writes `official/predictions.jsonl`,
`official/run_evaluation_command.json`, and n=5/n=20/n=50 subset manifests so
the same patches can be replayed through `swebench.harness.run_evaluation`.
Use `scripts/run_official_swebench.py` to execute those manifests locally or on
Modal; Modal runs can be wrapped with Doppler so `MODAL_TOKEN_ID` and
`MODAL_TOKEN_SECRET` stay out of shell history. Official grading parallelizes
with `--max-workers`; L4 GPUs are useful for Modal patch generation, while the
upstream official SWE-bench grader is CPU-bound.
For wide generation, `scripts/modal_lbah_swebench_generate.py` maps instances
across Modal workers and can request L4s with `LBAH_MODAL_GPU=L4`.
For self-consistency sweeps, `scripts/modal_lbah_swebench_tournament.py`
generates multiple candidates per instance across the same Modal pool and
writes one official replay command per candidate column. After grading each
candidate column, `scripts/summarize_swebench_candidates.py` compares the
official reports by instance and writes the post-hoc oracle union. Use that
summary to tune pre-official ranking signals; do not treat official labels as a
submission-time selector.

## Layout

- `lbah/core/` schemas, runner, scorer, ledger, certificates
- `lbah/coding/` real-repository coding harness primitives
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
