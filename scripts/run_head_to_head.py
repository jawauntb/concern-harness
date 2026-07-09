#!/usr/bin/env python
"""Head-to-head: raw vs LBAH vs gated vs sealed on SWE-bench Lite.

Claim level: **coding-agent diagnostic**. Isolates harness-surface effects on
``provider_big`` / Opus 4.8. Not SOTA. Not a leaderboard claim.

Arms (same instance IDs, model, max_steps, timeout):

* **raw** — unsealed checkout; raw coding prompt (no ledger coaching)
* **lbah** — unsealed; LBAH coding prompt + certificates (default Modal path)
* **gated** — leak+force-retrieve instances; contamination gate blocks finish
  when the synthetic ``LEAK_MARKER`` is in the commitment
* **sealed** — Cursor-style seal (single-commit ``.git`` + block remote shells)

Reuse: if ``--reuse-sealed-unsealed`` points at a prior sealed/unsealed run,
``lbah`` ← unsealed and ``sealed`` ← sealed artifacts (same n=20 slice).

Usage:
  python3.11 scripts/run_head_to_head.py prepare \\
      --instances runs/swebench_lite_n20/instances.jsonl \\
      --out runs/head_to_head_n20 --limit 20

  python3.11 scripts/run_head_to_head.py launch \\
      --out runs/head_to_head_n20 --arm raw --doppler --limit 20

  python3.11 scripts/run_head_to_head.py summarize \\
      --out runs/head_to_head_n20 \\
      --docs docs/results/SWEBENCH_HEAD_TO_HEAD.md
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ArmId = Literal["raw", "lbah", "gated", "sealed"]
ARMS: tuple[ArmId, ...] = ("raw", "lbah", "gated", "sealed")


def _arm_dir(out: Path, arm: ArmId) -> Path:
    return out / arm


def _arm_config(arm: ArmId) -> dict[str, Any]:
    return {
        "raw": {
            "coding_prompt": "raw",
            "seal_git_history": False,
            "allow_git_history": True,
            "contamination_gate": False,
            "use_leak_instances": False,
            "force_retrieve": False,
        },
        "lbah": {
            "coding_prompt": "lbah",
            "seal_git_history": False,
            "allow_git_history": True,
            "contamination_gate": False,
            "use_leak_instances": False,
            "force_retrieve": False,
        },
        "gated": {
            "coding_prompt": "lbah",
            "seal_git_history": False,
            "allow_git_history": True,
            "contamination_gate": True,
            "use_leak_instances": True,
            "force_retrieve": True,
        },
        "sealed": {
            "coding_prompt": "lbah",
            "seal_git_history": True,
            "allow_git_history": False,
            "contamination_gate": False,
            "use_leak_instances": False,
            "force_retrieve": False,
        },
    }[arm]


def cmd_prepare(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    src = Path(args.instances)
    rows = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
    if args.limit is not None:
        rows = rows[: args.limit]

    clean_path = out / "instances_clean.jsonl"
    clean_path.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""))

    leak_dir = out / "instances_gated"
    inject_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "inject_swebench_leaks.py"),
        "--instances",
        str(clean_path),
        "--force-retrieve",
        "--out",
        str(leak_dir),
    ]
    print(" ".join(inject_cmd))
    if not args.dry_run:
        inj = subprocess.run(inject_cmd, cwd=ROOT, check=False)
        if inj.returncode != 0:
            return inj.returncode
    leak_instances = leak_dir / "instances.jsonl"
    markers = leak_dir / "contamination_markers.jsonl"

    for arm in ARMS:
        cfg = _arm_config(arm)
        d = _arm_dir(out, arm)
        d.mkdir(parents=True, exist_ok=True)
        src_inst = leak_instances if cfg["use_leak_instances"] else clean_path
        if src_inst.exists():
            shutil.copy(src_inst, d / "instances.jsonl")
        (d / "arm.json").write_text(
            json.dumps(
                {
                    "arm": arm,
                    "n": len(rows),
                    "model_agent": "configs/provider_big.yaml",
                    "claim_level": "coding-agent diagnostic (head-to-head)",
                    **cfg,
                    "markers": str(markers) if cfg["use_leak_instances"] else "",
                },
                indent=2,
            )
            + "\n"
        )
    print(f"prepared {len(rows)} instances × {len(ARMS)} arms under {out}")
    return 0


def _find_report(modal_dir: Path) -> Path | None:
    official = modal_dir / "official"
    for candidate in [official / "official-report.json", *sorted(official.glob("*.json"))]:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(payload, dict) and "resolved_ids" in payload:
            return candidate
    return None


def _arm_stats(arm_dir: Path) -> dict[str, Any] | None:
    modal = arm_dir / "modal"
    official = modal / "official"
    preds_path = official / "predictions.jsonl"
    if not preds_path.exists():
        return None
    preds = [json.loads(l) for l in preds_path.read_text().splitlines() if l.strip()]
    report_path = _find_report(modal)
    resolved: list[str] = []
    unresolved: list[str] = []
    empty: list[str] = []
    errors: list[str] = []
    if report_path is not None:
        if report_path.parent != official:
            shutil.copy(report_path, official / "official-report.json")
            report_path = official / "official-report.json"
        report = json.loads(report_path.read_text())
        resolved = [str(x) for x in report.get("resolved_ids") or []]
        unresolved = [str(x) for x in report.get("unresolved_ids") or []]
        empty = [str(x) for x in report.get("empty_patch_ids") or []]
        errors = [str(x) for x in report.get("error_ids") or []]
    n = len(preds)
    n_res = len(resolved)
    load_scores: list[float] = []
    runs_path = modal / "runs.jsonl"
    if runs_path.exists():
        for line in runs_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            cr = row.get("coding_result") or {}
            if isinstance(cr, dict) and "load_score" in cr:
                load_scores.append(float(cr["load_score"]))
    probe_path = official / "contamination_probe.jsonl"
    synth_flag = 0
    if probe_path.exists():
        for line in probe_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("resolved") and row.get("flagged"):
                synth_flag += 1
    return {
        "n_preds": n,
        "n_resolved": n_res,
        "resolve_rate": n_res / max(1, n),
        "resolved_ids": resolved,
        "unresolved_ids": unresolved,
        "empty_patch_ids": empty,
        "error_ids": errors,
        "report_path": str(report_path) if report_path else "",
        "mean_load_score": (sum(load_scores) / len(load_scores)) if load_scores else None,
        "synth_flagged_resolved": synth_flag,
        "synth_flag_rate": synth_flag / max(1, n_res),
    }


def cmd_reuse(args: argparse.Namespace) -> int:
    """Copy sealed/unsealed Modal artifacts into lbah/sealed arms."""

    out = Path(args.out)
    src = Path(args.reuse_sealed_unsealed)
    mapping = {
        "lbah": src / "unsealed" / "modal",
        "sealed": src / "sealed" / "modal",
    }
    for arm, modal_src in mapping.items():
        if not modal_src.exists():
            print(f"skip {arm}: missing {modal_src}")
            continue
        dest = _arm_dir(out, arm) / "modal"  # type: ignore[arg-type]
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(modal_src, dest)
        print(f"reused {modal_src} → {dest}")
    return 0


def cmd_summarize(args: argparse.Namespace) -> int:
    out = Path(args.out)
    stats: dict[str, dict[str, Any]] = {}
    for arm in ARMS:
        s = _arm_stats(_arm_dir(out, arm))
        if s is None:
            print(f"{arm}: no predictions yet")
            continue
        stats[arm] = s
        print(
            f"{arm}: resolved={s['n_resolved']}/{s['n_preds']} "
            f"rate={s['resolve_rate']:.2f}"
        )

    lines = [
        "# SWE-bench head-to-head — raw / LBAH / gated / sealed",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**coding-agent diagnostic (head-to-head)**. Not SOTA. Goal is to "
        "isolate raw vs LBAH vs gated vs sealed effects on Lite with "
        "`provider_big` (Opus 4.8), not optimize leaderboard performance.",
        "",
        "## Arms",
        "",
        "| arm | surface |",
        "|---|---|",
        "| raw | unsealed; raw coding prompt (no ledger coaching) |",
        "| lbah | unsealed; LBAH coding prompt + certificates |",
        "| gated | leak+force-retrieve; block finish on synthetic marker |",
        "| sealed | single-commit `.git` + block remote shells |",
        "",
        "## Results",
        "",
        "| arm | submitted | resolved | resolve rate | empty | errors | synth flag/res |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        st = stats.get(arm)
        if not st:
            lines.append(f"| {arm} | — | — | — | — | — | — |")
            continue
        flag = (
            f"{st['synth_flagged_resolved']}/{st['n_resolved']}"
            if arm == "gated"
            else "—"
        )
        lines.append(
            f"| {arm} | {st['n_preds']} | {st['n_resolved']} | "
            f"{st['resolve_rate']:.2f} | {len(st['empty_patch_ids'])} | "
            f"{len(st['error_ids'])} | {flag} |"
        )

    raw = stats.get("raw")
    lbah = stats.get("lbah")
    gated = stats.get("gated")
    sealed = stats.get("sealed")
    lines.extend(["", "## Read", ""])
    if not all(stats.get(a) for a in ARMS):
        lines.append("Incomplete — finish all arms before interpreting.")
    else:
        assert raw and lbah and gated and sealed
        d_lbah = lbah["resolve_rate"] - raw["resolve_rate"]
        d_seal = sealed["resolve_rate"] - lbah["resolve_rate"]
        d_gate = gated["resolve_rate"] - lbah["resolve_rate"]
        lines.append(
            f"Δ resolve (lbah − raw) = {d_lbah:+.2f}; "
            f"(sealed − lbah) = {d_seal:+.2f}; "
            f"(gated − lbah) = {d_gate:+.2f}."
        )
        lines.append("")
        if abs(d_lbah) < 0.05 and abs(d_seal) < 0.05:
            lines.append(
                "Resolve rates are similar across raw/LBAH/sealed — consistent "
                "with `EVIDENCE.md`: deploy LBAH for audit/irreversible actions, "
                "not leaderboard lift. Gated arm measures overblock under "
                "induced contamination, not natural base rate."
            )
        else:
            lines.append(
                "Resolve gaps exist on this slice; interpret as harness-surface "
                "effects only. Still not SOTA and not Cursor's Pro sealed drop."
            )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- `{out}`",
        ]
    )
    for arm, st in stats.items():
        if st.get("report_path"):
            lines.append(f"- {arm} report: `{st['report_path']}`")
    lines.append("")
    text = "\n".join(lines)
    (out / "HEAD_TO_HEAD.md").write_text(text)
    if args.docs:
        docs = Path(args.docs)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(text)
    print(text)
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    out = Path(args.out)
    arm: ArmId = args.arm
    cfg = _arm_config(arm)
    arm_dir = _arm_dir(out, arm)
    instances = arm_dir / "instances.jsonl"
    if not instances.exists():
        raise SystemExit(f"missing {instances}; run prepare first")
    modal_out = arm_dir / "modal"
    run_id = f"lbah-h2h-{arm}-{int(time.time())}"
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
        "--coding-prompt",
        cfg["coding_prompt"],
    ]
    if cfg["seal_git_history"]:
        gen_cmd.append("--seal-git-history")
    elif cfg["allow_git_history"]:
        gen_cmd.append("--allow-git-history")
    if cfg["contamination_gate"]:
        gen_cmd.append("--contamination-gate")
    if args.capture_io:
        gen_cmd.append("--capture-io")

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
            f"LBAH_MODAL_GPU={args.gpu}",
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
        subset = modal_out / "official" / "run_evaluation_command.json"
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
        "--contamination-artifact-dir",
        str(modal_out / "official"),
    ]
    markers = arm_dir / "arm.json"
    arm_meta = json.loads(markers.read_text()) if markers.exists() else {}
    marker_path = arm_meta.get("markers") or ""
    if cfg["use_leak_instances"] and marker_path and Path(marker_path).exists():
        grade_cmd.extend(
            [
                "--enable-contamination-probe",
                "--contamination-markers",
                str(marker_path),
            ]
        )
    if args.doppler:
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
    for cand in Path.cwd().glob(f"*{run_id}*official*.json"):
        dest = modal_out / "official" / "official-report.json"
        shutil.move(str(cand), dest)
        print(f"moved report → {dest}")
    return grade.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("prepare")
    p.add_argument("--instances", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_prepare)

    r = sp.add_parser("reuse")
    r.add_argument("--out", required=True)
    r.add_argument("--reuse-sealed-unsealed", required=True)
    r.set_defaults(func=cmd_reuse)

    s = sp.add_parser("summarize")
    s.add_argument("--out", required=True)
    s.add_argument("--docs", default="docs/results/SWEBENCH_HEAD_TO_HEAD.md")
    s.set_defaults(func=cmd_summarize)

    l = sp.add_parser("launch")
    l.add_argument("--out", required=True)
    l.add_argument("--arm", choices=list(ARMS), required=True)
    l.add_argument("--model-agent", default="configs/provider_big.yaml")
    l.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    l.add_argument("--limit", type=int, default=20)
    l.add_argument("--max-steps", type=int, default=20)
    l.add_argument("--timeout-seconds", type=float, default=120.0)
    l.add_argument("--max-workers", type=int, default=40)
    l.add_argument("--gpu", default="L4")
    l.add_argument("--capture-io", action="store_true")
    l.add_argument("--doppler", action="store_true")
    l.add_argument("--doppler-project", default="cofounder")
    l.add_argument("--doppler-config", default="dev")
    l.add_argument("--dry-run", action="store_true")
    l.set_defaults(func=cmd_launch)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
