# SOTA Harness Integration Plan

This note describes how LBAH builds on current agent-harness research while preserving its own theory: concern variables must be load-bearing at the surfaces where an agent commits.

## What changed

LBAH can now wrap a black-box OpenAI-compatible agent harness, including Fugu-style orchestrators, through `OpenAICompatibleHarnessAdapter`. The external harness still proposes actions, but LBAH owns the concern ledger, transport checks, proxy checks, freshness gates, validators, and certificates.

LBAH also audits multi-agent orchestration traces. If a proposal includes an `orchestration` payload, `OrchestrationAuditor` checks that high-concern variables survive into handoffs and that shared transcript patterns do not collapse independent workers into the same shortcut trajectory.

Finally, `lbah diagnose` turns run JSONL into a compact model-harness diagnostic report. It groups failures by gate family and proposes the next falsifiable harness-improvement experiment.

## Research grounding

- [Sakana Fugu Technical Report](https://arxiv.org/abs/2606.21228): learned orchestration can route and coordinate frontier workers behind one model-like API. LBAH adopts the integration posture, not the proprietary training recipe.
- [Harness-Bench](https://arxiv.org/abs/2605.27922): agent capability should be reported at the model-harness configuration level, with traces and validators beyond final task success. LBAH's comparison and diagnostic commands report exactly that configuration level.
- [Code as Agent Harness](https://arxiv.org/abs/2605.18747): code is the executable, inspectable substrate for agent reasoning, acting, state, and verification. LBAH treats the ledger and certificate as code-level contracts around that substrate.
- [Natural-Language Agent Harnesses](https://arxiv.org/abs/2603.25723): harness policy can become an inspectable artifact instead of hidden controller glue. LBAH keeps the theory in docs and the gates in small modules that can be ablated.
- [Agentic Harness Engineering](https://arxiv.org/abs/2604.25850): harness edits should be tied to observability and falsifiable predictions. `lbah diagnose` is the first local loop for turning failed gates into candidate edits and next experiments.
- [SWE-agent](https://arxiv.org/abs/2405.15793) and [OpenHands](https://arxiv.org/abs/2407.16741): interface and platform design materially change software-agent outcomes. LBAH's adapter layer lets those systems become measured workers rather than uninspected competitors.

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
