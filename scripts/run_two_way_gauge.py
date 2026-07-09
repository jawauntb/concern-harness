#!/usr/bin/env python
"""Track C: two-way gauge via second-run leak perturbation on flagged cells.

Fingerprint flags are correlational. This script upgrades a subset of
force-retrieve positives to an interventional confirmation:

1. Base run: leak+force-retrieve (existing A2 / gated artifacts).
2. Perturbed run: same instances with ``LEAK_MARKER`` → ``ALT_LEAK`` in the
   carrier text (and problem statement if force-retrieve quotes it).
3. For each resolved flagged cell: ``leak_changed = (base_patch != alt_patch)``.
   Issue probe stays the marker heuristic (issue text unchanged).

Claim level: **coding-agent diagnostic (interventional subset)**. Not SOTA.

Usage:
  python3.11 scripts/run_two_way_gauge.py prepare \\
      --base-instances runs/leak_control_n5/A2_force/instances.jsonl \\
      --flagged-from runs/leak_control_n5/A2_force/modal/contamination_probe.jsonl \\
      --out runs/two_way_gauge_n5 --limit 3

  python3.11 scripts/run_two_way_gauge.py launch \\
      --out runs/two_way_gauge_n5 --doppler --limit 3

  python3.11 scripts/run_two_way_gauge.py summarize \\
      --out runs/two_way_gauge_n5 \\
      --base-predictions runs/leak_control_n5/A2_force/modal/official/predictions.jsonl \\
      --docs docs/results/SWEBENCH_TWO_WAY_GAUGE.md
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _perturb_leak_text(text: str) -> str:
    return text.replace("LEAK_MARKER:", "ALT_LEAK:")


def _perturb_instance(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    meta = dict(out.get("metadata") or {})
    contam = dict(meta.get("contamination") or {})
    for key in ("leak_text", "leak_marker", "synthetic_marker"):
        if isinstance(contam.get(key), str):
            contam[key] = _perturb_leak_text(contam[key])
    if isinstance(contam.get("issue_text"), str):
        # force-retrieve instructions may quote the marker path/content
        contam["issue_text"] = _perturb_leak_text(contam["issue_text"])
    meta["contamination"] = contam
    out["metadata"] = meta
    # problem_statement may embed force-retrieve text with the marker
    for field in ("problem_statement", "hints_text"):
        if isinstance(out.get(field), str):
            out[field] = _perturb_leak_text(out[field])
    return out


def _flagged_ids(probe_path: Path, *, limit: int | None) -> list[str]:
    ids: list[str] = []
    for line in probe_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("flagged") and row.get("resolved"):
            ids.append(str(row["instance_id"]))
    if limit is not None:
        ids = ids[:limit]
    return ids


def cmd_prepare(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base_rows = {
        json.loads(l)["instance_id"]: json.loads(l)
        for l in Path(args.base_instances).read_text().splitlines()
        if l.strip()
    }
    ids = _flagged_ids(Path(args.flagged_from), limit=args.limit)
    if not ids:
        raise SystemExit("no flagged resolved cells to perturb")
    selected = []
    perturbed = []
    for iid in ids:
        if iid not in base_rows:
            print(f"skip missing base instance {iid}")
            continue
        selected.append(base_rows[iid])
        perturbed.append(_perturb_instance(base_rows[iid]))
    (out / "base_instances.jsonl").write_text(
        "\n".join(json.dumps(r) for r in selected) + ("\n" if selected else "")
    )
    (out / "perturbed_instances.jsonl").write_text(
        "\n".join(json.dumps(r) for r in perturbed) + ("\n" if perturbed else "")
    )
    (out / "selection.json").write_text(
        json.dumps(
            {
                "instance_ids": [r["instance_id"] for r in selected],
                "n": len(selected),
                "claim_level": "coding-agent diagnostic (interventional subset)",
                "perturbation": "LEAK_MARKER: → ALT_LEAK:",
            },
            indent=2,
        )
        + "\n"
    )
    # markers sidecar for probe (ALT markers)
    markers = []
    for row in perturbed:
        contam = (row.get("metadata") or {}).get("contamination") or {}
        markers.append(
            {
                "instance_id": row["instance_id"],
                "leak_marker": contam.get("leak_marker") or contam.get("synthetic_marker"),
                "synthetic_marker": contam.get("synthetic_marker")
                or contam.get("leak_marker"),
                "gold_fingerprint": contam.get("gold_fingerprint"),
                "derived_line": contam.get("derived_line", ""),
            }
        )
    (out / "contamination_markers.jsonl").write_text(
        "\n".join(json.dumps(m) for m in markers) + ("\n" if markers else "")
    )
    print(f"prepared {len(selected)} perturbed cells under {out}")
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    out = Path(args.out)
    instances = out / "perturbed_instances.jsonl"
    if not instances.exists():
        raise SystemExit(f"missing {instances}; run prepare first")
    modal_out = out / "modal_perturbed"
    run_id = f"lbah-twoway-{int(time.time())}"
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
        "--allow-git-history",
        "--coding-prompt",
        "lbah",
    ]
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
        "--enable-contamination-probe",
        "--contamination-markers",
        str(out / "contamination_markers.jsonl"),
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


def _load_preds(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        out[str(row["instance_id"])] = str(row.get("model_patch") or "")
    return out


def cmd_summarize(args: argparse.Namespace) -> int:
    out = Path(args.out)
    selection = json.loads((out / "selection.json").read_text())
    ids = selection["instance_ids"]
    base = _load_preds(Path(args.base_predictions))
    alt_path = out / "modal_perturbed" / "official" / "predictions.jsonl"
    if not alt_path.exists():
        raise SystemExit(f"missing {alt_path}")
    alt = _load_preds(alt_path)

    rows: list[dict[str, Any]] = []
    leak_changed_n = 0
    for iid in ids:
        b = base.get(iid, "")
        a = alt.get(iid, "")
        changed = b != a and bool(b) and bool(a)
        if changed:
            leak_changed_n += 1
        rows.append(
            {
                "instance_id": iid,
                "base_len": len(b),
                "alt_len": len(a),
                "leak_commitment_changed": changed,
                "base_has_leak_marker": "LEAK_MARKER:" in b,
                "alt_has_alt_marker": "ALT_LEAK:" in a,
            }
        )
    n = len(rows)
    rate = leak_changed_n / max(1, n)
    (out / "two_way_gauge.json").write_text(
        json.dumps({"n": n, "leak_changed": leak_changed_n, "rate": rate, "rows": rows}, indent=2)
        + "\n"
    )

    lines = [
        "# SWE-bench two-way gauge — Track C interventional subset",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**coding-agent diagnostic (interventional subset)**. Not SOTA. "
        "Fingerprint flags remain correlational for the full matrix; this "
        "subset upgrades force-retrieve positives with a second-run leak "
        "perturbation (`LEAK_MARKER:` → `ALT_LEAK:`).",
        "",
        "## Acceptance",
        "",
        "On force-retrieve positives, leak probe changes commitment ≥ 0.80 "
        "of replayed cells (issue text unchanged).",
        "",
        "## Results",
        "",
        f"| metric | value |",
        f"|---|---:|",
        f"| cells | {n} |",
        f"| leak commitment changed | {leak_changed_n} |",
        f"| rate | {rate:.2f} |",
        "",
        "### Per-instance",
        "",
        "| instance_id | leak_changed | base has LEAK_MARKER | alt has ALT_LEAK |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['instance_id']} | {r['leak_commitment_changed']} | "
            f"{r['base_has_leak_marker']} | {r['alt_has_alt_marker']} |"
        )
    lines.extend(
        [
            "",
            "## Read",
            "",
        ]
    )
    if rate >= 0.80:
        lines.append(
            f"PASS ({rate:.2f}): intervening on the leak carrier moved the "
            "commitment on ≥80% of flagged cells — interventional confirmation "
            "of the marker heuristic on this subset."
        )
    else:
        lines.append(
            f"Below target ({rate:.2f} < 0.80): some flagged cells did not "
            "track the ALT fingerprint. Treat remaining matrix flags as "
            "correlational; expand N or inspect convergent patches."
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- `{out}`",
            f"- `{out / 'two_way_gauge.json'}`",
            "",
        ]
    )
    text = "\n".join(lines)
    (out / "TWO_WAY_GAUGE.md").write_text(text)
    if args.docs:
        docs = Path(args.docs)
        docs.parent.mkdir(parents=True, exist_ok=True)
        docs.write_text(text)
    print(text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("prepare")
    p.add_argument("--base-instances", required=True)
    p.add_argument("--flagged-from", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--limit", type=int, default=3)
    p.set_defaults(func=cmd_prepare)

    l = sp.add_parser("launch")
    l.add_argument("--out", required=True)
    l.add_argument("--model-agent", default="configs/provider_big.yaml")
    l.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    l.add_argument("--limit", type=int, default=3)
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

    s = sp.add_parser("summarize")
    s.add_argument("--out", required=True)
    s.add_argument("--base-predictions", required=True)
    s.add_argument("--docs", default="docs/results/SWEBENCH_TWO_WAY_GAUGE.md")
    s.set_defaults(func=cmd_summarize)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
