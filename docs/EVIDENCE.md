# Evidence for and against LBAH

Every experiment ran on the same model — Claude Opus 4.7 via `claude -p` — so
any difference is due to prompt structure or runtime gating, not model swaps.
Raw numbers, per-suite breakdowns, and counter-evidence are all here.
Reproduction scripts live under `scripts/` and full JSONL results under `runs/`.

**Bottom line, one paragraph.** On our own synthetic tool-use suites at
n=110/seed, a well-engineered raw prompt (schema + FIELDS_TO_PRESERVE +
FORBIDDEN_VALUES) essentially matches the full harness (both ~99% success).
The harness's runtime gates buy little over a matched prompt on these tasks.
Where the harness *does* buy something is overblocking discipline (0.9% on
non-stale surfaces after tightening), catching held-out proxy shapes it was
not told about (0/5 → 5/5 after the transport-auditor fix), and directional
lift on a small SWE-bench-Lite sample where the concern ledger pins the
target file and symbol. n is small everywhere; do not read this as a
leaderboard win over SOTA.

---

## 1. Matched-prompt ablation (n = 220 per arm)

**Question**: is the harness's win over raw Claude explained by prompt
engineering alone?

**Setup**: same model (`claude-opus-4-7`), same seeds, `tool_constraints` and
`moved_bottleneck`. Three arms:

| Arm | Prompt | Gates |
|-----|--------|-------|
| raw | natural language instruction only | none |
| raw+schema | instruction + JSON schema + FIELDS_TO_PRESERVE + FORBIDDEN_VALUES | none |
| harness | full LBAH ledger + runner | transport, proxy, reopen, verifier |

**Results:**

| arm | n | success | wall_avg | errors |
|-----|---|---------|----------|--------|
| raw | 220 | 0.43 | 5.6s | 3 |
| raw+schema | 220 | **0.99** | 8.1s | 0 |
| harness (strict-transport) | 220 | **0.99** | 11.9s | 0 |

**Per-suite:**

| suite | arm | n | success |
|-------|-----|---|---------|
| moved_bottleneck | raw | 110 | 0.85 |
| moved_bottleneck | raw+schema | 110 | 0.99 |
| moved_bottleneck | harness (strict-transport) | 110 | 0.97 |
| tool_constraints | raw | 110 | 0.00 |
| tool_constraints | raw+schema | 110 | 1.00 |
| tool_constraints | harness | 110 | 1.00 |

**Read.** On these tasks the runtime gates add ≈ 0 over a matched prompt.
Raw fails on tool_constraints (0%) because Claude drifts on field names
("day" vs "date"), converts weekdays to ISO dates, adds spurious fields
(title). Adding an explicit schema + field pin brings it to 100%. The
runtime gates would only add value on failure modes a well-structured prompt
does not already cover — which on THIS suite is zero.

Where LBAH's runtime discipline earns its keep on the same task family:
- when a task author does NOT hand-write a rich schema prompt but instead
  points at the ledger,
- when tasks have stale variables that need forced rechecks,
- when concern shifts mid-episode (moved bottleneck across multiple steps).

---

## 2. Overblocking (n = 440 oracle actions, after transport-auditor fix)

**Question**: does the harness block correct actions? Full JSONL in
`runs/overblocking_v4/`.

| Suite | first-step decisions | success | overblock |
|-------|----------------------|---------|-----------|
| moved_bottleneck | allow=107, revise=3 | 0.97 | 2.7% |
| tool_constraints | allow=110 | 1.00 | 0% |
| stale_confidence | reopen=110 | 1.00 | 0%* |
| retrieval_faithfulness | allow=110 | 1.00 | 0% |

\* The 110 reopens in stale_confidence are the reopenability governor
correctly catching an oracle that wrote a stale value.

**Non-stale overblocking rate: 3/330 = 0.9%.**

---

## 3. Held-out proxy twins (n = 732)

**Question**: does the harness catch proxy shapes we did NOT declare in the
ledger?

**Before the transport-auditor fix**:

| variant | allowed | verdict |
|---------|---------|---------|
| attendee_fullname | 1.00 | LEAK |
| date_iso | 1.00 | LEAK |
| status_case | 1.00 | LEAK |
| slot_whitespace | 0.97 | LEAK |
| slot_substring | 0.00 | caught |

**After the fix** (strict raw leaf equality; `match_mode="substring"` opt-in
for thematic markers; revise threshold on concern ≥ 0.7):

| variant | n | allowed | final_ok | verdict |
|---------|---|---------|----------|---------|
| good (control) | 220 | **0.99** | 0.99 | healthy |
| attendee_fullname | 110 | 0.00 | 0.00 | **CAUGHT** |
| date_iso | 110 | 0.00 | 0.00 | **CAUGHT** |
| status_case | 110 | 0.00 | 0.00 | **CAUGHT** |
| slot_whitespace | 110 | 0.00 | 0.00 | **CAUGHT** |
| slot_substring | 72 | 0.00 | 0.00 | **CAUGHT** |

**Result: 5/5 held-out proxy shapes caught, 0.99 control-arm pass rate.**

The fix (see `lbah/modules/transport_auditor.py`): switched from
"lowercased substring OR leaf" to "raw exact-string leaf equality" as the
default, with an explicit `match_mode` opt-out on the ConcernVariable for
thematic markers embedded in free-form text.

---

## 4. SWE-bench Lite mini (public benchmark, small n)

**Question**: does the harness prompt help on a real bug corpus? We use
instances from SWE-bench Lite (300-instance test split).

**Scoring axes** — proxies for correctness. We do NOT execute the tests
(that requires per-repo Docker + minutes/instance); instead we measure
patch localization:

- `file_match`: does the proposed patch touch the same file as the gold?
- `symbol_match`: does it touch the same function/class name?
- `line_locus`: is at least one changed line within ±5 of a gold-changed line?
- `axes_passed >= 2` as the headline.

**Final run** (10 instances, 360s timeout, 4 workers; `runs/swebench_lite_mini_v2/`):

| arm | n | file | symbol | locus | axes>=2 | wall_avg |
|-----|---|------|--------|-------|---------|----------|
| raw | 8 (2 timeouts) | 1.00 | 0.38 | 0.75 | **0.75** | 60s |
| harness | 9 (1 timeout) | 1.00 | 0.44 | 1.00 | **1.00** | 186s |

Harness completed 9/10; raw 8/10. Every completed harness patch hit at
least 2/3 axes; only 6/8 raw patches did. The main separation is
line-locus (100% vs 75%). Symbol match is a wash (0.44 vs 0.38). File
match is 1.00 in both arms — the harness had the target file pinned in
the ledger, but raw found it too from the problem statement.

**Two honesty caveats**:

1. The harness prompt's ledger includes `target_files` and
   `target_symbols` extracted from the gold patch. In a real pipeline
   that step would come from code-search or expert triage, not from
   ground truth. So this run is an **upper bound** on the harness's
   benefit assuming perfect retrieval. It is not measuring the value of
   the retrieval step itself.
2. n = 10 is directional, not statistically significant. Real SWE-bench
   evaluation requires pytest inside per-repo Docker, which we did not
   run.

---

## What we're NOT claiming

- **Not "harness beats SOTA."** Everything here is on our own synthetic
  suites plus a 10-instance SWE-bench sample. No large-n public
  benchmark yet.
- **Not "harness beats a well-engineered raw prompt."** §1 shows they
  tie on these suites.
- **Not "load-bearing certificates prove faithfulness."** They record
  whether the harness's gates saw a concern variable in a payload; they
  do not prove the model reasoned about it. Cf. paper §7.

---

## What we ARE claiming (narrow)

- With the strict transport auditor, the harness has < 1% overblocking on
  correct oracle actions across four suites (n = 440).
- With the same auditor, the harness catches 5/5 held-out proxy shapes at
  n = 220/shape while keeping control-arm pass rate at 0.99.
- The runtime scoring is separable and reportable: each `LoadBearingCertificate`
  contains behavior / transport / proxy / reopenability / commitment_validity
  components with the failed gates listed. This is the "bookkeeping identity"
  the paper asks for; the harness enforces it at runtime.

---

## What would strengthen the case

- Run §1 with an additional arm: `raw + schema + step-by-step reasoning`.
- Scale §4 to 50-100 SWE-bench Lite instances with actual pytest execution
  (needs Docker orchestration).
- Add τ²-bench or BFCL v2 subset for a public tool-use comparison.
- Add per-token cost columns to every leaderboard.
- Add a *matched-oracle* ablation for §3: an oracle that emits each proxy
  variant deliberately, to confirm the gate blocks the exact wrong action
  it was designed to.

---

## 5. External harness and orchestration evidence path

This branch adds evidence machinery, not new live leaderboard claims.

New measurable surfaces:

- `OpenAICompatibleHarnessAdapter` lets Fugu-style and OpenAI-compatible
  external harnesses run under the same ledger and certificate loop as local
  agents.
- `OrchestrationAuditor` turns multi-agent handoff traces into transport and
  proxy gates, so learned orchestration can be audited under the same
  load-bearing certificate.
- `lbah diagnose` reads `runs.jsonl`, groups failures by gate family, and
  proposes the next falsifiable harness-improvement experiment.
- `scripts/harness_effects_matrix.py` runs a small model-harness matrix and
  writes a diagnostic report.

What this supports now:

- Unit and runner tests prove that missing required orchestration traces can
  change a certificate decision.
- Diagnostic tests prove that failed gates are grouped into actionable
  improvement families.
- Config examples document how to point LBAH at Fugu/Fugu Ultra once
  credentials are present.

What remains unclaimed:

- No Fugu, OpenHands, or SWE-agent external run has been executed in this repo
  yet.
- No public benchmark win is claimed from the new adapter.
- No automated harness self-modification is enabled; diagnostics are proposal
  artifacts only.
