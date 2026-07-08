#!/usr/bin/env python
"""Summarize official SWE-bench reports for a candidate matrix."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lbah.coding.swebench_candidates import (  # noqa: E402
    infer_swebench_candidate_id_from_path,
    load_swebench_candidate_matrix_manifest,
    load_swebench_official_candidate_report,
    summarize_swebench_candidate_reports,
    write_swebench_candidate_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        required=True,
        help="Path to candidate_matrix_manifest.json from modal_lbah_swebench_tournament.py.",
    )
    parser.add_argument(
        "--report",
        action="append",
        required=True,
        help="Official report path, or candidate_id=path when the path does not include candidate_000.",
    )
    parser.add_argument("--out", help="Optional JSON summary output path.")
    args = parser.parse_args()

    manifest = load_swebench_candidate_matrix_manifest(args.matrix)
    reports = [
        load_swebench_official_candidate_report(candidate_id, path)
        for candidate_id, path in (_parse_report_arg(value) for value in args.report)
    ]
    summary = summarize_swebench_candidate_reports(manifest, reports)
    if args.out:
        write_swebench_candidate_summary(args.out, summary)
    print(
        "candidate summary: "
        f"{summary.report_count}/{summary.candidate_count} reports, "
        f"oracle {summary.oracle_resolved_instances}/{summary.total_instances} resolved"
    )
    for report in summary.candidate_reports:
        role = f" ({report.role_label})" if report.role_label else ""
        print(
            f"- {report.candidate_id}{role}: "
            f"{report.resolved_instances}/{report.submitted_instances} resolved, "
            f"errors={report.error_instances}, empty={report.empty_patch_instances}"
        )
    if summary.missing_report_candidate_ids:
        missing = ", ".join(summary.missing_report_candidate_ids)
        print(f"missing reports: {missing}", file=sys.stderr)
    return 0


def _parse_report_arg(value: str) -> tuple[str, str]:
    if "=" in value:
        candidate_id, path = value.split("=", 1)
        if not candidate_id:
            raise ValueError(f"empty candidate id in --report {value!r}")
        if not path:
            raise ValueError(f"empty path in --report {value!r}")
        return candidate_id, path
    return infer_swebench_candidate_id_from_path(value), value


if __name__ == "__main__":
    raise SystemExit(main())
