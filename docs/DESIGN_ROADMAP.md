# LBAH Design Roadmap — toward a SOTA harness rooted in the load-bearing standard

Status: draft, 2026-07-09. Owner: this branch (`claude/ai-loops-autonomous-cgwz7g`).
Scope: turns the event-sourced ledger + gauge-fixing probe (merged in #26) into
the backbone of a state-of-the-art, *theory-first* agent harness.

This document is meant to be **followed**. Every phase has concrete files,
tasks, and falsifiable acceptance criteria. It is grounded in (a) a full
repository exploration and (b) a July-2026 literature survey — both summarized
inline with file/line and source references.

---

## 0. The one-sentence thesis

Every deployed guardrail today gates on **correlation** — *is the right value
present / did it plausibly flow into the action* (CaMeL's taint tags,
Agent-Sentry's learned provenance envelopes, No-Certificate-No-Execution's
policy permissibility). LBAH's unclaimed territory is to gate on **control** —
*did the right distinction actually move the commitment, verified by
intervention.* "Generation is not permission" (No-Certificate-No-Execution);
LBAH adds **"correlation is not control."**

That is the load-bearing standard (`docs/THEORY.md`) restated as a product
position. The roadmap below is the path from "we have the mechanism" to "we
have the evidence, at scale, that beats the field at its known weak point."

---

## 1. Where we actually are (grounded in the code)

### 1.1 What shipped in #26 and works

- **Event-sourced concern ledger** (`lbah/core/events.py`): append-only
  `ConcernEventLog`, `ConcernLedger` as a deterministic seq-ordered projection,
  `lineage()` / `fork_at()` / `diff()`. Wired into the runner
  (`core/runner.py`), surfaced on `RunResult.event_log`, inspectable via
  `lbah replay --lineage <var>`.
- **Interventional gauge-fixing probe** (`gauge_fixing_probe`): perturbs a
  concern variable's value *across every carrier in the agent's input bundle*
  (the ledger node and the task metadata the ledger embeds), diffs the
  commitment, and returns a transport-scoped three-way verdict
  (`gauge_fixed` / `invariant_but_value_present` / `invariant_and_absent`).
- 104 tests green; default runtime behavior is bit-identical to pre-#26.

### 1.2 Measured effect (32-seed `moved_bottleneck`, `guarded` mode)

| config | oracle proxy-score | first_slot | constant | oracle−constant gap |
|---|---|---|---|---|
| pre-#26 / probe off | 1.000 | 0.603 | 0.529 | 0.471 |
| probe on (`budget=2`) | 1.000 | 0.501 | 0.409 | **0.591** |

The probe widens the separation between a load-bearing agent and a
ledger-ignoring one by ~25%, while a correct agent keeps a perfect score. This
is the harness's core job (separating use from availability), and it improved.

### 1.3 The honest critique — six gaps

**G1 — The gauge probe is dormant in every real run.** `gauge_probe_budget`
defaults to `0` (`core/runner.py`) and *nothing in the CLI ever sets it > 0*
(only the unit tests do). So `lbah run/bench/compare` build the event log and
all the gauge machinery, then never fire the probe. Every headline number in
`docs/EVIDENCE.md` (e.g. "held-out proxy 5/5 caught") comes from the
`transport_auditor`, **not** from the interventional probe. This is the highest
value/lowest cost fix in the repo.

**G2 — Two disjoint harness stacks.** The concern/gate stack (`core/`,
`modules/`, `environments/`, `benches/`) and the coding stack (`coding/`) share
vocabulary but almost no code. `lbah/coding/` has **zero** references to
`LoadBearingCertificate`, `make_certificate`, or `ConcernEventLog`. Its
`CodingLedger` (`coding/ledger.py`) is mutable and lossy — the exact pattern
`core/events.py` was written to replace. `CandidatePatchTournamentRunner`
literally forks repos and diffs commitments, yet uses none of the gauge/lineage
machinery. The SWE-bench side — where the real benchmark credibility lives — is
not covered by the theory at all.

**G3 — The telemetry gap.** `EVIDENCE.md` admits per-component scores
(`transport_score`, `proxy_resistance_score`, …) are persisted on only ~12 of
1404 rows, so the component ablation and the load-inequality "bound test" are
under-powered. Event-sourcing was supposed to fix persistence but hasn't been
extended to cover the score fields diagnostics reads.

**G4 — The LLM-backed modules are un-wired.** `LLMConcernMapper` and friends
exist, and `lbah/prompts/*.txt` spell out their JSON contracts, but the CLI
always constructs the deterministic variants, and **the prompt files are never
read by any code** (the live prompt is an inline string). The harness has only
ever been evaluated with hand-authored `task.metadata` concern variables — i.e.
the concern-mapping obligation is assumed, not tested end-to-end.

**G5 — Environments are toy.** Every environment is an in-memory simulation;
`coding_env.run_tests` is a "deterministic stub" that string-matches a symbol.
The only *executed* (not simulated) benchmark evidence is
`docs/results/SWEBENCH_MODAL_PROBE.md` (n=1 and n=5 official-graded Modal runs,
with honest negative results). Claims of realism must route through the coding
stack, not the synthetic suites.

**G6 — Citation hygiene.** `docs/SOTA_HARNESS_INTEGRATION.md` cites 2026 arXiv
IDs that appear fabricated/placeholder. This must be purged before any external
write-up; see §5 caveat — the survey below has the same risk and is flagged.

---

## 2. Competitive landscape (grounded in the survey)

> Caveat: the July-2026 survey could not fetch arXiv/leaderboard pages directly
> (proxy 403s); paper details come from search-result summaries and **arXiv IDs
> are unverified**. Treat the *ideas and positioning* as load-bearing and every
> specific ID as "verify before citing." Do not repeat G6.

### 2.1 Where the field is

- **Harness > model, and the field now knows it.** The "Binding Constraint
  Thesis" position (harness-induced variance exceeds model-induced variance on
  long-horizon tasks; leaderboards without harness disclosure mislead). SWE-bench
  Verified is near-saturated (~93–95% top); attention moved to SWE-bench Pro and
  harness-controlled slices (mini-swe-agent, OpenHands/CodeAct). Learned
  orchestrators (Sakana **Fugu**) devise scaffolds dynamically.
- **Contamination is quantified and mainstream.** Cursor (June 2026): **63% of
  successful Opus-4.8 SWE-bench-Pro solves *retrieved* the fix** (upstream PR
  lookup or mining bundled `.git`), score drops 87.1→73.0 when sealed. UTBoost:
  345 erroneous "passing" patches, rankings shift for 24.4% of Verified. ~19.8%
  of top "solves" semantically incorrect.
- **Provenance gating exists — but correlational.** CaMeL (capability/taint,
  dataflow, provable-by-construction), Agent-Sentry (learned provenance
  envelopes, allow/ambiguous/block), No-Certificate-No-Execution
  (Proposal–Certification–Execution, policy permissibility, ZK trace certs).
- **Interventional faithfulness exists — but on internals or post-hoc.** Causal
  mediation on CoT (direct vs indirect effects), Counterfactual Simulation
  Training, CausalFlow (post-hoc counterfactual repair of failures), classic
  causal scrubbing / interchange interventions (internals-only).
- **Event-sourced agents exist — as memory, not certification.** Nakajima's
  ActiveGraph ("The Log is the Agent"): log-as-truth, deterministic projection,
  cheap forking, lineage. Regimes: held-out-gated self-improvement loops where
  every promotion is an event.
- **Autoresearch is the fastest-growing harness pattern — and already broke.**
  Karpathy autoresearch, Bilevel Autoresearch, GEAR, EvoTrainer; Shopify's
  overfit speedup is a public wrong-variable failure of the paradigm.

### 2.2 LBAH's unclaimed square

Nobody found gates on an **interventionally verified** claim that the right
variable controlled the commitment. CaMeL/Agent-Sentry answer *could it have
flowed*; LBAH answers *did it actually move the action*. That is:

> **Causal scrubbing at the harness boundary, treating the model as a black box,
> as a pre-commitment gate.**

That framing appears open, and it composes with — rather than competes against —
the correlational systems (they cheaply nominate carriers; LBAH's probe confirms
them).

---

## 3. The roadmap

Five phases, ordered by (value ÷ cost). Each lists rationale, tasks with files,
acceptance criteria, and the obligation it advances.

### Phase 0 — Activate what we built  ·  *closes G1, G3*

The mechanism exists; make it run and make it first-class. Cheapest, highest
credibility gain.

**Tasks**
1. Wire `--gauge-budget` (and `--gauge-min-concern`) into `lbah run/bench/compare`
   (`cli.py`), threaded to `LoadBearingHarness`. Add `gauge_probe_budget` to the
   mode YAMLs (`configs/guarded_mode.yaml`, `audit_mode.yaml`).
2. Promote the gauge verdict to a **first-class certificate field**. Today the
   three-way verdict lives only in `GateResult.evidence`; add
   `gauge_results: list[GateResult]` (or a typed `GaugeVerdict` summary) to
   `LoadBearingCertificate` (`core/schemas.py`) so diagnostics and scoring can
   read it without string-parsing evidence.
3. Fix the telemetry gap (G3): ensure `scorer.score` persists all per-component
   scores on **every** `RunResult` row, and that `core/diagnostics.py` reads
   them. Add a regression test asserting 100% row coverage.
4. Re-run the held-out-proxy eval (`scripts/heldout_proxy_twins.py`) **with the
   gauge probe on**, and report gauge-only catch-rate vs transport-only. This
   separates the two mechanisms' contributions for the first time.

**Acceptance**
- `lbah bench --suite moved_bottleneck --gauge-budget 2` fires the probe (gauge
  gates present in certificates).
- Component scores present on 100% of rows in a fresh run dir.
- A short `docs/results/GAUGE_ABLATION.md`: catch-rate with/without the probe on
  held-out proxies, plus overblocking (false-block) rate on `OracleAgent`.

**Obligation advanced:** gauge-fixing (from dormant to live).

### Phase 1 — Unify the stacks: event-source the coding ledger  ·  *closes G2*

Bring the theory to the side that carries benchmark credibility.

**Tasks**
1. Make `CodingLedger` (`coding/ledger.py`) an append-only projection of a
   coding event log, reusing the `core/events.py` pattern (a `CodingEvent` type
   or a generalization of `ConcernEvent`). Preserve the existing
   `unresolved(threshold)` API as a projection query.
2. Emit a `LoadBearingCertificate` (or a coding-specialized certificate sharing
   the schema) per `finish` in `CodingHarnessRunner` (`coding/runner.py`), so
   `lbah code run` produces certificates comparable to the gate stack.
3. Give `CandidatePatchTournamentRunner` (`coding/tournament.py`) a
   gauge/lineage treatment: it already forks repos — record those forks as
   events and expose per-candidate lineage.

**Acceptance**
- `lbah code run` emits at least one `LoadBearingCertificate` with populated
  transport/gauge fields.
- `lbah replay --lineage` works on a coding run's event log.
- No regression in the Modal smoke suite (`docs/results/SWEBENCH_MODAL_PROBE.md`
  numbers hold).

**Obligation advanced:** all four, extended to real repositories.

### Phase 2 — The flagship: per-action runtime-contamination detection  ·  *the paper*

Reproduce Cursor's aggregate "63% retrieved, not derived" **per action**, using
the gauge-fixing probe as the detector. This is the demonstration that makes
LBAH matter.

**Tasks**
1. Build a controlled SWE-bench-style slice where the fix is reachable via a
   *leak carrier* — injected git history (`git log --all`), an injected "hint"
   field, or a retrieved-doc stub — separate from the issue description.
2. Treat the leak carrier as a concern variable and run the gauge probe:
   perturb the leaked-fix carrier and check whether the winning patch tracks it
   (`invariant` to the issue but *sensitive* to the leak ⇒ retrieved-not-derived,
   flag). Perturb the issue description and check the converse.
3. Calibrate with a surface/semantic perturbation-operator set (presentation
   changes = null set, must not fire; meaning changes = positive set, must
   fire). Report false-positive / false-negative rates.

**Acceptance**
- On the slice, per-instance flag rate tracks whether the solve used the leak
  carrier (target: flag ≥80% of leak-tracking solves; <10% false flags on
  derived solves).
- Probe is invariant to presentation-only perturbations (documented FP rate).
- `docs/results/RUNTIME_CONTAMINATION.md` with the full table.

**Obligation advanced:** gauge-fixing + commitment-effect, on the field's
current hardest failure mode.

### Phase 3 — Self-tuning under certificates (LBAH-gated autoresearch)  ·  *ride the wave*

Autoresearch loops are spreading and have a known integrity hole (Shopify
overfit). Ship the missing integrity layer.

**Tasks**
1. Regimes-style loop (held-out-gated) over LBAH's *own* knobs: gauge budget,
   `gauge_min_concern`, tournament scoring weights, decision thresholds. The
   benchmark suites are the fixed, agent-unedited eval (the `prepare.py`
   analog). **The proxy adversary and scorer stay strictly outside the loop** —
   the Goodhart guard: an autoresearch loop optimizing a metric is exactly where
   wrong-variable optimization bites, and LBAH's whole thesis says the evaluator
   must be untouchable.
2. Every promote/discard is an event in the ledger; promotion requires static +
   in-sample + held-out gates.

**Acceptance**
- The loop improves held-out gauge catch-rate (or load-score calibration `r`,
  currently a modest 0.304) **without** raising the `OracleAgent` false-block
  rate beyond a fixed budget.
- Every tuning decision is replayable from the event log.

**Obligation advanced:** the standard applied reflexively to LBAH itself.

### Phase 4 — Rigor & positioning  ·  *closes G4, G6*

**Tasks**
1. Wire and evaluate at least one LLM-backed module end-to-end
   (`LLMConcernMapper` via a real adapter), and make the modules actually read
   `lbah/prompts/*.txt` (or delete the files). Report concern-mapping quality vs
   the hand-authored metadata baseline — this tests the currently-assumed
   concern obligation.
2. Purge the fabricated arXiv IDs from `SOTA_HARNESS_INTEGRATION.md`; verify
   every citation used anywhere. Add the §0 positioning ("correlation is not
   control") to the README, differentiated against CaMeL / Agent-Sentry /
   No-Certificate-No-Execution.
3. UTBoost-style test hardening: tournament winners must survive augmented
   oracles, not just the original suite, before their certificate stands.

**Acceptance**
- One end-to-end LLM concern-mapping run with reported quality.
- Zero unverifiable citations in `docs/`.
- Tournament certificate records "survived hardened tests."

**Obligation advanced:** concern (tested, not assumed) + commitment-effect
(against strengthened oracles).

---

## 4. What to borrow, beat, position (survey → action)

| Idea | Source (verify ID) | Action |
|---|---|---|
| Interventional > correlational provenance | CaMeL, Agent-Sentry, No-Cert-No-Exec | **[position]** §0 thesis; compose static taint (cheap carrier nomination) + LBAH probe (confirm) — Phase 2 task 2 |
| Runtime contamination is per-action wrong-variable | Cursor June-2026 | **[borrow]** flagship demo — Phase 2 |
| Perturbation-operator taxonomy | surface/semantic noise, AgentNoiseBench | **[borrow]** probe calibration null/positive sets — Phase 2 task 3 |
| Held-out-gated event-logged self-improvement | ActiveGraph / Regimes | **[borrow]** Phase 3 |
| Test augmentation catches false passes | UTBoost | **[beat]** Phase 4 task 3 |
| Certificates = machine-readable harness disclosure | Binding Constraint Thesis | **[position]** README framing |
| Certify the Karpathy Loop | autoresearch / Bilevel / GEAR | **[beat]** Phase 3 framing |
| Direct/indirect effect decomposition | causal mediation on CoT | **[borrow]** future: split transport (indirect) from bypass (direct) in the certificate |
| Tool-use failure taxonomy | ToolFailBench, ToolScan (verify IDs) | **[borrow]** coding-stack validators — §4.1 |
| Read-set load-bearingness | exploration-drift corpus (SUP-4083) | **[borrow]** gauge-probe generalization — §4.1 |

### 4.1 Adjacent corpus (agent exploration / context) — what we take, what we don't

A separate literature review (for the coding-agent exploration ticket
SUP-4083) surveyed ~20 papers on *unpriced exploration*: agents that keep
acquiring context past its marginal value, `AGENTS.md`/README bloat,
localization-before-edit, and exploration-budget steering. Most of it is a
**different axis** from LBAH — *efficiency / behavior-shaping of the
agent-under-test*, not *epistemic gating of arbitrary agents*. LBAH wraps and
gates any agent; it does not dictate how the agent explores. So exploration
budgets, steering hooks, repo cards, AST-preflight, and Agentless-style staged
control are **explicitly out of scope** for LBAH (they belong to the agent, not
the gate). Recording this boundary here to prevent scope creep.

Two items *do* transfer, because they restate LBAH's own obligations in a new
domain:

1. **Tool-use failure taxonomy → coding-stack validators.** ToolFailBench /
   ToolScan categories (*ignored tool result*, *fabricated output*,
   *unnecessary tool use*, *wrong args / invalid format*) are not a new axis —
   in LBAH's language they are transport and proxy failures: committing while
   ignoring a tool result is transport loss (the result was a concern carrier
   that did not survive); a fabricated output is a proxy. Fold these as named
   validators into the coding stack (Phase 1) alongside the existing
   `validators/tool_validators.py`, so coding certificates carry
   literature-backed tool-failure gates rather than ad hoc checks.

2. **"Read-set load-bearingness" — the one genuine conceptual bridge.** The
   gauge probe generalizes from a single concern variable to the agent's whole
   *read set*: of the N files/results the agent explored, which ones actually
   moved the commitment? Perturb each read result and diff the patch. This
   reframes "exploration drift" as a load-bearing question — unpriced
   exploration is context that was *available but not load-bearing*, which is
   exactly the availability-vs-use distinction the standard is built on. Adjacent
   to the core, but distinctive: a candidate Phase 2+ capability once the coding
   stack emits certificates.

---

## 5. Risks & non-goals

- **Probe cost / DoS.** The gauge probe re-invokes the agent per high-concern
  variable. Keep it budgeted (`gauge_probe_budget`), and use cheap static
  carrier nomination (CaMeL-style) before spending inference. Guardrails are an
  attack surface; probe-cost DoS is a real threat to bound.
- **Replay trust.** The probe is only as trustworthy as replay determinism.
  Adopt the clock/nondeterminism interception checklist (intercept `Date.now`,
  record all tool/LLM I/O) before claiming reproducibility. `core/events.py`
  already excludes wall-clock from the projection — extend that discipline to
  the coding stack.
- **Citation integrity (G6).** Repeated here because the repo already shipped
  fabricated IDs once. No external claim ships an unverified citation.
- **Non-goal:** beating the SWE-bench Verified top score. LBAH's contribution is
  *epistemic gating / auditability*, an orthogonal axis to raw solve-rate. The
  win condition is "certified, contamination-resistant solves," not a higher
  number on a saturated, partly-gamed leaderboard.

---

## 6. Immediate next step

Phase 0, task 1+2: wire `--gauge-budget` through the CLI and promote the verdict
to a certificate field. Small, unblocks the gauge ablation that turns "we built
a probe" into "the probe catches proxies the transport gate misses." Everything
downstream depends on the probe actually running.
