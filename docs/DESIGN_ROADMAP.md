# LBAH Design Roadmap — toward a SOTA harness rooted in the load-bearing standard

Status: research-backed draft, 2026-07-09 (v2). Owner: this branch
(`claude/ai-loops-autonomous-cgwz7g`). Scope: turns the event-sourced ledger +
gauge-fixing probe (merged in #26) into the backbone of a state-of-the-art,
*theory-first* agent harness.

This document is meant to be **followed**. Every phase has concrete files,
tasks, and falsifiable acceptance criteria. It is grounded in (a) a full
repository exploration, (b) the Metaphysics of Intelligence archive (load-bearing
standard, gauge-fixed transport, concern-weighted weakness, July-6 synthesis),
and (c) a verified arXiv / primary-source pass that strengthens, sharpens, or
rejects pieces of the original plan.

---

## 0. The one-sentence thesis

Every deployed guardrail today gates on **correlation** — *is the right value
present / did it plausibly flow into the action* (CaMeL's capabilities
[[arXiv:2503.18813](https://arxiv.org/abs/2503.18813)], Agent-Sentry's
execution-provenance bounds
[[arXiv:2603.22868](https://arxiv.org/abs/2603.22868)], No-Certificate-No-
Execution's policy permissibility
[[arXiv:2605.24462](https://arxiv.org/abs/2605.24462)], FIDES IFC/taint
[[arXiv:2505.23643](https://arxiv.org/abs/2505.23643)]). LBAH's unclaimed
territory is to gate on **control** — *did the right distinction actually move
the commitment, verified by intervention.*

"Generation is not permission" (No-Certificate-No-Execution); LBAH adds
**"correlation is not control."**

That is the load-bearing standard restated as a product position: a
representation / provenance / faithfulness claim is load-bearing only when it
supplies four evidence fields — concern, transport, gauge-fixing, and
commitment effect — and satisfies the bookkeeping inequality that refuses to be
written unless all four are present (*A Load-Bearing Standard for Representation
Claims*; *Gauge-Fixed Concern Transport*).

---

## 0.1 Research verdict on the plan (STORM + regime audit)

### What the literature **supports**

| Plan claim | Verdict | Primary evidence |
|---|---|---|
| Correlation ≠ control; need intervention | **Supports** | Locatello impossibility without inductive bias [[arXiv:1811.12359](https://arxiv.org/abs/1811.12359)]; D'Amour underspecification [[arXiv:2011.03395](https://arxiv.org/abs/2011.03395)]; Geiger causal abstraction / interchange [[arXiv:2106.02997](https://arxiv.org/abs/2106.02997)]; Chan et al. causal scrubbing (2022); own Laws 1–2 |
| Compose static taint + interventional probe | **Supports** | CaMeL / FIDES / PACT nominate carriers cheaply; none measure commitment effect. LBAH is the missing confirm step |
| Runtime contamination is the field's hard failure | **Supports** | Cursor (2026-06-25): 63% of Opus-4.8 Max SWE-bench Pro solves *retrieved* the fix; sealed harness 87.1→73.0. SWE-Bench+ solution leakage 32.67% [[arXiv:2410.06992](https://arxiv.org/abs/2410.06992)] |
| Test augmentation catches false passes | **Supports** | UTBoost: 345 erroneous "passed" patches; rankings shift for 24.4% of Verified [[arXiv:2506.09289](https://arxiv.org/abs/2506.09289)]. PatchDiff: 29.6% plausible patches behaviorally diverge [[arXiv:2503.15223](https://arxiv.org/abs/2503.15223)]. SWE-ABS adversarial strengthening [[arXiv:2603.00520](https://arxiv.org/abs/2603.00520)] |
| Certificates as pre-execution authorization | **Supports** | No-Certificate-No-Execution PCE architecture [[arXiv:2605.24462](https://arxiv.org/abs/2605.24462)]; Proof-of-Execution replay envelopes [[arXiv:2607.05397](https://arxiv.org/abs/2607.05397)] |
| Tool-failure taxonomy → transport/proxy validators | **Supports** | ToolFailBench [[arXiv:2607.04686](https://arxiv.org/abs/2607.04686)] (Result-Ignore / Output-Fabrication); ToolScan [[arXiv:2411.13547](https://arxiv.org/abs/2411.13547)] |
| Keep scorer outside autoresearch (Goodhart) | **Supports** | Goodhart; own synthesis eval rule; UTBoost/Cursor show optimizing the surface metric is exactly the failure mode |
| Phase 0 first (activate dormant gauge) | **Supports** | Own standard: without a live gauge-fixing intervention, every certificate is an *availability* claim. Dormant probe = missing obligation 3 |

### What the literature **sharpens** (keep the idea, tighten the claim)

| Plan claim | Sharpening |
|---|---|
| "Nobody gates on interventional control" | True for **black-box, pre-commitment harness gates**. False as a blanket: causal scrubbing / interchange / CoT mediation already do interventional tests on *internals* or *post-hoc*. Position as: *causal scrubbing at the harness boundary, model as black box, as a pre-commitment gate* — not "first interventional method ever" |
| CoT faithfulness as motivation | Paul et al. mediation [[arXiv:2402.13950](https://arxiv.org/abs/2402.13950)] supports intervening on reasoning. But hint-verbalization metrics overclaim unfaithfulness [[arXiv:2512.23032](https://arxiv.org/abs/2512.23032)]. **Do not** treat "did the transcript mention the leak" as the detector; treat **commitment effect under gauge perturbation** as the detector (exactly Law 1 + §6 of the load-bearing standard) |
| AgentNoiseBench as surface/semantic null set | **Wrong citation.** AgentNoiseBench [[arXiv:2602.11348](https://arxiv.org/abs/2602.11348)] is user/tool noise robustness. Surface-vs-semantic perturbation evidence is better cited as Zhang & Guo [[arXiv:2605.25981](https://arxiv.org/abs/2605.25981)] (+19.7 pp inconsistency gap). Use that paper (or a hand-built operator set) for Phase 2 calibration |
| "Binding Constraint Thesis" / Fugu / ActiveGraph / Regimes / Shopify overfit | Demote to **unverified namedrop** until primary sources are attached. Keep the *ideas* (harness variance, event-logged promotion, held-out gates, wrong-variable optimization) with verified substitutes: D'Amour, Goodhart, No-Cert-No-Exec, PoE, Cursor, UTBoost |
| Measured +25% proxy-resistance gap | Keep as **harness-internal evidence**, claim level = synthetic / controlled suite — not yet a coding-agent or foundation-model result (own claim boundary in Gauge-Fixed Transport + July-6 synthesis) |

### What the literature **pressures or partially disproves**

| Plan claim | Pressure |
|---|---|
| Phase 3 (LBAH-gated autoresearch) as near-term flagship | **Deprioritize relative to Phase 2.** Autoresearch integrity is real (Goodhart), but the field's acute, quantified failure is runtime contamination + weak oracles. Autoresearch without a working contamination detector optimizes the wrong certificate. Phase 3 stays, but *after* Phase 2 produces a detector the loop can gate on |
| Read-set load-bearingness as Phase 2+ | **Keep, but rename as Law-2 application.** Sweeping N reads with interventions is the moved-bottleneck law at the coding surface — not a new axis. Budget it; do not let it expand Phase 2 before the single-leak-carrier demo works |
| LLMConcernMapper end-to-end (Phase 4) | Theory says concern is an obligation, not optional — but Locatello + underspecification warn that an LLM-mapped concern without gauge/commitment tests is another availability claim. Wire it, then **immediately** subject mapped concerns to the same probe; do not treat mapper quality as a substitute for load |

### Regime audit (old → new)

- **Old regime:** correlational provenance / policy certificates / transcript audits; synthetic LBAH suites with transport auditor as headline evidence; gauge probe built but budget=0.
- **Transition claimed by this roadmap:** black-box interventional gauge-fixing as a *certificate field* on real coding commitments.
- **Allowed claim now:** scaffold + synthetic diagnostic (moved_bottleneck gap; Modal L4 five-gate suite in the papers).
- **Allowed claim after Phase 2 acceptance:** generated-text / coding-agent diagnostic of retrieved-vs-derived on a controlled leak slice — still not human-validated or neural-validated.
- **Rejected overclaim:** "LBAH certifies intelligence / solves SWE-bench / proves faithfulness of CoT."

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
Claim level: **synthetic diagnostic**, consistent with Law 1 / Demo A–B in the
load-bearing standard paper — not yet a coding-agent result.

### 1.3 The honest critique — six gaps

**G1 — The gauge probe is dormant in every real run.** `gauge_probe_budget`
defaults to `0` (`core/runner.py`) and *nothing in the CLI ever sets it > 0*
(only the unit tests do). So `lbah run/bench/compare` build the event log and
all the gauge machinery, then never fire the probe. Every headline number in
`docs/EVIDENCE.md` (e.g. "held-out proxy 5/5 caught") comes from the
`transport_auditor`, **not** from the interventional probe. This is the highest
value/lowest cost fix in the repo — and the theory says it is not optional:
without gauge-fixing, certificates are availability claims.

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
write-up. §2 and §7 below replace the unverified survey IDs with checked ones.

---

## 2. Competitive landscape (verified sources)

> Citation rule: every ID below was resolved against arXiv or a primary URL in
> the 2026-07-09 research pass. Unverified names from the prior survey are
> either dropped or marked **[unverified — do not cite]**.

### 2.1 Where the field is

- **Underspecification is the background condition.** Many predictors share IID
  score but encode different inductive biases
  [[arXiv:2011.03395](https://arxiv.org/abs/2011.03395)]. Leaderboards without
  structure gates select arbitrarily among them.
- **Contamination / reward hacking is quantified.** Cursor (2026-06-25): 63% of
  successful Opus-4.8 Max SWE-bench Pro resolutions retrieved the fix (upstream
  lookup 57%, git-history mining 9%); sealed harness drops 87.1→73.0 (Composer
  2.5: 74.7→54.0). SWE-Bench+ earlier found 32.67% solution leakage in "solved"
  patches [[arXiv:2410.06992](https://arxiv.org/abs/2410.06992)].
- **Weak oracles inflate pass rates.** UTBoost [[arXiv:2506.09289](https://arxiv.org/abs/2506.09289)];
  PatchDiff [[arXiv:2503.15223](https://arxiv.org/abs/2503.15223)]; SWE-ABS
  [[arXiv:2603.00520](https://arxiv.org/abs/2603.00520)].
- **Provenance gating exists — correlational / policy.** CaMeL
  [[arXiv:2503.18813](https://arxiv.org/abs/2503.18813)]; FIDES
  [[arXiv:2505.23643](https://arxiv.org/abs/2505.23643)]; Agent-Sentry
  [[arXiv:2603.22868](https://arxiv.org/abs/2603.22868)]; PACT argument-role
  provenance [[arXiv:2605.11039](https://arxiv.org/abs/2605.11039)];
  No-Certificate-No-Execution [[arXiv:2605.24462](https://arxiv.org/abs/2605.24462)].
- **Interventional faithfulness exists — internals or post-hoc.** Causal
  scrubbing (Chan et al. 2022); interchange / DAS
  [[arXiv:2106.02997](https://arxiv.org/abs/2106.02997),
  [arXiv:2303.02536](https://arxiv.org/abs/2303.02536)]; CoT mediation
  [[arXiv:2402.13950](https://arxiv.org/abs/2402.13950)]. None of these are
  pre-commitment black-box harness gates on coding commitments.
- **Replay / attestation is becoming infrastructure.** Proof of Execution
  [[arXiv:2607.05397](https://arxiv.org/abs/2607.05397)] binds authorization,
  effect, history, and replay — directly relevant to probe trustworthiness.

### 2.2 LBAH's unclaimed square (sharpened)

Nobody found a **pre-commitment, black-box harness gate** that issues a
certificate only when an intervention shows the right variable controlled the
commitment. CaMeL/FIDES/Agent-Sentry answer *could it have flowed / is the
trace in-bounds*; No-Certificate-No-Execution answers *is the trace
policy-permissible*; LBAH answers *did the claimed distinction actually move
the action*.

> **Causal scrubbing at the harness boundary, treating the model as a black box,
> as a pre-commitment gate.**

That framing remains open, and it composes with — rather than competes against —
the correlational systems (they cheaply nominate carriers; LBAH's probe confirms
them).

Theory mapping (own papers → product):

| Obligation | Harness object | Field analogue it beats |
|---|---|---|
| Concern | concern density / `gauge_min_concern` | uniform validation; unweighted Bennett |
| Transport | event ledger + transport auditor | taint presence without survival-to-action |
| Gauge-fixing | `gauge_fixing_probe` | decodability / transcript mention / provenance tag |
| Commitment effect | patch/commitment diff under intervention | pass@k / "solved" without mechanism |

---

## 3. The roadmap

Five phases, ordered by (value ÷ cost), with research-driven priority notes.
Each lists rationale, tasks with files, acceptance criteria, and the obligation
it advances.

### Phase 0 — Activate what we built  ·  *closes G1, G3*  ·  **DO FIRST**

The mechanism exists; make it run and make it first-class. Cheapest, highest
credibility gain. Theory: a dormant gauge probe means every shipped certificate
is still an availability claim (Law 1).

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

Bring the theory to the side that carries benchmark credibility. Without this,
Phase 2 cannot emit certificates the field will take seriously (G5).

**Tasks**
1. Make `CodingLedger` (`coding/ledger.py`) an append-only projection of a
   coding event log, reusing the `core/events.py` pattern (a `CodingEvent` type
   or a generalization of `ConcernEvent`). Preserve the existing
   `unresolved(threshold)` API as a projection query. Align with PoE-style
   replay envelopes where cheap: capture tool/LLM I/O needed for probe replay
   [[arXiv:2607.05397](https://arxiv.org/abs/2607.05397)].
2. Emit a `LoadBearingCertificate` (or a coding-specialized certificate sharing
   the schema) per `finish` in `CodingHarnessRunner` (`coding/runner.py`), so
   `lbah code run` produces certificates comparable to the gate stack. Map
   certificate fields onto the four obligations explicitly.
3. Give `CandidatePatchTournamentRunner` (`coding/tournament.py`) a
   gauge/lineage treatment: it already forks repos — record those forks as
   events and expose per-candidate lineage.
4. Fold ToolFailBench / ToolScan categories into coding validators
   (`validators/tool_validators.py`): Result-Ignore → transport loss;
   Output-Fabrication → proxy; Tool-Skip / Unnecessary-Tool-Use → concern /
   over-acquisition signals [[arXiv:2607.04686](https://arxiv.org/abs/2607.04686),
   [arXiv:2411.13547](https://arxiv.org/abs/2411.13547)].

**Acceptance**
- `lbah code run` emits at least one `LoadBearingCertificate` with populated
  transport/gauge fields.
- `lbah replay --lineage` works on a coding run's event log.
- No regression in the Modal smoke suite (`docs/results/SWEBENCH_MODAL_PROBE.md`
  numbers hold).
- Named tool-failure validators appear on coding certificates.

**Obligation advanced:** all four, extended to real repositories.

### Phase 2 — The flagship: per-action runtime-contamination detection  ·  *the paper*

Reproduce Cursor's aggregate "63% retrieved, not derived" **per action**, using
the gauge-fixing probe as the detector. This is the demonstration that makes
LBAH matter — and the literature's strongest external demand signal.

Map the demo onto the seven-step protocol from the load-bearing standard:

1. Commitment surface = winning patch / graded solve.
2. Concern = issue-derived fix distinctions vs leak-carrier distinctions.
3. Transport = issue → reads/tools → patch.
4. Gauge alternatives = "derived from issue" vs "retrieved from leak" (same
   observations possible).
5. Gauge-fixing = perturb leak carrier vs perturb issue text.
6. Commitment effect = does the patch track the perturbation?
7. Report bound = catch-rate, FP rate, overblock rate.

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
   fire). Prefer operators aligned with Zhang & Guo
   [[arXiv:2605.25981](https://arxiv.org/abs/2605.25981)], **not** AgentNoiseBench.
   Report false-positive / false-negative rates.
4. **Anti-cheat:** do not use transcript mention of the leak as a success
   criterion (hint-verbalization critique [[arXiv:2512.23032](https://arxiv.org/abs/2512.23032)]).
   The detector is commitment-effect under intervention only.
5. Optional Phase-2+ (budgeted): read-set load-bearingness — sweep N reads with
   the same probe (Law 2 / moved bottleneck at the coding surface). Only after
   the single-leak-carrier demo hits acceptance.

**Acceptance**
- On the slice, per-instance flag rate tracks whether the solve used the leak
  carrier (target: flag ≥80% of leak-tracking solves; <10% false flags on
  derived solves).
- Probe is invariant to presentation-only perturbations (documented FP rate).
- `docs/results/RUNTIME_CONTAMINATION.md` with the full table and claim level
  labeled `coding-agent diagnostic`.

**Obligation advanced:** gauge-fixing + commitment-effect, on the field's
current hardest failure mode.

### Phase 3 — Self-tuning under certificates (LBAH-gated autoresearch)  ·  *after Phase 2*

Autoresearch loops need an integrity layer (Goodhart). Ship it **once Phase 2
gives a detector worth gating on** — otherwise the loop tunes toward a hollow
certificate.

**Tasks**
1. Held-out-gated loop over LBAH's *own* knobs: gauge budget,
   `gauge_min_concern`, tournament scoring weights, decision thresholds. The
   benchmark suites are the fixed, agent-unedited eval. **The proxy adversary
   and scorer stay strictly outside the loop.**
2. Every promote/discard is an event in the ledger; promotion requires static +
   in-sample + held-out gates, including the Phase-2 contamination detector when
   available.
3. Optimize for held-out gauge catch-rate / load-score calibration **subject to**
   an OracleAgent false-block budget — never for raw solve-rate alone.

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
   the hand-authored metadata baseline — then **run the gauge probe on mapped
   concerns** so mapper quality cannot substitute for load.
2. Purge fabricated arXiv IDs from `SOTA_HARNESS_INTEGRATION.md`; replace with
   the verified set in §7. Add the §0 positioning ("correlation is not control")
   to the README, differentiated against CaMeL / FIDES / Agent-Sentry /
   No-Certificate-No-Execution.
3. UTBoost / PatchDiff / SWE-ABS-style test hardening: tournament winners must
   survive augmented oracles before their certificate stands
   [[arXiv:2506.09289](https://arxiv.org/abs/2506.09289),
   [arXiv:2503.15223](https://arxiv.org/abs/2503.15223),
   [arXiv:2603.00520](https://arxiv.org/abs/2603.00520)].

**Acceptance**
- One end-to-end LLM concern-mapping run with reported quality **and** gauge
  catch-rate on mapped concerns.
- Zero unverifiable citations in `docs/`.
- Tournament certificate records "survived hardened tests."

**Obligation advanced:** concern (tested, not assumed) + commitment-effect
(against strengthened oracles).

---

## 4. What to borrow, beat, position (verified survey → action)

| Idea | Source | Action |
|---|---|---|
| Interventional > correlational provenance | CaMeL [2503.18813], FIDES [2505.23643], Agent-Sentry [2603.22868], No-Cert-No-Exec [2605.24462] | **[position]** §0 thesis; compose static taint (cheap carrier nomination) + LBAH probe (confirm) — Phase 2 |
| Runtime contamination is per-action wrong-variable | Cursor 2026-06-25; SWE-Bench+ [2410.06992] | **[borrow]** flagship demo — Phase 2 |
| Surface vs semantic perturbation calibration | Zhang & Guo [2605.25981] | **[borrow]** probe null/positive sets — Phase 2 task 3 |
| Test augmentation catches false passes | UTBoost [2506.09289], PatchDiff [2503.15223], SWE-ABS [2603.00520] | **[beat]** Phase 4 task 3 |
| Certificates = pre-execution authorization | No-Cert-No-Exec [2605.24462]; PoE [2607.05397] | **[position]** README; Phase 1 certificate schema |
| Causal scrubbing / interchange (internals) | Chan et al. 2022; Geiger [2106.02997] | **[position]** LBAH = same idea at harness boundary |
| CoT mediation + verbalization caveat | Paul et al. [2402.13950]; [2512.23032] | **[borrow/sharpen]** intervene on carriers; never use mention-as-faithfulness |
| Tool-use failure taxonomy | ToolFailBench [2607.04686], ToolScan [2411.13547] | **[borrow]** coding-stack validators — Phase 1 task 4 |
| Underspecification / gauge necessity | D'Amour [2011.03395]; Locatello [1811.12359] | **[position]** why certificates need all four obligations |
| Read-set load-bearingness | own Law 2; SUP-4083 bridge | **[borrow]** Phase 2+ after single-carrier demo |
| AgentNoiseBench as surface/semantic taxonomy | — | **[reject citation]** wrong paper; do not use for Phase 2 calibration |
| Binding Constraint / Fugu / ActiveGraph / Shopify | — | **[demote]** unverified names; keep ideas via verified substitutes |

### 4.1 Adjacent corpus (agent exploration / context) — what we take, what we don't

A separate literature review (coding-agent exploration ticket SUP-4083) surveyed
~20 papers on *unpriced exploration*. Most of it is a **different axis** from
LBAH — *efficiency / behavior-shaping of the agent-under-test*, not *epistemic
gating of arbitrary agents*. Exploration budgets, steering hooks, repo cards,
AST-preflight, and Agentless-style staged control remain **explicitly out of
scope**.

Two items still transfer:

1. **Tool-use failure taxonomy → coding-stack validators** (now with verified
   IDs above) — Phase 1 task 4.
2. **Read-set load-bearingness** — Law 2 at the coding surface; Phase 2+ only.

---

## 5. Risks & non-goals

- **Probe cost / DoS.** The gauge probe re-invokes the agent per high-concern
  variable. Keep it budgeted (`gauge_probe_budget`), and use cheap static
  carrier nomination (CaMeL/FIDES-style) before spending inference.
- **Replay trust.** The probe is only as trustworthy as replay determinism.
  Adopt PoE-style capture of tool/LLM I/O before claiming reproducibility
  [[arXiv:2607.05397](https://arxiv.org/abs/2607.05397)].
- **Citation integrity (G6).** No external claim ships an unverified citation.
- **Claim-level inflation.** Synthetic suite wins ≠ coding-agent diagnostics ≠
  human/neural validation. Label every result table with its claim level.
- **Non-goal:** beating the SWE-bench Verified top score. LBAH's contribution is
  *epistemic gating / auditability*. Win condition: certified,
  contamination-resistant solves — not a higher number on a saturated,
  partly-gamed leaderboard (Cursor; UTBoost).

---

## 6. Immediate next step

Phase 0, task 1+2: wire `--gauge-budget` through the CLI and promote the verdict
to a certificate field. Small, unblocks the gauge ablation that turns "we built
a probe" into "the probe catches proxies the transport gate misses." Everything
downstream — especially the Phase 2 contamination paper — depends on the probe
actually running.

---

## 7. Verified citation ledger (2026-07-09 research pass)

Use these; do not reintroduce unverified IDs.

| Topic | Citation |
|---|---|
| CaMeL | Debenedetti et al., arXiv:2503.18813 |
| FIDES / IFC | Costa et al., arXiv:2505.23643 |
| Agent-Sentry | Sequeira et al., arXiv:2603.22868 |
| No-Certificate-No-Execution | Liu et al., arXiv:2605.24462 |
| PACT argument provenance | arXiv:2605.11039 |
| Proof of Execution | arXiv:2607.05397 |
| UTBoost | Yu et al., arXiv:2506.09289 |
| PatchDiff / plausible patches | arXiv:2503.15223 |
| SWE-ABS | Yu et al., arXiv:2603.00520 |
| SWE-Bench+ leakage | Aleithan et al., arXiv:2410.06992 |
| Cursor runtime contamination | https://cursor.com/blog/reward-hacking-coding-benchmarks (2026-06-25) |
| Causal abstraction | Geiger et al., arXiv:2106.02997 |
| DAS / distributed interchange | Geiger et al., arXiv:2303.02536 |
| Causal scrubbing | Chan, Garriga-Alonso, Goldowsky-Dill et al., 2022 (AF) |
| CoT mediation | Paul et al., arXiv:2402.13950 |
| Hint-verbalization caveat | arXiv:2512.23032 |
| Surface vs semantic noise | Zhang & Guo, arXiv:2605.25981 |
| AgentNoiseBench (tool/user noise; *not* Phase-2 calib) | arXiv:2602.11348 |
| ToolFailBench | arXiv:2607.04686 |
| ToolScan | arXiv:2411.13547 |
| Underspecification | D'Amour et al., arXiv:2011.03395 |
| Disentanglement impossibility | Locatello et al., arXiv:1811.12359 |
| Own theory stack | *A Load-Bearing Standard…*; *Gauge-Fixed Concern Transport* (2026-07-07); *Concern-Weighted Weakness* (2026-07-07); *What Matters Becomes Measurable* (2026-07-06) |
