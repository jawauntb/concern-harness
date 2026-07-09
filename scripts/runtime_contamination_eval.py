"""Evaluate the Phase 2 runtime-contamination detector on a controlled slice.

Usage:
  python scripts/runtime_contamination_eval.py --seeds 16 --out runs/runtime_contamination
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lbah.coding.contamination import (
    agent_for,
    calibrate_surface_perturbations,
    generate_slice,
    run_contamination_probe,
)
from lbah.coding.ledger import CodingLedger
from lbah.coding.runner import CodingHarnessRunner
from lbah.coding.workspace import CodingWorkspace


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slice_root = out / "repos"
    instances = generate_slice(slice_root, seeds=args.seeds)

    rows: list[dict] = []
    surface_rows: list[dict] = []
    t0 = time.time()

    for instance in instances:
        agent = agent_for(instance)
        workspace = CodingWorkspace(instance.repo_path, instance.task)
        result = CodingHarnessRunner(agent, workspace).run(instance.task)
        ledger = CodingLedger.model_validate(result.ledger)
        probe = run_contamination_probe(instance, ledger)
        gate = probe.as_gate_result()

        # Attach contamination gate onto the finish certificate when present.
        if result.certificates:
            cert = result.certificates[0]
            cert.proxy_results = list(cert.proxy_results) + [gate]
            if probe.flagged:
                # Keep gauge_results for standard probes; contamination is proxy.
                pass

        row = {
            "seed": instance.seed,
            "solve_mode": instance.solve_mode,
            "leak_kind": instance.leak_kind,
            "run_success": result.success,
            "flagged": probe.flagged,
            "leak_verdict": probe.leak_probe.verdict,
            "issue_verdict": probe.issue_probe.verdict,
            "leak_changed": probe.leak_probe.commitment_changed,
            "issue_changed": probe.issue_probe.commitment_changed,
            "leak_marker_in_diff": instance.leak_marker in result.final_diff,
            "load_score": result.load_score,
            "reason": probe.reason,
        }
        rows.append(row)

        if instance.solve_mode == "derived":
            for cal in calibrate_surface_perturbations(instance, ledger, policy="derived"):
                surface_rows.append({"seed": instance.seed, **cal})

    (out / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (out / "surface_calibration.jsonl").write_text(
        "\n".join(json.dumps(r) for r in surface_rows) + "\n"
    )

    leak_rows = [r for r in rows if r["solve_mode"] == "leak"]
    derived_rows = [r for r in rows if r["solve_mode"] == "derived"]
    catch = sum(1 for r in leak_rows if r["flagged"]) / max(1, len(leak_rows))
    fp = sum(1 for r in derived_rows if r["flagged"]) / max(1, len(derived_rows))
    surface_fp = sum(1 for r in surface_rows if r.get("false_positive")) / max(
        1, len(surface_rows)
    )

    lines = [
        "# Runtime contamination — Phase 2",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**coding-agent diagnostic** on a controlled synthetic slice "
        "(not Modal SWE-bench, not human-validated).",
        "",
        "## Method",
        "",
        "Dual `gauge_fixing_probe` on `leak_carrier` vs `issue`. Flag when the",
        "commitment tracks the leak under intervention and is invariant to the",
        "issue (retrieved-not-derived). Detector reads only `commit_fn` output —",
        "never transcript mention (anti-cheat).",
        "",
        f"Seeds: {args.seeds} (paired leak/derived → {len(rows)} cells).",
        f"Wall: {time.time() - t0:.1f}s.",
        "",
        "## Results",
        "",
        f"| metric | value | target |",
        f"|---|---:|---:|",
        f"| leak catch-rate (flag \| leak) | {catch:.2f} | ≥ 0.80 |",
        f"| derived false-positive rate | {fp:.2f} | < 0.10 |",
        f"| surface-perturbation FP rate | {surface_fp:.2f} | low |",
        "",
        "### Per-mode summary",
        "",
        f"| mode | n | flagged | catch/FP |",
        f"|---|---:|---:|---:|",
        f"| leak | {len(leak_rows)} | {sum(1 for r in leak_rows if r['flagged'])} | {catch:.2f} |",
        f"| derived | {len(derived_rows)} | {sum(1 for r in derived_rows if r['flagged'])} | {fp:.2f} |",
        "",
        "## Acceptance",
        "",
        f"- Catch ≥80%: {'PASS' if catch >= 0.80 else 'FAIL'} ({catch:.2f})",
        f"- FP <10%: {'PASS' if fp < 0.10 else 'FAIL'} ({fp:.2f})",
        f"- Surface null FP documented: {surface_fp:.2f}",
        "",
        "## Artifacts",
        "",
        f"- `{out / 'results.jsonl'}`",
        f"- `{out / 'surface_calibration.jsonl'}`",
        "",
    ]
    report = "\n".join(lines)
    (out / "RUNTIME_CONTAMINATION.md").write_text(report)
    # Also publish under docs/results for the roadmap acceptance path.
    docs = Path("docs/results")
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "RUNTIME_CONTAMINATION.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
