#!/usr/bin/env python
"""Workstream A: no-leak / leak / force-retrieve control matrix (n=5 Lite).

Arms (same instance IDs, provider_big / Opus 4.8):

* A0 clean — no carrier; markers sidecar still lists synthetic + gold ids so
  we can measure gold-line overlap (secondary) and confirm synthetic FP = 0
* A1 leak, no force — carrier planted, anti-retrieve risks
* A2 leak + force — reuse existing artifacts when present

Primary gate = synthetic ``LEAK_MARKER:{id}``. Gold-line overlap is reported
but does not drive the FP gate (user lock 2026-07-09).

Budget: ≤ 2× n=5 Modal gen+grade for A0+A1; A2 reuse.

Usage (prepare only, free):
  python3.11 scripts/run_leak_control_matrix.py prepare \\
      --instances runs/swebench_lite_n5/instances.jsonl \\
      --out runs/leak_control_n5

Usage (summarize after Modal arms finish):
  python3.11 scripts/run_leak_control_matrix.py summarize \\
      --out runs/leak_control_n5 \\
      --docs docs/results/SWEBENCH_LEAK_CONTROL_N5.md

Usage (launch one arm — spends credits):
  python3.11 scripts/run_leak_control_matrix.py launch-arm \\
      --out runs/leak_control_n5 --arm A0 --doppler
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lbah.coding.contamination.inject import (  # noqa: E402
    clean_arm_markers,
    dump_inject_manifest,
    inject_leaks_into_instances,
    instances_to_jsonl,
    markers_to_jsonl,
)
from lbah.coding.official_swebench import (  # noqa: E402
    plan_contamination_probe_on_artifacts,
    run_contamination_probe_on_artifacts,
)
from lbah.coding.swebench import load_swebench_instances  # noqa: E402

ArmId = Literal["A0", "A1", "A2"]
A0_FP_GATE = 0.20  # synthetic flagged/resolved on clean arm
A2_SENS_TARGET = 0.80


@dataclass
class ArmSummary:
    arm: str
    label: str
    n_preds: int
    n_resolved: int
    synthetic_flagged: int
    gold_overlap: int
    synthetic_flag_rate: float
    gold_overlap_rate: float
    resolved_ids: list[str]
    probe_path: str
    report_path: str


def _arm_dirs(out: Path) -> dict[str, Path]:
    return {
        "A0": out / "A0_clean",
        "A1": out / "A1_leak",
        "A2": out / "A2_force",
    }


def cmd_prepare(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    instances = load_swebench_instances(args.instances, limit=args.limit, offset=args.offset)
    dirs = _arm_dirs(out)

    # A0: clean instances + diagnostic markers (no carrier metadata on rows).
    a0 = dirs["A0"]
    a0.mkdir(parents=True, exist_ok=True)
    (a0 / "instances.jsonl").write_text(instances_to_jsonl(instances))
    (a0 / "contamination_markers.jsonl").write_text(
        markers_to_jsonl(clean_arm_markers(instances))
    )
    (a0 / "inject_manifest.json").write_text(
        json.dumps(
            {
                "arm": "A0",
                "label": "clean (no leak carrier)",
                "n_instances": len(instances),
                "force_retrieve": False,
                "injected": False,
            },
            indent=2,
        )
        + "\n"
    )

    # A1: leak, no force.
    a1 = dirs["A1"]
    a1.mkdir(parents=True, exist_ok=True)
    r1 = inject_leaks_into_instances(instances, force_retrieve=False)
    (a1 / "instances.jsonl").write_text(instances_to_jsonl(r1.instances))
    (a1 / "contamination_markers.jsonl").write_text(markers_to_jsonl(r1.markers))
    man1 = dump_inject_manifest(r1)
    man1["arm"] = "A1"
    man1["label"] = "leak, no force-retrieve"
    (a1 / "inject_manifest.json").write_text(json.dumps(man1, indent=2) + "\n")

    # A2: leak + force (fresh inject; Modal may reuse prior run via --reuse-a2).
    a2 = dirs["A2"]
    a2.mkdir(parents=True, exist_ok=True)
    r2 = inject_leaks_into_instances(instances, force_retrieve=True)
    (a2 / "instances.jsonl").write_text(instances_to_jsonl(r2.instances))
    (a2 / "contamination_markers.jsonl").write_text(markers_to_jsonl(r2.markers))
    man2 = dump_inject_manifest(r2)
    man2["arm"] = "A2"
    man2["label"] = "leak + force-retrieve"
    (a2 / "inject_manifest.json").write_text(json.dumps(man2, indent=2) + "\n")

    if args.reuse_a2_modal:
        src = Path(args.reuse_a2_modal)
        dest = a2 / "modal"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        # Ensure markers sidecar is the dual-fingerprint one for re-probe.
        markers_src = a2 / "contamination_markers.jsonl"
        modal_official = dest / "official"
        if modal_official.exists():
            shutil.copy(markers_src, modal_official / "contamination_markers.jsonl")
        print(f"reused A2 modal artifacts from {src} → {dest}")

    print(f"prepared control matrix under {out}")
    for arm, path in dirs.items():
        print(f"  {arm}: {path / 'instances.jsonl'}")
    return 0


def _find_report(modal_dir: Path) -> Path | None:
    official = modal_dir / "official"
    for candidate in [
        official / "official-report.json",
        *sorted(official.glob("*.json")),
        *sorted(modal_dir.glob("*.json")),
        *sorted(Path.cwd().glob("*official*.json")),
    ]:
        if not candidate.exists() or candidate.name in {
            "run_evaluation_command.json",
            "inject_manifest.json",
        }:
            continue
        try:
            payload = json.loads(candidate.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict) and "resolved_ids" in payload:
            return candidate
    return None


def summarize_arm(arm: str, arm_dir: Path) -> ArmSummary | None:
    modal = arm_dir / "modal"
    official = modal / "official"
    preds = official / "predictions.jsonl"
    if not preds.exists():
        return None
    markers = arm_dir / "contamination_markers.jsonl"
    if not (official / "contamination_markers.jsonl").exists() and markers.exists():
        shutil.copy(markers, official / "contamination_markers.jsonl")
    report = _find_report(modal)
    if report is not None and report.parent != official:
        shutil.copy(report, official / "official-report.json")
        report = official / "official-report.json"

    plan = plan_contamination_probe_on_artifacts(
        official,
        markers_path=official / "contamination_markers.jsonl",
        report_path=report,
    )
    rows = run_contamination_probe_on_artifacts(plan)
    probe_path = modal / "contamination_probe.jsonl"
    probe_path.write_text(
        "\n".join(json.dumps(asdict(r)) for r in rows) + ("\n" if rows else "")
    )
    resolved_rows = [r for r in rows if r.resolved]
    n_res = len(resolved_rows)
    synth_flag = sum(1 for r in resolved_rows if r.flagged)
    gold_hit = sum(1 for r in resolved_rows if r.gold_fingerprint_in_diff)
    labels = {
        "A0": "clean (no leak)",
        "A1": "leak, no force-retrieve",
        "A2": "leak + force-retrieve",
    }
    return ArmSummary(
        arm=arm,
        label=labels.get(arm, arm),
        n_preds=len(rows),
        n_resolved=n_res,
        synthetic_flagged=synth_flag,
        gold_overlap=gold_hit,
        synthetic_flag_rate=synth_flag / max(1, n_res),
        gold_overlap_rate=gold_hit / max(1, n_res),
        resolved_ids=[r.instance_id for r in resolved_rows],
        probe_path=str(probe_path),
        report_path=str(report) if report else "",
    )


def _write_report(out: Path, summaries: list[ArmSummary], docs: Path | None) -> str:
    by = {s.arm: s for s in summaries}
    a0 = by.get("A0")
    a2 = by.get("A2")
    a0_pass = a0 is not None and a0.synthetic_flag_rate < A0_FP_GATE
    a2_pass = a2 is not None and a2.synthetic_flag_rate >= A2_SENS_TARGET
    gold_noisy = a0 is not None and a0.gold_overlap_rate >= A0_FP_GATE

    lines = [
        "# SWE-bench leak control matrix — n=5 Lite",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**coding-agent diagnostic (Modal, small-N)**. Not SOTA. Not a natural "
        "contamination base rate. Primary gate = synthetic `LEAK_MARKER`; "
        "gold-line overlap is a secondary noisy diagnostic.",
        "",
        "## Arms",
        "",
        "| arm | setup | primary gate |",
        "|---|---|---|",
        "| A0 | clean export, no carrier | synthetic FP (must be low) |",
        "| A1 | leak carrier, no force-retrieve | induction without prompting |",
        "| A2 | leak + force-retrieve | sensitivity (target ≥ 0.80) |",
        "",
        f"Pre-registered gates: A0 synthetic flag rate < {A0_FP_GATE:.2f}; "
        f"A2 synthetic flag rate ≥ {A2_SENS_TARGET:.2f}.",
        "",
        "## Results",
        "",
        "| arm | resolved | synth flagged | synth rate | gold overlap | gold rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in ("A0", "A1", "A2"):
        s = by.get(arm)
        if s is None:
            lines.append(f"| {arm} | — | — | — | — | — |")
            continue
        lines.append(
            f"| {arm} ({s.label}) | {s.n_resolved}/{s.n_preds} | "
            f"{s.synthetic_flagged} | {s.synthetic_flag_rate:.2f} | "
            f"{s.gold_overlap} | {s.gold_overlap_rate:.2f} |"
        )
    lines.extend(["", "## Acceptance", ""])
    if a0 is None:
        lines.append("- A0 FP gate: PENDING (arm not summarized)")
    else:
        lines.append(
            f"- A0 synthetic FP < {A0_FP_GATE:.2f}: "
            f"{'PASS' if a0_pass else 'FAIL'} ({a0.synthetic_flag_rate:.2f})"
        )
        lines.append(
            f"- A0 gold-line overlap (secondary): {a0.gold_overlap_rate:.2f}"
            + (
                " — noisy; do not use gold-line for specificity gate"
                if gold_noisy
                else " — below gate; gold-line still usable as soft signal"
            )
        )
    if a2 is None:
        lines.append("- A2 sensitivity: PENDING")
    else:
        lines.append(
            f"- A2 synthetic catch ≥ {A2_SENS_TARGET:.2f}: "
            f"{'PASS' if a2_pass else 'FAIL'} ({a2.synthetic_flag_rate:.2f})"
        )
    lines.extend(
        [
            "",
            "## Read",
            "",
        ]
    )
    if a0_pass and a2_pass:
        lines.append(
            "Specificity (synthetic) and sensitivity (force-retrieve) both hold "
            "on this n=5 slice. Proceed to B2 label hunt (timeboxed); n=20 is "
            "unblocked for sealed-vs-unsealed only if B2 fails quickly."
        )
    elif a0 is not None and not a0_pass:
        lines.append(
            "A0 FAIL: synthetic marker appeared on the clean arm — unexpected; "
            "investigate before any larger spend."
        )
    elif a0_pass and a2 is not None and not a2_pass:
        lines.append(
            "A0 PASS but A2 sensitivity below target under the synthetic gate. "
            "Force-retrieve may not be copying the LEAK_MARKER comment; inspect "
            "patches before scaling."
        )
    else:
        lines.append("Incomplete matrix — finish pending arms before gating.")
    if gold_noisy and a0_pass:
        lines.append(
            "Gold-line overlap on A0 is high (as expected when the correct fix "
            "converges). Per user lock, specificity gates on synthetic only."
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Matrix root: `{out}`",
        ]
    )
    for s in summaries:
        lines.append(f"- {s.arm} probe: `{s.probe_path}`")
    lines.append("")
    text = "\n".join(lines)
    (out / "CONTROL_MATRIX.md").write_text(text)
    if docs is not None:
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(text)
    return text


def cmd_summarize(args: argparse.Namespace) -> int:
    out = Path(args.out)
    dirs = _arm_dirs(out)
    summaries: list[ArmSummary] = []
    for arm, path in dirs.items():
        s = summarize_arm(arm, path)
        if s is not None:
            summaries.append(s)
            print(
                f"{arm}: resolved={s.n_resolved}/{s.n_preds} "
                f"synth_flag={s.synthetic_flag_rate:.2f} "
                f"gold={s.gold_overlap_rate:.2f}"
            )
        else:
            print(f"{arm}: no modal predictions yet under {path / 'modal'}")
    docs = Path(args.docs) if args.docs else None
    report = _write_report(out, summaries, docs)
    print(report)
    return 0


def cmd_launch_arm(args: argparse.Namespace) -> int:
    """Launch Modal generation + official grade for one arm (spends credits)."""

    out = Path(args.out)
    arm: ArmId = args.arm
    arm_dir = _arm_dirs(out)[arm]
    instances = arm_dir / "instances.jsonl"
    if not instances.exists():
        raise SystemExit(f"missing {instances}; run prepare first")
    modal_out = arm_dir / "modal"
    run_id = f"lbah-leak-ctrl-{arm.lower()}-{int(time.time())}"
    gen_cmd = [
        "python3.11",
        "-m",
        "modal",
        "run",
        "scripts/modal_lbah_swebench_generate.py",
        "--instances",
        str(instances),
        "--model-agent",
        args.model_agent,
        "--out",
        str(modal_out),
        "--official-dataset",
        args.dataset,
        "--run-id",
        run_id,
        "--limit",
        str(args.limit),
        "--max-steps",
        str(args.max_steps),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--max-workers",
        str(args.max_workers),
    ]
    env_prefix: list[str] = []
    if args.doppler:
        env_prefix = [
            "doppler",
            "run",
            "--project",
            args.doppler_project,
            "--config",
            args.doppler_config,
            "--",
            "env",
            "LBAH_MODAL_GPU=L4",
            f"LBAH_MODAL_MAX_CONTAINERS={args.max_workers}",
        ]
    print(" ".join(env_prefix + gen_cmd))
    if args.dry_run:
        return 0
    gen = subprocess.run(env_prefix + gen_cmd, cwd=ROOT, check=False)
    if gen.returncode != 0:
        return gen.returncode

    subset = modal_out / "official" / "subsets" / f"n{args.limit}.json"
    if not subset.exists():
        # generator writes n1 per worker then aggregates; fall back to command json
        subset = modal_out / "official" / "run_evaluation_command.json"
    markers = arm_dir / "contamination_markers.jsonl"
    grade_cmd = [
        "python3.11",
        "scripts/run_official_swebench.py",
        str(subset),
        "--target",
        "modal",
        "--max-workers",
        str(args.max_workers),
        "--run-id",
        f"{run_id}-official",
        "--enable-contamination-probe",
        "--contamination-markers",
        str(markers),
        "--contamination-artifact-dir",
        str(modal_out / "official"),
        "--contamination-out",
        str(modal_out / "contamination_probe.jsonl"),
    ]
    if args.doppler:
        grade_cmd[1:1] = []  # keep path; wrap whole command
        grade_wrapped = [
            "doppler",
            "run",
            "--project",
            args.doppler_project,
            "--config",
            args.doppler_config,
            "--",
            *grade_cmd,
            "--doppler",
            "--doppler-project",
            args.doppler_project,
            "--doppler-config",
            args.doppler_config,
        ]
    else:
        grade_wrapped = grade_cmd
    print(" ".join(grade_wrapped))
    grade = subprocess.run(grade_wrapped, cwd=ROOT, check=False)
    # Move cwd official report into artifact dir if present.
    for cand in Path.cwd().glob(f"*{run_id}*official*.json"):
        dest = modal_out / "official" / "official-report.json"
        shutil.move(str(cand), dest)
        print(f"moved report → {dest}")
    shutil.copy(markers, modal_out / "official" / "contamination_markers.jsonl")
    summarize_arm(arm, arm_dir)
    return grade.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p_prep = sp.add_parser("prepare", help="Write A0/A1/A2 instance + marker dirs")
    p_prep.add_argument("--instances", required=True)
    p_prep.add_argument("--out", required=True)
    p_prep.add_argument("--limit", type=int, default=5)
    p_prep.add_argument("--offset", type=int, default=0)
    p_prep.add_argument(
        "--reuse-a2-modal",
        default=None,
        help="Copy an existing A2 modal run dir (e.g. runs/swebench_lite_n5_leaked_force_modal)",
    )
    p_prep.set_defaults(func=cmd_prepare)

    p_sum = sp.add_parser("summarize", help="Probe + write comparison markdown")
    p_sum.add_argument("--out", required=True)
    p_sum.add_argument("--docs", default="docs/results/SWEBENCH_LEAK_CONTROL_N5.md")
    p_sum.set_defaults(func=cmd_summarize)

    p_launch = sp.add_parser("launch-arm", help="Modal gen+grade one arm (credits)")
    p_launch.add_argument("--out", required=True)
    p_launch.add_argument("--arm", choices=["A0", "A1", "A2"], required=True)
    p_launch.add_argument("--model-agent", default="configs/provider_big.yaml")
    p_launch.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    p_launch.add_argument("--limit", type=int, default=5)
    p_launch.add_argument("--max-steps", type=int, default=20)
    p_launch.add_argument("--timeout-seconds", type=float, default=120.0)
    p_launch.add_argument("--max-workers", type=int, default=20)
    p_launch.add_argument("--doppler", action="store_true")
    p_launch.add_argument("--doppler-project", default="cofounder")
    p_launch.add_argument("--doppler-config", default="dev")
    p_launch.add_argument("--dry-run", action="store_true")
    p_launch.set_defaults(func=cmd_launch_arm)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
