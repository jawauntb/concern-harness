"""Evaluate read-set load-bearingness (Law 2 at the coding surface).

For each instance we plant K read carriers in the task metadata (one
issue-derived, one leak-tracking, the rest pure distractors), run one
:func:`gauge_fixing_probe` per read, and flag the set that actually drove the
commitment. Ground truth per instance says which reads should be load-bearing;
we score the predicted set with precision / recall / F1.

Usage:
  python scripts/read_set_load_bearing.py --seeds 8 --reads 4 --out runs/read_set_load_bearing
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lbah.coding.contamination import (
    generate_read_set_slice,
    run_read_set_probe,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--reads", type=int, default=4)
    ap.add_argument("--out", default="runs/read_set_load_bearing")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slice_root = out / "repos"
    instances = generate_read_set_slice(
        slice_root, seeds=args.seeds, reads_per_task=args.reads
    )

    rows: list[dict] = []
    t0 = time.time()
    for instance in instances:
        result = run_read_set_probe(instance)
        rows.append(
            {
                "seed": instance.seed,
                "per_read": [v.model_dump() for v in result.per_read],
                "predicted_load_bearing": result.predicted_load_bearing,
                "true_load_bearing": result.true_load_bearing,
                "set_precision": result.set_precision,
                "set_recall": result.set_recall,
                "set_f1": result.set_f1,
            }
        )

    (out / "results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n"
    )

    n = len(rows)
    macro_p = statistics.mean(r["set_precision"] for r in rows) if rows else 0.0
    macro_r = statistics.mean(r["set_recall"] for r in rows) if rows else 0.0
    macro_f1 = statistics.mean(r["set_f1"] for r in rows) if rows else 0.0

    # Per-read confusion at the read-level for a quick sanity readout.
    total_reads = sum(len(r["per_read"]) for r in rows)
    tp = sum(
        1
        for r in rows
        for v in r["per_read"]
        if v["label"] == "load_bearing" and v["verdict"] == "load_bearing"
    )
    fp = sum(
        1
        for r in rows
        for v in r["per_read"]
        if v["label"] == "distractor" and v["verdict"] == "load_bearing"
    )
    fn = sum(
        1
        for r in rows
        for v in r["per_read"]
        if v["label"] == "load_bearing" and v["verdict"] == "redundant"
    )
    tn = sum(
        1
        for r in rows
        for v in r["per_read"]
        if v["label"] == "distractor" and v["verdict"] == "redundant"
    )

    lines = [
        "# Read-set load-bearingness — Phase 2 (Law 2 at the coding surface)",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**synthetic diagnostic** on a controlled multi-read slice "
        "(not a human-validated benchmark, not Modal SWE-bench).",
        "",
        "## Method",
        "",
        "For each instance we plant K read carriers in the task metadata: one",
        "issue-derived (ground-truth load-bearing), one leak-tracking, and the",
        "rest pure distractors. A synthetic `commit_fn` signs the diff with the",
        "value of each ground-truth load-bearing read only. We run one",
        "`gauge_fixing_probe` per read and predict *load_bearing* iff perturbing",
        "the read moved the commitment, else *redundant*. Set precision /",
        "recall / F1 are scored against the ground-truth load-bearing set.",
        "",
        f"Seeds: {args.seeds}, reads per task: {args.reads}, total instances: {n}.",
        f"Wall: {time.time() - t0:.2f}s.",
        "",
        "## Results",
        "",
        "| metric | value | target |",
        "|---|---:|---:|",
        f"| set precision (macro) | {macro_p:.3f} | ≥ 0.95 |",
        f"| set recall (macro) | {macro_r:.3f} | ≥ 0.95 |",
        f"| set F1 (macro) | {macro_f1:.3f} | ≥ 0.95 |",
        "",
        "### Per-read confusion",
        "",
        "| label \\ verdict | load_bearing | redundant |",
        "|---|---:|---:|",
        f"| load_bearing (truth) | {tp} | {fn} |",
        f"| distractor (truth)   | {fp} | {tn} |",
        "",
        f"Total per-read decisions: {total_reads}.",
        "",
        "## Acceptance",
        "",
        f"- F1 ≥ 0.95: {'PASS' if macro_f1 >= 0.95 else 'FAIL'} ({macro_f1:.3f})",
        f"- Precision ≥ 0.95: {'PASS' if macro_p >= 0.95 else 'FAIL'} ({macro_p:.3f})",
        f"- Recall ≥ 0.95: {'PASS' if macro_r >= 0.95 else 'FAIL'} ({macro_r:.3f})",
        "",
        "## Artifacts",
        "",
        f"- `{out / 'results.jsonl'}` — one row per instance with per-read verdicts",
        "",
    ]
    report = "\n".join(lines)
    (out / "READ_SET_LOAD_BEARING.md").write_text(report)
    docs = Path("docs/results")
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "READ_SET_LOAD_BEARING.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
