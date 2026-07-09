#!/usr/bin/env python
"""Wrap external solvers (Claude, OpenRouter) with LBAH certs / contamination gate.

Plan (a): keep a strong model as the *solver*; LBAH owns certificates and the
optional finish-time contamination gate. Not SOTA. Isolates wrap effects.

Solvers:
  * claude     — Anthropic ``provider_llm`` / Opus 4.8 (``configs/claude_opus_4_8.yaml``)
  * openrouter — OpenAI-compatible OpenRouter Opus 4.8
                 (``configs/openrouter_opus_4_8.yaml``)

Wrap modes:
  * raw   — raw coding prompt, no gate
  * certs — LBAH coding prompt + certificates, no gate
  * gate  — leak+force-retrieve instances; block finish on synthetic marker

Reuse: ``--reuse-head-to-head`` copies prior Claude raw/lbah/gated Modal
artifacts into claude/{raw,certs,gate} so we only burn OpenRouter credits
for the new solver.

Usage:
  python3.11 scripts/run_wrap_matrix.py prepare \\
      --instances runs/swebench_lite_n20/instances.jsonl \\
      --out runs/wrap_matrix_n20 --limit 20

  python3.11 scripts/run_wrap_matrix.py reuse \\
      --out runs/wrap_matrix_n20 \\
      --reuse-head-to-head runs/head_to_head_n20

  python3.11 scripts/run_wrap_matrix.py launch \\
      --out runs/wrap_matrix_n20 --solver openrouter --wrap raw --doppler

  python3.11 scripts/run_wrap_matrix.py summarize \\
      --out runs/wrap_matrix_n20 \\
      --docs docs/results/SWEBENCH_WRAP_MATRIX.md
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

SolverId = Literal["claude", "openrouter"]
WrapId = Literal["raw", "certs", "gate"]
SOLVERS: tuple[SolverId, ...] = ("claude", "openrouter")
WRAPS: tuple[WrapId, ...] = ("raw", "certs", "gate")

SOLVER_MODELS: dict[SolverId, str] = {
    "claude": "configs/claude_opus_4_8.yaml",
    "openrouter": "configs/openrouter_opus_4_8.yaml",
}


def _cell_dir(out: Path, solver: SolverId, wrap: WrapId) -> Path:
    return out / solver / wrap


def _wrap_config(wrap: WrapId) -> dict[str, Any]:
    return {
        "raw": {
            "coding_prompt": "raw",
            "contamination_gate": False,
            "use_leak_instances": False,
            "allow_git_history": True,
        },
        "certs": {
            "coding_prompt": "lbah",
            "contamination_gate": False,
            "use_leak_instances": False,
            "allow_git_history": True,
        },
        "gate": {
            "coding_prompt": "lbah",
            "contamination_gate": True,
            "use_leak_instances": True,
            "allow_git_history": True,
        },
    }[wrap]


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

    for solver in SOLVERS:
        for wrap in WRAPS:
            cfg = _wrap_config(wrap)
            d = _cell_dir(out, solver, wrap)
            d.mkdir(parents=True, exist_ok=True)
            src_inst = leak_instances if cfg["use_leak_instances"] else clean_path
            if src_inst.exists():
                shutil.copy(src_inst, d / "instances.jsonl")
            (d / "cell.json").write_text(
                json.dumps(
                    {
                        "solver": solver,
                        "wrap": wrap,
                        "n": len(rows),
                        "model_agent": SOLVER_MODELS[solver],
                        "claim_level": "coding-agent diagnostic (wrap matrix)",
                        **cfg,
                        "markers": str(markers) if cfg["use_leak_instances"] else "",
                    },
                    indent=2,
                )
                + "\n"
            )
    print(f"prepared {len(rows)} instances × {len(SOLVERS)} solvers × {len(WRAPS)} wraps")
    return 0


def cmd_reuse(args: argparse.Namespace) -> int:
    """Map prior Claude head-to-head arms → wrap-matrix claude cells."""

    out = Path(args.out)
    src = Path(args.reuse_head_to_head)
    mapping = {
        ("claude", "raw"): src / "raw" / "modal",
        ("claude", "certs"): src / "lbah" / "modal",
        ("claude", "gate"): src / "gated" / "modal",
    }
    for (solver, wrap), modal_src in mapping.items():
        if not modal_src.exists():
            print(f"skip {solver}/{wrap}: missing {modal_src}")
            continue
        dest = _cell_dir(out, solver, wrap) / "modal"  # type: ignore[arg-type]
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(modal_src, dest)
        print(f"reused {modal_src} → {dest}")
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


def _cell_stats(cell_dir: Path) -> dict[str, Any] | None:
    modal = cell_dir / "modal"
    official = modal / "official"
    preds_path = official / "predictions.jsonl"
    if not preds_path.exists():
        return None
    preds = [json.loads(l) for l in preds_path.read_text().splitlines() if l.strip()]
    report_path = _find_report(modal)
    resolved: list[str] = []
    empty: list[str] = []
    errors: list[str] = []
    if report_path is not None:
        if report_path.parent != official:
            shutil.copy(report_path, official / "official-report.json")
            report_path = official / "official-report.json"
        report = json.loads(report_path.read_text())
        resolved = [str(x) for x in report.get("resolved_ids") or []]
        empty = [str(x) for x in report.get("empty_patch_ids") or []]
        errors = [str(x) for x in report.get("error_ids") or []]
    n = len(preds)
    n_res = len(resolved)
    probe_path = official / "contamination_probe.jsonl"
    synth_flag = 0
    if probe_path.exists():
        for line in probe_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("resolved") and row.get("flagged"):
                synth_flag += 1
    gate_msgs = 0
    gen_path = modal / "modal_generation_results.json"
    if gen_path.exists():
        for row in json.loads(gen_path.read_text()):
            blob = "\n".join(
                [
                    str(row.get("stdout") or ""),
                    str(row.get("stderr") or ""),
                    str(row.get("run") or ""),
                ]
            )
            if "contamination gate" in blob:
                gate_msgs += 1
    marker_in = sum(1 for p in preds if "LEAK_MARKER:" in (p.get("model_patch") or ""))
    return {
        "n_preds": n,
        "n_resolved": n_res,
        "resolve_rate": n_res / max(1, n),
        "resolved_ids": resolved,
        "empty_patch_ids": empty,
        "error_ids": errors,
        "report_path": str(report_path) if report_path else "",
        "synth_flagged_resolved": synth_flag,
        "gate_messages": gate_msgs,
        "preds_with_leak_marker": marker_in,
    }


def cmd_summarize(args: argparse.Namespace) -> int:
    out = Path(args.out)
    stats: dict[tuple[str, str], dict[str, Any]] = {}
    for solver in SOLVERS:
        for wrap in WRAPS:
            s = _cell_stats(_cell_dir(out, solver, wrap))
            key = (solver, wrap)
            if s is None:
                print(f"{solver}/{wrap}: no predictions yet")
                continue
            stats[key] = s
            print(
                f"{solver}/{wrap}: resolved={s['n_resolved']}/{s['n_preds']} "
                f"rate={s['resolve_rate']:.2f}"
            )

    lines = [
        "# SWE-bench wrap matrix — Claude / OpenRouter × raw / certs / gate",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**coding-agent diagnostic (wrap matrix)**. Not SOTA. Plan (a): "
        "external/model solvers propose; LBAH owns certificates and the "
        "optional contamination finish gate.",
        "",
        "## Cells",
        "",
        "| solver | wrap | surface |",
        "|---|---|---|",
        "| claude | raw | Anthropic Opus 4.8; raw coding prompt |",
        "| claude | certs | same model; LBAH prompt + certificates |",
        "| claude | gate | leak+force-retrieve; finish gate on synthetic marker |",
        "| openrouter | raw | OpenRouter `anthropic/claude-opus-4.8`; raw prompt |",
        "| openrouter | certs | same; LBAH prompt + certificates |",
        "| openrouter | gate | leak+force; finish gate |",
        "",
        "## Results",
        "",
        "| solver | wrap | submitted | resolved | rate | empty | gate msgs | residual marker |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for solver in SOLVERS:
        for wrap in WRAPS:
            st = stats.get((solver, wrap))
            if not st:
                lines.append(f"| {solver} | {wrap} | — | — | — | — | — | — |")
                continue
            lines.append(
                f"| {solver} | {wrap} | {st['n_preds']} | {st['n_resolved']} | "
                f"{st['resolve_rate']:.2f} | {len(st['empty_patch_ids'])} | "
                f"{st['gate_messages']} | {st['preds_with_leak_marker']} |"
            )

    lines.extend(["", "## Read", ""])
    if len(stats) < len(SOLVERS) * len(WRAPS):
        lines.append("Incomplete — finish all cells before interpreting.")
    else:
        lines.append(
            "Pre-registered: resolve% may tie or drop under certs/gate; win = "
            "certificates on solves + gate engage under induction, not beating "
            "unwrapped resolve%. Cross-solver: Claude vs OpenRouter should be "
            "near-ties if both are Opus 4.8 — transport differences are the "
            "interesting residual."
        )
        for solver in SOLVERS:
            raw = stats[(solver, "raw")]["resolve_rate"]
            certs = stats[(solver, "certs")]["resolve_rate"]
            lines.append(
                f"- {solver}: Δ(certs − raw) = {certs - raw:+.2f}; "
                f"gate residual markers = "
                f"{stats[(solver, 'gate')]['preds_with_leak_marker']}/"
                f"{stats[(solver, 'gate')]['n_preds']}."
            )
    lines.extend(["", "## Artifacts", "", f"- `{out}`", ""])
    for (solver, wrap), st in stats.items():
        if st.get("report_path"):
            lines.append(f"- {solver}/{wrap}: `{st['report_path']}`")
    lines.append("")
    text = "\n".join(lines)
    (out / "WRAP_MATRIX.md").write_text(text)
    if args.docs:
        docs = Path(args.docs)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(text)
    print(text)
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    out = Path(args.out)
    solver: SolverId = args.solver
    wrap: WrapId = args.wrap
    cfg = _wrap_config(wrap)
    cell = _cell_dir(out, solver, wrap)
    instances = cell / "instances.jsonl"
    if not instances.exists():
        raise SystemExit(f"missing {instances}; run prepare first")
    model_agent = args.model_agent or SOLVER_MODELS[solver]
    modal_out = cell / "modal"
    run_id = f"lbah-wrap-{solver}-{wrap}-{int(time.time())}"
    gen_cmd = [
        "python3.11",
        "-m",
        "modal",
        "run",
        "scripts/modal_lbah_swebench_generate.py",
        "--instances",
        str(instances),
        "--model-agent",
        model_agent,
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
        "--allow-git-history",
    ]
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
    cell_meta = json.loads((cell / "cell.json").read_text())
    marker_path = cell_meta.get("markers") or ""
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
    r.add_argument("--reuse-head-to-head", required=True)
    r.set_defaults(func=cmd_reuse)

    s = sp.add_parser("summarize")
    s.add_argument("--out", required=True)
    s.add_argument("--docs", default="docs/results/SWEBENCH_WRAP_MATRIX.md")
    s.set_defaults(func=cmd_summarize)

    l = sp.add_parser("launch")
    l.add_argument("--out", required=True)
    l.add_argument("--solver", choices=list(SOLVERS), required=True)
    l.add_argument("--wrap", choices=list(WRAPS), required=True)
    l.add_argument("--model-agent", default=None)
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
