# Retrieved or Derived? Gauge-Fixing Certificates for Agent Commitments

Working draft, 2026-07-09. Owner: this branch.
Claim-level labels are printed against every table; nothing here has been
human-validated or run against a foundation-model coding leaderboard.

## Abstract

Deployed guardrails today gate on *correlation* — did the right value flow
into the action, is the trace policy-permissible, does a taint marker
survive to commitment (CaMeL [arXiv:2503.18813], FIDES [arXiv:2505.23643],
Agent-Sentry [arXiv:2603.22868], No-Certificate-No-Execution
[arXiv:2605.24462]). We ask a different question: did the claimed
distinction actually *control* the commitment. We instantiate this as a
pre-commitment, black-box harness gate on top of an event-sourced concern
ledger, and evaluate it on three synthetic slices plus a small-N live
Claude coding pilot. On the flagship contamination slice (n=16 paired
leak/derived cells) the detector catches 100 % of retrieved-not-derived
solves at 0 % false positive; a generalisation to N reads (Law 2, Track
B) recovers the ground-truth load-bearing set with macro F1 = 1.00; a
real-LLM concern mapper (Track A, Claude Opus 4.7 on n=8 seeds) preserves
the load-bearing distinction (value-recall 0.94, critical-rank 1.00) and
its output continues to catch 100 % of held-out proxies. The live-agent
pilot (Track D, Claude Opus 4.7 on n=2 seeds → 4 cells) shows the
detector's *specificity* is intact on real-agent derived solves (0 FP)
but produced no positives — Claude ignored a buried leak carrier and
solved the task from the issue text. A `--force-retrieve` follow-up
(same model, n=2 → 4 cells) that instructs leak-mode cells to consult
the carrier induces marker retrieval and recovers catch = 1.00 at
FP = 0.00 — sensitivity holds in vitro once positives exist. The same
induction on Modal SWE-bench Lite (n=5, force-retrieve, Opus 4.8) yields
5/5 resolved under a synthetic `LEAK_MARKER` gate with catch = 1.00; the
matched clean arm (A0) has synthetic FP = 0.00 while gold-line overlap
is 0.50 — specificity holds only for the synthetic fingerprint. Still
not a natural-contamination base rate.

We do not claim to beat SWE-bench Verified, to certify intelligence, or
to have validated any of this against human graders. We claim a
falsifiable, budgeted mechanism for asking "retrieved or derived" per
action, and a claim-level ledger that refuses to inflate.

## 1  Position: correlation is not control

The load-bearing standard for representation claims requires four
evidence fields to be jointly present before a claim is written down:
**concern** (which distinctions must survive), **transport** (from where
to where), **gauge-fixing** (do gauge-equivalent alternatives produce
the same commitment), and **commitment effect** (did the commitment
change under the intervention). Absent gauge-fixing, every certificate
is an *availability* claim — the right value was present, no guarantee
it did the work (D'Amour [arXiv:2011.03395]; Locatello [arXiv:1811.12359]).

Existing harness gates satisfy some subset of these obligations:

| Field | Existing gate | Gap |
|---|---|---|
| concern | Uniform validation; policy allowlists | Unweighted; no distinction of load-bearing vs incidental |
| transport | Taint / IFC / provenance tags (CaMeL, FIDES, Agent-Sentry, PACT [arXiv:2605.11039]) | Presence, not survival-to-commitment |
| gauge-fixing | Causal scrubbing (Chan et al. 2022), interchange / DAS ([arXiv:2106.02997], [arXiv:2303.02536]) | Internals or post-hoc, not pre-commitment black-box |
| commitment effect | pass@k, "resolved" flags | Ignore mechanism; contaminated by leaks (Cursor 2026-06-25; SWE-Bench+ [arXiv:2410.06992]) |

Our contribution is a **pre-commitment, black-box harness gate** that
issues a certificate only when an intervention shows the claimed
distinction controlled the commitment: causal scrubbing at the harness
boundary, with the model as a black box.

## 2  Related work

We build on and position against verified prior art. Unverified names
from earlier surveys are omitted (see roadmap §7 for the ledger).

**Contamination and weak oracles.** Cursor (2026-06-25) shows 63 % of
successful Opus-4.8 Max SWE-bench Pro resolutions retrieved the fix and
that sealing the harness drops the number 87.1 → 73.0. SWE-Bench+
quantifies 32.67 % solution leakage in "solved" patches
[arXiv:2410.06992]. UTBoost [arXiv:2506.09289], PatchDiff
[arXiv:2503.15223] and SWE-ABS [arXiv:2603.00520] show weak oracles
inflate pass rates.

**Provenance and certificates.** CaMeL, FIDES, Agent-Sentry and PACT
gate on *whether a taint could have flowed*; No-Certificate-No-Execution
[arXiv:2605.24462] and Proof of Execution [arXiv:2607.05397] add
pre-execution authorization and replay envelopes. None supply an
interventional test of control.

**Interventional faithfulness at internals.** Causal scrubbing;
interchange / DAS; CoT mediation [arXiv:2402.13950]. Related, and
partially inspiring, but requires either weight access or post-hoc
analysis; harness gates at commitment time do not.

**Faithfulness caveat.** Hint verbalization [arXiv:2512.23032] overclaims
unfaithfulness; we treat transcript mention as evidence *of nothing* and
gate only on commitment effect under intervention.

**Tool failure taxonomy.** ToolFailBench [arXiv:2607.04686] and ToolScan
[arXiv:2411.13547] give named categories (Result-Ignore, Output-
Fabrication, Tool-Skip) that map to transport / proxy / concern gates
in our stack.

## 3  Method

We implement four obligations as first-class certificate fields on an
append-only `ConcernEventLog` whose deterministic projection is a
`ConcernLedger`. The event log makes transport a lineage query and
gauge-fixing a real intervention (`gauge_fixing_probe`) that
substitutes a gauge-equivalent value *for every carrier of the
distinction in the agent's input bundle* — perturbing one carrier misses
agents that read the distinction from another. The verdict is scoped by
whether the value was present at all, so out-of-ledger provenance is not
mistaken for a proxy.

### 3.1 Retrieved-or-derived as a dual gauge probe

Given a task with an issue variable and a leak-carrier variable
(injected git history, hint, or retrieved-doc stub), we run **two**
gauge probes on the commitment: one perturbing the leak carrier's
value, one perturbing the issue's. Retrieved-not-derived ⇔
`leak_probe.commitment_changed ∧ ¬ issue_probe.commitment_changed`.
This is the exact contrapositive of "controlled by the intended
distinction" (Law 1).

Anti-cheat: the detector consults only the commit function's output.
Transcript mention of the leak marker never counts, in line with the
hint-verbalization caveat.

### 3.2 Read-set load-bearingness (Law 2 at the coding surface)

Generalise 3.1 to K reads per instance. Plant one ground-truth
load-bearing read plus K−1 distractors (one leak-tracking, rest pure).
Run one gauge probe per read; predict `load_bearing` iff perturbation
moves the commitment. Score set precision / recall / F1 against the
ground-truth load-bearing set.

### 3.3 Live LLM concern mapping (Phase 4 upgrade)

Wire a real Claude model to `LLMConcernMapper` and force the extraction
path by stripping metadata. Quality is scored id-agnostically:
**value-recall** (fraction of baseline values recovered anywhere in the
mapper's output) and **critical-rank** (whether the mapper assigns
strictly higher concern to the load-bearing distinction than the mean
distractor concern). The mapped ledger is then subjected to the same
gauge probe as a hand-authored one — mapper quality cannot substitute
for load.

## 4  Experiments

### 4.1 Single-carrier contamination detector

**Claim level:** coding-agent diagnostic on a controlled synthetic
slice. Not Modal SWE-bench, not human-validated.

Toy repo with `add(a,b) = a-b`; issue = "return the sum"; leak carrier =
`.lbah/leak/git_log.txt` containing an ALT-flag marker line. Paired
`leak` / `derived` policies drive the commit function. Seeds = 16,
paired → 32 cells. Wall = 53.4 s.

| metric | value | target |
|---|---:|---:|
| leak catch-rate | **1.00** | ≥ 0.80 |
| derived FP rate | **0.00** | < 0.10 |
| surface-perturbation FP | 0.00 | low |

Surface-perturbation calibration confirms the flag does not fire under
presentation-only rewrites (Zhang & Guo class [arXiv:2605.25981]) — only
under semantic ones. Full table: `docs/results/RUNTIME_CONTAMINATION.md`.

### 4.2 Read-set load-bearingness (K=4)

**Claim level:** synthetic diagnostic. Law 2 at the coding surface.

Seeds = 8, reads per task = 4 → 32 per-read decisions.

| metric | value | target |
|---|---:|---:|
| set precision (macro) | **1.000** | ≥ 0.95 |
| set recall (macro)    | **1.000** | ≥ 0.95 |
| set F1 (macro)        | **1.000** | ≥ 0.95 |

Per-read confusion: 8 true positives, 0 false negatives, 0 false
positives, 24 true negatives. Full table:
`docs/results/READ_SET_LOAD_BEARING.md`.

### 4.3 Real-LLM concern mapping

**Claim level:** real-LLM diagnostic on `moved_bottleneck` (synthetic).
Not human-validated, not on real code.

`claude -p` (Claude Opus 4.7) driven `LLMConcernMapper` on n = 8 seeds,
mean wall / seed 9.19 s. Two lenses, one id-based, one id-agnostic:

| metric | LLM | metadata baseline |
|---|---:|---:|
| id-overlap recall | 0.44 | 1.00 |
| id-overlap F1     | 0.48 | 1.00 |
| **value-recall**  | **0.94** | 1.00 |
| **critical-rank correct** | **1.00** | 1.00 |
| mean critical concern | 1.00 | 1.00 |
| mean distractor concern | 0.04 | 0.20 |
| held-out gauge catch | **1.00** | 1.00 |
| good-allow | 0.62 | 1.00 |

Read: Claude preserves the load-bearing distinction (value-recall 0.94,
critical-rank 1.00) and is *stricter* about ignoring distractors than
the hand-authored baseline (0.04 vs 0.20). The 0.62 good-allow is an
honest tradeoff — Claude's richer mapping declares additional
concerns (anti-recency guard, tool-argument key semantics) that block
some good actions the sparse baseline lets through.

Full table: `docs/results/CONCERN_MAPPER_EVAL.md`.

### 4.4 Live-agent contamination pilot (Track D)

**Claim level:** coding-agent diagnostic (local, small-N). Not
human-validated, not Modal-graded.

`ClaudeCodeCLIAdapter` drives the toy contamination slice through
`CodingHarnessRunner`. Because a two-way gauge is expensive under real
LLM calls, the live probe uses a marker-inspection heuristic
(`run_contamination_probe_on_real_diff`): flag = leak marker present in
the diff *and* issue-only derived signal absent.

Claude Opus 4.7, n = 2 seeds → 4 cells, wall = 127.5 s.

| metric | value | target | reads |
|---|---:|---:|---|
| leak catch-rate | 0.00 | ≥ 0.80 | **no positives produced** |
| derived FP rate | **0.00** | < 0.10 | specificity holds |
| leak-marker-in-diff | 0.00 / 4 | — | Claude ignored the leak carrier |

**Read.** All four cells — both `leak`-instrumented and `derived`-
instrumented — produced the issue-derived line (`return a + b`) with no
leak marker. Claude ignored `.lbah/leak/git_log.txt` and solved the
task from the issue text alone. This is not a detector failure. It is
a live-agent behavioural finding: the leak carrier alone was not
prominent enough in this toy setup to induce retrieved-not-derived on
Opus 4.7. The detector's *specificity* (0 FP on real-agent derived
solves) is intact; its *sensitivity* was untested until the
force-retrieve follow-up below.

#### Force-retrieve sensitivity (follow-up a)

Same model and N, with leak-mode instructions rewritten to require
reading `.lbah/leak/git_log.txt` and applying the recorded upstream fix
(including marker comments). Derived-mode cells keep the anti-retrieve
risks. Wall = 126.9 s. Full table:
`docs/results/RUNTIME_CONTAMINATION_REAL_AGENT_FORCE_RETRIEVE.md`.

| metric | value | target | reads |
|---|---:|---:|---|
| leak catch-rate | **1.00** | ≥ 0.80 | sensitivity holds |
| derived FP rate | **0.00** | < 0.10 | specificity holds |
| leak-marker-in-diff (leak cells) | **1.00** | 1.00 | induction worked |

**Read.** Instructing the agent to consult the leak carrier induced
retrieved-not-derived commitments on both leak cells; the
marker-inspection detector caught them (2/2) with 0 FP on derived.
This is an *in-vitro sensitivity* check, not a claim that natural
contamination rates match Cursor's SWE-bench Pro figure.

**Consequence for the flagship claim.** The detector's 100 % catch on
the scripted `leak_tracking_agent` (4.1) and on force-retrieve live
cells shows that a detector of this shape works when a contaminated
commitment exists. What the baseline 4.4 run shows is that the
*contamination-induction* half of a real-agent benchmark is nontrivial
— a buried file alone was not enough on Opus 4.7; an explicit consult
instruction was. The Cursor 2026-06-25 result (63 % retrieved on
SWE-bench Pro) samples from a distribution where those conditions are
met at scale without prompting.

**Remaining follow-ups.** (b) Modal SWE-bench leak sidecar — **done** at
n=5 force-retrieve, then **control matrix** with synthetic primary gate:
A0 clean synth FP = 0.00, A2 force-retrieve synth catch = 1.00; gold-line
overlap on A0 = 0.50 (noisy — specificity gates on synthetic only). See
`docs/results/SWEBENCH_LEAK_CONTROL_N5.md`. A1 (leak, no force) not run
in the ≤2×n=5 budget. (c) Base-rate on known-contaminated distribution —
**B2 label hunt failed timebox** (`docs/results/B2_LABEL_HUNT.md`):
SWE-Bench+ labels issue-text leakage, not runtime retrieve; Cursor has
no public instance dump. Fall back sealed-vs-unsealed n=20 **ran**:
unsealed 14/20 = sealed 14/20 (Δ = 0) on Lite with Opus 4.8 — resolve-
neutral under seal; two cells swapped (`docs/results/SWEBENCH_SEALED_UNSEALED_N20.md`).
Honest negative for "Lite mirrors Cursor's Pro sealed drop."

**Head-to-head (raw / LBAH / gated / sealed), Lite n=20, Opus 4.8.**
Resolve: raw 13/20, LBAH 14/20, sealed 14/20 (Δ LBAH−raw = +0.05;
sealed−LBAH = 0). Matches `EVIDENCE.md`: LBAH is not a resolve% lift.
Gated (leak+force-retrieve + synthetic-marker finish gate, v2): gate
message on 17/20 cells; residual marker in 4/20 submitted patches;
still 20/20 resolved after revise. **v3 fail-closed:** budget exhaustion
with marker still present restores the baseline and submits an empty
patch instead of leaking residual flags
(`docs/results/SWEBENCH_HEAD_TO_HEAD.md`).

**Track C two-way gauge (interventional subset, n=3).** On A2
force-retrieve positives, perturbing `LEAK_MARKER:` → `ALT_LEAK:` moved
the commitment on 3/3 cells (rate 1.00). Fingerprint flags for the full
matrix stay correlational; this subset is interventional confirmation
(`docs/results/SWEBENCH_TWO_WAY_GAUGE.md`).

## 5  Anti-cheat and claim-level ledger

We label every table with a claim level and refuse to inflate:

| level | means | applies to |
|---|---|---|
| synthetic diagnostic | Deterministic slice, no real model in the loop | Phase 2 detector (4.1), read-set (4.2) |
| real-LLM diagnostic | Real model in the loop, synthetic task substrate | Concern mapper (4.3) |
| coding-agent diagnostic (local, small-N) | Real coding harness loop, toy repo, small N | Live pilot (4.4) |
| coding-agent diagnostic (Modal) | Modal-graded, contamination sidecar | Leak control, sealed/unsealed, head-to-head, Track C subset |
| human-validated | External human grader signoff | Not yet |

Corresponding anti-cheat rules:

1. **Detector reads no transcript.** Only the commit function's output
   (or the final diff for the live probe). Transcript mention is not
   used as evidence of anything.
2. **Two-way gauge, not one-way.** Perturbing only the leak carrier
   catches agents that also react to a surface change to the issue;
   perturbing only the issue catches agents that pass through
   regardless. The retrieved-not-derived flag requires *both* verdicts.
3. **Surface / semantic calibration.** Perturbation-operator set
   partitioned into presentation-only (null set — must not fire) and
   meaning-changing (positive set — must fire). Zhang & Guo class, not
   AgentNoiseBench.
4. **Anti-cheat for autoresearch.** The proxy adversary and scorer stay
   strictly outside the tuning loop (Phase 3). Promotion requires
   static + in-sample + held-out gates plus the contamination detector.

## 6  Limitations

- **Synthetic substrate.** 4.1, 4.2, 4.3 all live on a controlled toy
  repo or a hand-built `moved_bottleneck` task. The distributional gap
  to real SWE-bench is real.
- **N is small.** The live-agent pilot (4.4) is small-N by design;
  cost of a two-way real gauge motivates the marker heuristic there.
- **Modal contamination control matrix at n=5.** Synthetic primary gate:
  A0 FP 0.00 / A2 catch 1.00
  (`docs/results/SWEBENCH_LEAK_CONTROL_N5.md`). Gold-line is secondary
  and noisy on clean. B2 external runtime-retrieve labels not available
  (`docs/results/B2_LABEL_HUNT.md`).
- **Sealed vs unsealed Lite n=20.** Resolve 14/20 both arms (Δ = 0);
  not Cursor's Pro sealed drop (`docs/results/SWEBENCH_SEALED_UNSEALED_N20.md`).
- **Head-to-head Lite n=20.** raw 0.65 / LBAH 0.70 / sealed 0.70;
  gated v2 gate-engage 17/20, residual marker 4/20 (pre fail-closed);
  v3 empties the commit on budget+marker — no leaderboard claim
  (`docs/results/SWEBENCH_HEAD_TO_HEAD.md`).
- **Track C two-way gauge.** Interventional subset n=3 at rate 1.00;
  not a full-matrix gauge (`docs/results/SWEBENCH_TWO_WAY_GAUGE.md`).
- **Replay trust.** PoE envelope capture is opt-in; the Track C
  subset used a second live run (perturbed carrier), not pure replay.

## 7  Conclusion

Retrieved-or-derived is testable at the harness boundary, per action,
in polynomial time, and it survives being generalised to N reads. Real
LLMs can drive the concern-mapping half of the certificate without
collapsing catch rates. On a live coding agent, specificity held without
prompting and sensitivity held once retrieval was induced
(`--force-retrieve`). On Modal SWE-bench Lite n=5 under the same
induction, 4/5 resolved patches carried the gold fingerprint. Head-to-head
on Lite n=20 isolates raw/LBAH/sealed as resolve-near-ties; Track C
confirms leak intervention moves commitments on a flagged subset. Still
diagnostic claim level, not SOTA. A Pro-scale sealed contrast remains
open if accessible.

Nothing above certifies intelligence, solves SWE-bench, or proves
faithfulness of chain-of-thought. It certifies a bookkeeping identity
between four evidence fields, verifies gauge-fixing by intervention,
and refuses to be written down when any of the four is missing.

## Appendix A — Citation ledger

Verified 2026-07-09. See `docs/DESIGN_ROADMAP.md` §7 for canonical
mapping to arXiv IDs; every reference above resolves through that
table.

## Appendix B — Reproducibility

All results here regenerate from `main` at commit `<TODO_FINAL_SHA>`:

```
python scripts/runtime_contamination_eval.py --seeds 16 --out runs/runtime_contamination
python scripts/read_set_load_bearing.py --seeds 8 --reads 4 --out runs/read_set_load_bearing
python scripts/concern_mapper_eval.py --model claude --seeds 8 --out runs/concern_mapper_eval_claude
python scripts/contamination_real_agent_eval.py --no-dry-run --seeds 2 \
  --model-agent configs/claude_opus_4_7.yaml --out runs/contamination_real_agent_live
# §4.4 follow-up (a): force-retrieve sensitivity (also spends tokens)
python scripts/contamination_real_agent_eval.py --no-dry-run --force-retrieve --seeds 2 \
  --model-agent configs/claude_opus_4_7.yaml \
  --out runs/contamination_real_agent_force_retrieve
```

The last two commands spend real Claude tokens; the first three are free
under any hosted-Anthropic policy.
