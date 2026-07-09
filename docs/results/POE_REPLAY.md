# PoE-style replay capture — Track C

Status: 2026-07-09. Infrastructure only. This is a probe-trust foundation, not
an empirical result. Motivated by `docs/DESIGN_ROADMAP.md` §5 Risks
("Replay trust — the probe is only as trustworthy as replay determinism.
Adopt PoE-style capture of tool/LLM I/O before claiming reproducibility.
arXiv:2607.05397") and §Phase 1 task 1 ("Align with PoE-style replay
envelopes where cheap: capture tool/LLM I/O needed for probe replay").

## What landed

Two new event types on the append-only logs, plus a small replay module:

| module | added |
|---|---|
| `lbah/core/events.py` | `EventType` gets `record_llm_io`; projection skips it |
| `lbah/coding/events.py` | `CodingEventType` gets `record_llm_io`, `record_tool_io`; projection skips both |
| `lbah/core/replay.py` | `IOEnvelope`, `ReplayModelAdapter`, `capture_llm_io`, `envelopes_from_log`, `ReplayMismatchError` |
| `lbah/coding/replay.py` | `ToolEnvelope`, `ReplayToolExecutor`, `bundle_from_log` |
| `lbah/coding/runner.py` | `CodingHarnessRunner(..., capture_io=False)` opt-in flag |

## Envelope schema

`IOEnvelope` (one per `.complete()` call):

- `call_index: int` — monotonic per capturing wrapper. Replay consumes
  envelopes in ascending `call_index` order.
- `request: dict` — the normalised call arguments: `messages`, `schema`,
  `tools`, `temperature`, `max_tokens`. Normalisation is `json.dumps` with
  `sort_keys=True`, so dict-iteration order is not part of the request
  identity.
- `response: dict` — the raw return value of the adapter (deep-copied at
  capture time so downstream mutation does not corrupt the envelope).
- `adapter_name: str | None` — provenance only; not part of the match.

`ToolEnvelope` (coding runner, one per executed action):

- `step: int` — position in the tool stream.
- `action: dict` — the `CodingAction` as recorded by the runner.
- `observation: dict` — the `CodingObservation` the runner produced.

## Captured surfaces

- **LLM calls.** Any object with a `.complete()` method that the coding
  runner reaches through `agent.model` is wrapped by
  `CapturingModelAdapter` when `capture_io=True`. Covers `EchoModel`,
  `ProviderLLMAdapter`, `LocalLLMAdapter`, `ClaudeCodeCLIAdapter`,
  and any `ModelCodingAgent` (they all share the `.complete()` shape).
- **Tool calls.** The coding runner captures `(action, observation)` pairs
  for every executed step — inspect, search, read_file, edit_file,
  run_command, run_tests, finish. Failed and successful actions alike.

Both surfaces are captured on the same `CodingEventLog` so a replay bundle
is a function of one artefact.

## Replay contract

`ReplayModelAdapter` and `ReplayToolExecutor` are strict on purpose:

1. Responses / observations are returned in captured order.
2. Every incoming request must match the captured request under
   `_normalise_request`. Mismatch raises `ReplayMismatchError` with a
   `difflib.unified_diff` between expected and actual — the whole point of
   PoE-style capture is that divergence is loud, not silent.
3. Running past the captured stream raises `ReplayMismatchError` — the
   caller invoked the model or a tool more times than was recorded.

`envelopes_from_log` reconstructs the ordered envelope stream from a
completed run's log; `bundle_from_log` (coding-side) returns the paired
model + tool executor ready to drop into a fresh runner.

## Guarantees / non-guarantees

- **Opt-in.** `capture_io=False` by default. Existing runs incur no wrapper,
  no extra events, no perf hit.
- **Projection-invariant.** `record_llm_io` and `record_tool_io` are skipped
  by both projections, so the `ConcernLedger` / `CodingLedger` a replay
  reconstructs is bit-identical to the original (verified in
  `test_projection_ignores_io_events`).
- **What it does not verify.** This module makes replay possible; it does
  not by itself prove that the certificate is a pure function of the
  ledger. That is the next brick — a certificate-replay probe that runs a
  bundle and asserts the resulting commitment matches the original.
- **Non-determinism outside the two streams.** If a captured run consulted
  something beyond `agent.model.complete` and the coding runner's tool
  actions (e.g. an agent that reads its own `os.environ`), replay does not
  cover it. The design keeps this boundary explicit so an eventual gauge
  probe of "did the certificate use anything we did not capture?" has a
  clear failure mode.

## Claim level

**Infrastructure**, not an empirical result. The wired probe-trust claim is:
given a completed coding run captured with `capture_io=True`,
`bundle_from_log` produces a model + tool executor from which the exact
same LLM responses and tool observations can be replayed in order. The
guarantee is byte-identical envelope replay; empirical claims that depend
on this (certificate reproducibility, gauge-probe reruns, tournament
replays) are follow-on work.
