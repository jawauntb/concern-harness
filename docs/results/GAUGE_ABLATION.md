# Gauge ablation — Phase 0

Status: 2026-07-09. Closes DESIGN_ROADMAP Phase 0 acceptance item 3.

## What changed

- CLI `--gauge-budget` / `--gauge-min-concern` wired through `run` / `bench` / `compare`.
- Mode YAMLs (`configs/guarded_mode.yaml`, `configs/audit_mode.yaml`) default
  `gauge_probe_budget: 2`.
- `LoadBearingCertificate.gauge_results` is a first-class field (gauge gates also
  remain in `proxy_results` for backward compatibility).
- Bench/compare JSONL rows always persist all five component scores.

## Held-out proxy twins (`moved_bottleneck`, 8 seeds)

Command:

```bash
python scripts/heldout_proxy_twins.py --suites moved_bottleneck --seeds 8 \
  --gauge-budget 0 --out runs/gauge_ablation_off
python scripts/heldout_proxy_twins.py --suites moved_bottleneck --seeds 8 \
  --gauge-budget 2 --out runs/gauge_ablation_on
```

| variant | n | allowed (off) | allowed (on) | by_gauge (off) | by_gauge (on) |
|---|---:|---:|---:|---:|---:|
| good | 8 | 1.00 | 1.00 | 0.00 | 0.00 |
| slot_substring | 3 | 0.00 | 0.00 | 0.00 | 1.00 |
| slot_whitespace | 8 | 0.00 | 0.00 | 0.00 | 1.00 |

### Read

- **No overblocking:** Oracle-shaped `good` stays fully allowed with gauge on;
  gauge does not fail on load-bearing commitments (`by_gauge=0` on good).
- **Gauge fires on held-out proxies:** with `budget=2`, every held-out variant
  records at least one failed `proxy::gauge_fixing` gate (`by_gauge=1.0`).
- **Transport already catches these shapes:** `by_tport` is high on both arms
  for this suite (exact-leaf / whitespace / substring mismatches). The gauge
  signal is therefore *redundant but independent* here — it confirms the
  commitment is not controlled by the claimed concern under perturbation.
- Claim level: **synthetic diagnostic** on the held-out twin script, not a
  coding-agent result.

## CLI smoke

```bash
lbah bench --suite moved_bottleneck --agent configs/oracle.yaml \
  --mode audit --seeds 2 --gauge-budget 2 --out /tmp/lbah_gauge_smoke
```

Every JSONL row has `behavior_score`, `transport_score`,
`proxy_resistance_score`, `reopenability_score`, `commitment_validity_score`,
and `gauge_gate_count > 0`.

## Tests

`tests/test_phase0_cli_telemetry.py` plus existing gauge/scoring/diagnostics
suites — all green at merge time.
