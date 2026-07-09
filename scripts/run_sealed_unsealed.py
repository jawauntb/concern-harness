#!/usr/bin/env python
"""Sealed vs unsealed SWE-bench Lite diagnostic (paper §4.4 fall-back for c).

Claim level: **coding-agent diagnostic (sealed/unsealed)** — not Cursor's
natural 63% base rate, not SOTA.

* **unsealed**: full clone history kept; ``.git`` readable; remote shells allowed
* **sealed**: after checkout, wipe ``.git`` → single commit; block curl/wget/
  ``git clone|fetch|pull`` (Cursor 2026-06-25 style, best-effort)

Usage:
  python3.11 scripts/run_sealed_unsealed.py prepare \\
      --instances runs/swebench_lite_n20/instances.jsonl \\
      --out runs/sealed_unsealed_n20

  python3.11 scripts/run_sealed_unsealed.py launch \\
      --out runs/sealed_unsealed_n20 --arm unsealed --doppler --limit 20

  python3.11 scripts/run_sealed_unsealed.py launch \\
      --out runs/sealed_unsealed_n20 --arm sealed --doppler --limit 20

  python3.11 scripts/run_sealed_unsealed.py summarize \\
      --out runs/sealed_unsealed_n20 \\
      --docs docs/results/SWEBENCH_SEALED_UNSEALED_N20.md
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

ArmId = Literal["unsealed", "sealed"]


def _arm_dir(out: Path, arm: ArmId) -> Path:
    return out / arm


def cmd_prepare(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    src = Path(args.instances)
    rows = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
    if args.limit is not None:
        rows = rows[: args.limit]
    for arm in ("unsealed", "sealed"):
        d = _arm_dir(out, arm)  # type: ignore[arg-type]
        d.mkdir(parents=True, exist_ok=True)
        (d / "instances.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")
        )
        (d / "arm.json").write_text(
            json.dumps(
                {
                    "arm": arm,
                    "n": len(rows),
                    "seal_git_history": arm == "sealed",
                    "allow_git_history": arm == "unsealed",
                    "model_agent": "configs/provider_big.yaml",
                    "claim_level": "coding-agent diagnostic (sealed/unsealed)",
                },
                indent=2,
            )
            + "\n"
        )
    print(f"prepared {len(rows)} instances × 2 arms under {out}")
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
    return {
        "n_preds": n,
        "n_resolved": n_res,
        "resolve_rate": n_res / max(1, n),
        "resolved_ids": resolved,
        "unresolved_ids": unresolved,
        "empty_patch_ids": empty,
        "error_ids": errors,
        "report_path": str(report_path) if report_path else "",
        "nonempty_patches": sum(1 for p in preds if (p.get("model_patch") or "").strip()),
    }


def cmd_summarize(args: argparse.Namespace) -> int:
    out = Path(args.out)
    stats: dict[str, dict[str, Any]] = {}
    for arm in ("unsealed", "sealed"):
        s = _arm_stats(_arm_dir(out, arm))  # type: ignore[arg-type]
        if s is None:
            print(f"{arm}: no predictions yet")
            continue
        stats[arm] = s
        print(
            f"{arm}: resolved={s['n_resolved']}/{s['n_preds']} "
            f"rate={s['resolve_rate']:.2f}"
        )

    u = stats.get("unsealed")
    s = stats.get("sealed")
    delta = None
    if u and s:
        delta = u["resolve_rate"] - s["resolve_rate"]

    lines = [
        "# SWE-bench sealed vs unsealed — Lite n=20",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**coding-agent diagnostic (sealed/unsealed)**. Not SOTA. Not Cursor's "
        "natural 63% retrieved base rate — this is a harness-surface contrast "
        "on Lite with `provider_big` (Opus 4.8).",
        "",
        "## Method",
        "",
        "* **unsealed:** full git clone history retained; `.git` readable; remote "
        "shells allowed.",
        "* **sealed:** after checkout + test_patch, wipe `.git` and reinit as a "
        "single commit; block curl/wget/`git clone|fetch|pull` in "
        "`CodingWorkspace.run_command` (best-effort; not a full network proxy).",
        "* Same instances, model, max_steps, timeout. Official Modal grading.",
        "",
        "## Results",
        "",
        "| arm | submitted | resolved | resolve rate | empty | errors |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in ("unsealed", "sealed"):
        st = stats.get(arm)
        if not st:
            lines.append(f"| {arm} | — | — | — | — | — |")
            continue
        lines.append(
            f"| {arm} | {st['n_preds']} | {st['n_resolved']} | "
            f"{st['resolve_rate']:.2f} | {len(st['empty_patch_ids'])} | "
            f"{len(st['error_ids'])} |"
        )
    if delta is not None:
        lines.extend(
            [
                "",
                f"**Δ resolve (unsealed − sealed):** {delta:+.2f}",
                "",
            ]
        )
    lines.extend(["## Read", ""])
    if delta is None:
        lines.append("Incomplete — finish both arms before interpreting.")
    elif delta > 0.05:
        lines.append(
            "Unsealed resolve% is higher — consistent with a history/network "
            "surface helping some solves. Still not a natural-contamination "
            "base rate; no per-action retrieve labels."
        )
    elif delta < -0.05:
        lines.append(
            "Sealed resolve% is higher — unexpected under the Cursor story; "
            "inspect empty/error ids and whether seal broke checkout tooling."
        )
    else:
        lines.append(
            "Resolve rates are similar — on this Lite n=20 slice the "
            "history/network surface did not move the needle much (small-N; "
            "Lite may be less retrieve-prone than Pro)."
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
    (out / "SEALED_UNSEALED.md").write_text(text)
    if args.docs:
        docs = Path(args.docs)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(text)
    print(text)
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    out = Path(args.out)
    arm: ArmId = args.arm
    arm_dir = _arm_dir(out, arm)
    instances = arm_dir / "instances.jsonl"
    if not instances.exists():
        raise SystemExit(f"missing {instances}; run prepare first")
    modal_out = arm_dir / "modal"
    run_id = f"lbah-seal-{arm}-{int(time.time())}"
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
    if arm == "sealed":
        gen_cmd.append("--seal-git-history")
    else:
        gen_cmd.append("--allow-git-history")

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
    p.set_defaults(func=cmd_prepare)

    s = sp.add_parser("summarize")
    s.add_argument("--out", required=True)
    s.add_argument("--docs", default="docs/results/SWEBENCH_SEALED_UNSEALED_N20.md")
    s.set_defaults(func=cmd_summarize)

    l = sp.add_parser("launch")
    l.add_argument("--out", required=True)
    l.add_argument("--arm", choices=["unsealed", "sealed"], required=True)
    l.add_argument("--model-agent", default="configs/provider_big.yaml")
    l.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    l.add_argument("--limit", type=int, default=20)
    l.add_argument("--max-steps", type=int, default=20)
    l.add_argument("--timeout-seconds", type=float, default=120.0)
    l.add_argument("--max-workers", type=int, default=40)
    l.add_argument("--gpu", default="L4")
    l.add_argument("--doppler", action="store_true")
    l.add_argument("--doppler-project", default="cofounder")
    l.add_argument("--doppler-config", default="dev")
    l.add_argument("--dry-run", action="store_true")
    l.set_defaults(func=cmd_launch)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
