#!/usr/bin/env python
"""Run generated LBAH official SWE-bench manifests locally or on Modal."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lbah.coding.official_swebench import (  # noqa: E402
    DopplerRunConfig,
    load_official_swebench_command,
    plan_contamination_probe_on_artifacts,
    plan_official_swebench_run,
    run_contamination_probe_on_artifacts,
    run_official_swebench_plan,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command_json", help="official/run_evaluation_command.json or official/subsets/n*.json")
    parser.add_argument("--target", choices=["local", "modal"], default="modal")
    parser.add_argument("--max-workers", type=int)
    parser.add_argument("--run-id")
    parser.add_argument("--cache-level", choices=["none", "base", "env", "instance"])
    parser.add_argument("--namespace")
    parser.add_argument("--modal-gpu", help="Document an intended GPU, e.g. L4. Official SWE-bench grading ignores this.")
    parser.add_argument("--doppler", action="store_true", help="Run through doppler so Modal tokens stay in env only.")
    parser.add_argument("--doppler-project", default="cofounder")
    parser.add_argument("--doppler-config", default="dev")
    parser.add_argument("--allow-local-low-disk", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--enable-contamination-probe",
        action="store_true",
        help=(
            "After grading, retroactively run Track D contamination probe on the "
            "Modal artifact directory. This does NOT invoke Modal; it scans the "
            "already-graded predictions.jsonl + report.json + optional "
            "contamination_markers.jsonl sidecar. Use --contamination-artifact-dir "
            "to override the directory."
        ),
    )
    parser.add_argument(
        "--contamination-artifact-dir",
        default=None,
        help="Directory holding predictions.jsonl + report.json (default: dirname of command_json).",
    )
    parser.add_argument(
        "--contamination-markers",
        default=None,
        help="JSONL sidecar mapping instance_id -> leak_marker / issue_text.",
    )
    parser.add_argument(
        "--contamination-out",
        default=None,
        help="Where to write contamination_probe.jsonl (default: <artifact-dir>/contamination_probe.jsonl).",
    )
    args = parser.parse_args()

    command = load_official_swebench_command(args.command_json)
    plan = plan_official_swebench_run(
        command,
        target=args.target,
        max_workers=args.max_workers,
        run_id=args.run_id,
        cache_level=args.cache_level,
        namespace=args.namespace,
        modal_gpu=args.modal_gpu,
        use_doppler=args.doppler,
        doppler=DopplerRunConfig(project=args.doppler_project, config=args.doppler_config),
        allow_local_low_disk=args.allow_local_low_disk,
    )

    for warning in plan.warnings:
        print(f"[official-swebench] warning: {warning}", file=sys.stderr)
    print(plan.shell_command())
    if args.dry_run:
        rc = 0
    else:
        rc = run_official_swebench_plan(plan).returncode

    if args.enable_contamination_probe:
        artifact_dir = Path(args.contamination_artifact_dir or Path(args.command_json).parent)
        probe_plan = plan_contamination_probe_on_artifacts(
            artifact_dir,
            markers_path=args.contamination_markers,
        )
        for warning in probe_plan.warnings:
            print(f"[contamination-probe] warning: {warning}", file=sys.stderr)
        results = run_contamination_probe_on_artifacts(probe_plan)
        out_path = Path(
            args.contamination_out or artifact_dir / "contamination_probe.jsonl"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "\n".join(json.dumps(dataclasses.asdict(r)) for r in results)
            + ("\n" if results else "")
        )
        flagged = sum(1 for r in results if r.flagged)
        print(
            f"[contamination-probe] wrote {out_path} ({len(results)} rows, "
            f"{flagged} flagged)"
        )

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
