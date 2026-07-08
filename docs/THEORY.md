# The theory behind LBAH

LBAH is a runtime that operationalizes the "load-bearing standard" for
representation claims proposed in
[*A Load-Bearing Standard for Representation Claims*](./A%20Load-Bearing%20Standard%20for%20Representation%20Claims.pdf)
(Brown, 2026, draft). This document sketches the standard and shows exactly
where each obligation lives in the code.

The paper starts from a clean observation about interpretability, causal
representation learning, and agent safety: all three fields keep confusing
**evidence of availability** (X is decodable, an activation correlates with
it, a rationale mentions it) with **evidence of use** (X causally controls
what the system commits to). The gap between the two is where deployment
surprises, unfaithful explanations, and mislocated mechanisms live.

The standard makes "the system has X" refuse to type-check unless four
inspectable fields are filled in. LBAH turns those four fields into runtime
gates around every agent action.

## The four obligations

For a representation claim to be **load-bearing** at concern scale μ, the
paper requires the following. On the right is the LBAH module that carries
the obligation.

| Obligation | Paper (§2) | LBAH module |
|-----------|-----------|-------------|
| **Concern** — which distinctions matter, with what weight, for the surface where control is fixed | concern density ρ(x) | `modules/concern_mapper.py` → `ConcernVariable(concern: float)` |
| **Transport** — the distinction must survive from perception to commitment | transport loss on the chain c₀ → c₁ → … → c_action | `modules/transport_auditor.py` |
| **Gauge fixing** — an intervention separating the claimed description from observationally equivalent alternatives | gauge-fixing intervention, scale γ | `modules/proxy_adversary.py` (proxies are the gauge-equivalent alternatives; each proxy check is a gauge-fixing test) + `modules/reopenability_governor.py` (a stale variable is an unfixed gauge in time) |
| **Commitment effect** — changing the distinction changes what the agent does | commitment effect Δ(x) | `environments/*.py::execute` + `validators/*` (validators measure whether the payload the model committed actually differs on the concern variable) |

The paper's inequality

> Load ≥ initial concern mass − transport loss, times gauge-fixing scale γ, times gauge-corrected commitment effect

is not a deep theorem — the paper says so explicitly ("a product of two
nonnegative lower bounds; the proof is one line and carries no predictive
content… read it as a definition of terms and an evidence contract, not a
theorem"). Its job is bookkeeping: the inequality cannot even be written
down unless the four fields are supplied.

LBAH's `LoadBearingCertificate` is exactly that bookkeeping. Every action
proposal emits one:

```
LoadScore = behavior × transport × proxy_resistance × reopenability × commitment_validity
```

with the failed gates listed. An action can be blocked, reopened, or
revised on any missing field.

## Two operational laws (paper §3) and how they show up here

### Moved-bottleneck law
> If concern mass shifts along the chain (the operative variable changes
> context between perception and commitment), any estimator or evaluator
> that ignores concern weighting is subject to a lower bound on
> deployment error that concern-weighted selection escapes.

**In LBAH**: the `moved_bottleneck` suite generates tasks whose critical
slot moves between seeds. The `TransportAuditor` weights every gate by
`concern`, so a variable that mattered in an earlier context doesn't
inflate the score once its concern mass has moved.

### Decodability-is-not-load law
> If a claimed description D and an observationally-equivalent D' produce
> the same commitments, no procedure using only observations and
> commitments can identify D from D'.

**In LBAH**: this is why the `ProxyAdversary` exists. For every high-concern
variable there is at least one proxy — a way the payload can look right
without carrying the intended distinction. Proxies are the gauge-equivalent
alternatives. The proxy check is the gauge-fixing intervention. Without at
least one intervention or contrast, the claim "the agent used this variable"
is not identified.

## The seven-step protocol (paper §5), mapped

| # | Step from the paper | Where LBAH does it |
|---|---------------------|--------------------|
| 1 | Name the commitment surface | `SurfaceMapper` returns `CommitmentSurface(id, type, irreversible, validators)` |
| 2 | Define the concern density | `ConcernMapper` returns `list[ConcernVariable]` |
| 3 | Specify the transport chain | Task metadata's `required_surfaces` per variable |
| 4 | List gauge alternatives | Task metadata's `proxy_risks` + `ProxyAdversary` |
| 5 | Choose gauge-fixing interventions | `ProxyAdversary` deterministic checks + env-supplied `proxy_checks` |
| 6 | Measure the commitment effect | `Verifier` (deterministic validators) + `env.execute` + `env.success` |
| 7 | Report the bound | `LoadBearingCertificate` (load_score, per-gate scores, failed_gates list) |

A claim that cannot fill steps 4–6 is called *availability, not load-bearing*
in the paper. In LBAH, an action that emits no proxy check and no
commitment validator gets `proxy_resistance=1.0` and `commitment_validity=1.0`
by default — and we log the fact that the check was **skipped**, not passed.
That's deliberate: silent absence of evidence must not read as evidence.

## Application: chain-of-thought faithfulness (paper §6)

The paper closes with the load-bearing standard applied to CoT faithfulness:
"the model used reasoning step s" is treated as a load-bearing claim and
each obligation becomes a faithfulness eval. LBAH lifts this from "measure
one model" to "gate every action": every step of every agent produces a
certificate for whether the reasoning it *reports* is the reasoning that
*controlled* the commitment.

The `RunResult` from `core/runner.py` is a full transcript in this form —
each entry is one such faithfulness measurement.

## Application: multi-agent harnesses and learned orchestration

Fugu-style orchestrators, SWE-agent-style interfaces, and OpenHands-style
platforms make the harness itself a major source of capability. LBAH's theory
does not treat that as a separate object from the load-bearing standard. It
treats orchestration as another transport chain.

For a multi-agent workflow, the chain is no longer just:

```
task -> context -> model proposal -> action
```

It can be:

```
task -> coordinator -> planner handoff -> worker handoff -> verifier handoff -> action
```

The same four obligations apply:

- **Concern**: the coordinator must know which variables matter.
- **Transport**: each handoff that can affect the final surface must carry
  the high-concern variables it needs.
- **Gauge fixing**: worker isolation and explicit access lists prevent every
  agent from being steered by the same proxy trajectory.
- **Commitment effect**: the final tool call, diff, answer, or memory write
  must still change when the concern variable changes.

This is why `modules/orchestration_auditor.py` emits ordinary `GateResult`
objects rather than a separate certificate type. Multi-agent traces become
transport and proxy evidence inside the same `LoadBearingCertificate`.

## Scope (paper §7, echoed here)

The paper is careful about scope, and so is LBAH:

- This is a **measurement discipline**, not a theory of intelligence.
- The load inequality is a definition of terms, not a predictive theorem.
- Concern must be **exogenous** (declared by task authors or an
  authorized deployment context), not extracted from the model's own
  activations — that circularity is the trap the standard exists to
  avoid.
- Empirical support is **synthetic and illustrative** in the paper. The
  same caveat applies to LBAH's built-in benchmark suites: they are
  designed to force each obligation to be paid at least once.

For real evidence that the harness improves reliability over prompt
engineering alone, see the ablation scripts under `scripts/` and the
`runs/` directory:
- `scripts/ablation_matched_prompt.py` — same schema, no gates vs. gates
- `scripts/overblocking_test.py` — false-block rate on oracle actions
- `scripts/heldout_proxy_twins.py` — proxies the ledger did NOT declare
- `scripts/swebench_lite_mini.py` — public benchmark subset
