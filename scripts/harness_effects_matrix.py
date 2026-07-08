"""Run a model-harness matrix and emit a diagnostic report.

This is a thin orchestration layer over the public CLI. It is meant for quick
Harness-Bench-style slices: same suite, same seeds, several agent configs,
guarded/audit modes, then an LBAH diagnostic report over the resulting JSONL.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default="moved_bottleneck")
    parser.add_argument("--agents", nargs="+", required=True)
    parser.add_argument("--modes", default="guarded,audit")
    parser.add_argument("--seeds", type=int, default=16)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    compare_cmd = [
        sys.executable,
        "-m",
        "lbah.cli",
        "compare",
        "--suite",
        args.suite,
        "--mode",
        args.modes,
        "--seeds",
        str(args.seeds),
        "--out",
        str(out_dir),
        *args.agents,
    ]
    subprocess.run(compare_cmd, check=True)

    report_path = out_dir / "diagnostic_report.md"
    diagnose_cmd = [
        sys.executable,
        "-m",
        "lbah.cli",
        "diagnose",
        str(out_dir / "runs.jsonl"),
        "--out",
        str(report_path),
    ]
    subprocess.run(diagnose_cmd, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
