#!/usr/bin/env python
"""Inject Track D leak carriers into a SWE-bench JSONL slice (paper §4.4 b).

Reads an instances JSONL (from ``export_swebench_instances.py`` or any
SWE-bench-shaped dump), plants contamination metadata on each row that has a
gold patch, and writes:

* ``<out>/instances.jsonl`` — annotated instances (generation input)
* ``<out>/contamination_markers.jsonl`` — sidecar for
  ``run_official_swebench.py --enable-contamination-probe``
* ``<out>/inject_manifest.json`` — counts + skipped ids

Does **not** call Modal or spend credits. Checkout planting happens later in
``prepare_swebench_workspace`` when a generation run loads these instances.

Usage:
  python scripts/inject_swebench_leaks.py \\
      --instances runs/swebench_lite_n5/instances.jsonl \\
      --out runs/swebench_lite_n5_leaked

  # Induce retrieval the way Track D --force-retrieve does:
  python scripts/inject_swebench_leaks.py \\
      --instances runs/swebench_lite_n5/instances.jsonl \\
      --force-retrieve \\
      --out runs/swebench_lite_n5_leaked_force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lbah.coding.contamination.inject import (  # noqa: E402
    dump_inject_manifest,
    inject_leaks_into_instances,
    instances_to_jsonl,
    markers_to_jsonl,
)
from lbah.coding.swebench import load_swebench_instances  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--instances",
        required=True,
        help="Input SWE-bench JSON/JSONL (must include gold `patch` for injection).",
    )
    parser.add_argument("--out", required=True, help="Output directory.")
    parser.add_argument(
        "--leak-kind",
        choices=["git_history", "hint", "retrieved_doc"],
        default="git_history",
    )
    parser.add_argument(
        "--force-retrieve",
        action="store_true",
        help=(
            "Rewrite problem_statement to require consulting .lbah/leak/git_log.txt "
            "(Track D force-retrieve induction)."
        ),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    instances = load_swebench_instances(
        args.instances, limit=args.limit, offset=args.offset
    )
    result = inject_leaks_into_instances(
        instances,
        leak_kind=args.leak_kind,
        force_retrieve=args.force_retrieve,
    )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "instances.jsonl").write_text(instances_to_jsonl(result.instances))
    (out / "contamination_markers.jsonl").write_text(markers_to_jsonl(result.markers))
    (out / "inject_manifest.json").write_text(
        json.dumps(dump_inject_manifest(result), indent=2) + "\n"
    )
    print(
        f"wrote {len(result.instances)} instances "
        f"({len(result.injected)} injected, {len(result.skipped)} skipped) → {out}"
    )
    if result.skipped:
        print(f"skipped (no gold patch): {', '.join(result.skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
