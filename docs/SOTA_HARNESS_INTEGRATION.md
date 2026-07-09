# SOTA Harness Integration Plan

This note describes how LBAH builds on current agent-harness research while preserving its own theory: concern variables must be load-bearing at the surfaces where an agent commits.

## What changed

LBAH can now wrap a black-box OpenAI-compatible agent harness, including Fugu-style orchestrators, through `OpenAICompatibleHarnessAdapter`. The external harness still proposes actions, but LBAH owns the concern ledger, transport checks, proxy checks, freshness gates, validators, and certificates.

LBAH also audits multi-agent orchestration traces. If a proposal includes an `orchestration` payload, `OrchestrationAuditor` checks that high-concern variables survive into handoffs and that shared transcript patterns do not collapse independent workers into the same shortcut trajectory.

Finally, `lbah diagnose` turns run JSONL into a compact model-harness diagnostic report. It groups failures by gate family and proposes the next falsifiable harness-improvement experiment.

## Research grounding

Verified citations only (see `docs/DESIGN_ROADMAP.md` §7). Unverified placeholder IDs
were purged in Phase 4.

- **Correlation is not control.** Static provenance / IFC systems nominate carriers;
  LBAH confirms commitment effect under intervention. Compose cheap nomination with
  gauge-fixing: [CaMeL](https://arxiv.org/abs/2503.18813),
  [FIDES](https://arxiv.org/abs/2505.23643),
  [Agent-Sentry](https://arxiv.org/abs/2603.22868),
  [No-Certificate-No-Execution](https://arxiv.org/abs/2605.24462),
  [PACT](https://arxiv.org/abs/2605.11039).
- **Certificates as pre-execution authorization / replay.**
  [No-Cert-No-Exec](https://arxiv.org/abs/2605.24462);
  [Proof of Execution](https://arxiv.org/abs/2607.05397).
- **Weak oracles and false passes.** Tournament winners must survive augmented tests:
  [UTBoost](https://arxiv.org/abs/2506.09289),
  [PatchDiff](https://arxiv.org/abs/2503.15223),
  [SWE-ABS](https://arxiv.org/abs/2603.00520).
- **Runtime contamination / leakage.**
  [Cursor (2026-06-25)](https://cursor.com/blog/reward-hacking-coding-benchmarks);
  [SWE-Bench+](https://arxiv.org/abs/2410.06992).
- **Tool-use failure taxonomy → validators.**
  [ToolFailBench](https://arxiv.org/abs/2607.04686),
  [ToolScan](https://arxiv.org/abs/2411.13547).
- **External harness posture (no primary paper claimed).** Fugu-style OpenAI-compatible
  orchestrators are an *integration shape* LBAH can wrap; they are not cited as a
  verified research result here. Interface design still matters for software agents
  ([SWE-agent](https://arxiv.org/abs/2405.15793),
  [OpenHands](https://arxiv.org/abs/2407.16741)) — LBAH's adapter layer measures those
  systems as workers under load-bearing certificates.

## Theory extension

The load-bearing standard already has four obligations:

- Concern: which distinctions matter.
- Transport: whether those distinctions survive into commitment.
- Gauge fixing: whether proxy-equivalent alternatives are ruled out.
- Commitment effect: whether the surface behavior depends on the distinction.

Multi-agent systems add a new place where these obligations can fail: handoff topology. A worker can receive the right task but not the right concern, or every worker can see the same shared transcript and converge on the same proxy. LBAH treats this as ordinary load-bearing evidence:

- Handoff access lists are transport chains.
- Worker isolation is a gauge-fixing condition.
- Shared memory is allowed when it carries durable context without overwriting independent solution paths.
- The final action is still the commitment surface.

This keeps orchestration theory inside the existing concern, transport, gauge, and commitment contract instead of adding a parallel theory.

## Running external harnesses

Install locally:

```bash
pip install -e ".[dev]"
```

Configure an OpenAI-compatible harness:

```yaml
name: fugu
type: fugu
base_url: https://api.sakana.ai
model: fugu
api_key_env: SAKANA_API_KEY
endpoint_path: /v1/chat/completions
temperature: 0.0
max_tokens: 4096
timeout: 300
```

Run one task:

```bash
lbah run --task moved_bottleneck:0 --agent configs/fugu_openai_compatible.yaml --mode audit --out runs/fugu_one
```

Run a small matrix:

```bash
python scripts/harness_effects_matrix.py \
  --suite moved_bottleneck \
  --agents configs/dummy.yaml configs/oracle.yaml configs/fugu_openai_compatible.yaml \
  --modes guarded,audit \
  --seeds 16 \
  --out runs/harness_matrix
```

Read the diagnostic report:

```bash
lbah diagnose runs/harness_matrix/runs.jsonl --out runs/harness_matrix/diagnostic_report.md
```

## Orchestration trace contract

External multi-agent systems can add an optional trace to the action payload:

```json
{
  "value": "lbah/core/runner.py",
  "orchestration": {
    "handoffs": [
      {
        "to": "planner",
        "variables": ["target_file"],
        "access_list": []
      },
      {
        "to": "worker",
        "variables": ["target_file"],
        "access_list": ["planner"]
      }
    ],
    "shared_transcript": true
  }
}
```

For tasks that require this evidence, set `metadata.requires_orchestration_trace: true`. Missing traces then fail a transport gate. Traces that omit high-concern variables fail concern transport. Shared transcripts without isolation or access lists fail the gauge-collapse check.

## What this is not

This is not a claim that LBAH beats SOTA harnesses. It is a way to wrap and measure them under LBAH's load-bearing contract.

This is not Fugu reimplementation. Fugu's learned routing and training recipe remain external. LBAH adds concern-aware auditability around model-like orchestrators.

This is not production self-modification. Diagnostic proposals are candidate harness edits; a human or future controlled loop still has to apply them and rerun the matrix.

## Next evidence gates

- Run `configs/fugu_openai_compatible.yaml` and `configs/fugu_ultra_openai_compatible.yaml` on the built-in suites once credentials are available.
- Add an OpenHands or SWE-agent server adapter config and compare the same suites.
- Scale `scripts/harness_effects_matrix.py` to a public coding slice with executable tests.
- Track cost and latency as first-class axes in `diagnostic_report.md`.
- Promote recurring diagnostic proposals into a controlled harness-evolution script with before/after predictions.
