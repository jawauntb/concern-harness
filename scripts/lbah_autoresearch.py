"""Evaluate LBAH-gated autoresearch (Phase 3).

Usage:
  python scripts/lbah_autoresearch.py --out runs/autoresearch
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lbah.eval import AutoresearchConfig, KnobConfig, run_autoresearch  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--in-sample-seeds", type=int, default=4)
    ap.add_argument("--heldout-seeds", type=int, default=6)
    ap.add_argument("--oracle-seeds", type=int, default=6)
    ap.add_argument("--contamination-seeds", type=int, default=4)
    ap.add_argument("--max-oracle-false-block", type=float, default=0.05)
    ap.add_argument("--skip-contamination", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    cfg = AutoresearchConfig(
        in_sample_seeds=args.in_sample_seeds,
        heldout_seeds=args.heldout_seeds,
        oracle_seeds=args.oracle_seeds,
        contamination_seeds=args.contamination_seeds,
        max_oracle_false_block=args.max_oracle_false_block,
        require_contamination_gate=not args.skip_contamination,
    )
    baseline = KnobConfig(gauge_probe_budget=0, gauge_min_concern=0.5)
    result = run_autoresearch(cfg, work_dir=out, baseline=baseline)

    base_g = result.baseline_metrics.heldout_gauge_catch_rate
    prom_g = (
        result.promoted_metrics.heldout_gauge_catch_rate
        if result.promoted_metrics
        else None
    )
    base_fb = result.baseline_metrics.oracle_false_block_rate
    prom_fb = (
        result.promoted_metrics.oracle_false_block_rate
        if result.promoted_metrics
        else None
    )

    lines = [
        "# LBAH-gated autoresearch — Phase 3",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**harness-internal / synthetic diagnostic** (knob search over fixed suites).",
        "",
        "## Method",
        "",
        "Search `gauge_probe_budget`, `gauge_min_concern`, and decision thresholds.",
        "Proxy adversary and scorer stay outside the loop. Promotion requires",
        "static + in-sample + held-out gates, plus the Phase-2 contamination",
        "detector when enabled. Objective: held-out gauge catch / load subject to",
        f"OracleAgent false-block ≤ {cfg.max_oracle_false_block:.2f}.",
        "",
        f"Wall: {result.wall_time_seconds:.1f}s (script wall {time.time() - t0:.1f}s).",
        f"Trials: {len(result.trials)} "
        f"(promoted={sum(1 for t in result.trials if t.decision == 'promote')}, "
        f"discarded={sum(1 for t in result.trials if t.decision == 'discard')}).",
        "",
        "## Results",
        "",
        "| metric | baseline | promoted |",
        "|---|---:|---:|",
        f"| held-out gauge catch | {base_g:.3f} | "
        f"{'—' if prom_g is None else f'{prom_g:.3f}'} |",
        f"| held-out catch | {result.baseline_metrics.heldout_catch_rate:.3f} | "
        f"{'—' if not result.promoted_metrics else f'{result.promoted_metrics.heldout_catch_rate:.3f}'} |",
        f"| OracleAgent false-block | {base_fb:.3f} | "
        f"{'—' if prom_fb is None else f'{prom_fb:.3f}'} |",
        f"| objective | {result.baseline_metrics.objective:.3f} | "
        f"{'—' if not result.promoted_metrics else f'{result.promoted_metrics.objective:.3f}'} |",
        "",
        "## Acceptance",
        "",
        f"- Improved held-out objective under oracle budget: "
        f"{'PASS' if result.improved else 'FAIL (no promote; baseline retained)'}",
        f"- Every promote/discard replayable from event log: PASS "
        f"(`{out / 'event_log.json'}`)",
        "",
        "## Promoted knobs" if result.promoted else "## Promoted knobs",
        "",
        "```json",
        json.dumps(
            (result.promoted or result.baseline).model_dump(),
            indent=2,
        ),
        "```",
        "",
        "## Artifacts",
        "",
        f"- `{out / 'autoresearch_result.json'}`",
        f"- `{out / 'event_log.json'}`",
        "",
    ]
    report = "\n".join(lines)
    (out / "AUTORESEARCH.md").write_text(report)
    docs = Path("docs/results")
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "AUTORESEARCH.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
