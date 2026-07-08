"""Empirical bound test.

The paper's inequality is Load >= (concern_mass - transport_loss) * gauge_scale
* commitment_effect. LBAH operationalizes it as a product:

    load_score = behavior * transport * proxy_resistance * reopenability * commitment_validity

Question: does `load_score` predict `env.success`? If yes, the bookkeeping
identity is empirically load-bearing (pun intended) — high load score means
the four obligations were paid AND the action worked. Miscalibration means
we either overweight a component or the components aren't independent.

Also tests ablation: what happens if we zero out one component in the score?
If ablating transport drops predictive power, transport is doing real work.
If it doesn't, transport is decorative.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys


def _load_all_certs(run_dirs: list[str]) -> list[dict]:
    """Return one row per certificate. If the results.jsonl only carries
    run-level scores (no per-cert list), fall back to synthesizing a single
    row from the run-level fields — most of our runs are that shape.
    """
    rows: list[dict] = []
    for rd in run_dirs:
        p = Path(rd) / "results.jsonl"
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            success = r.get("final_success")
            if success is None:
                success = r.get("final_success_if_allowed")
            certs = r.get("certificates") or []
            if certs:
                for c in certs:
                    rows.append({
                        "run_id": r.get("run_id") or r.get("task_id") or r.get("task"),
                        "task_id": r.get("task_id") or c.get("task_id"),
                        "source_dir": rd,
                        "final_success": success,
                        "decision": c.get("decision"),
                        "load_score": c.get("load_score"),
                        "behavior_score": c.get("behavior_score"),
                        "transport_score": c.get("transport_score"),
                        "proxy_resistance_score": c.get("proxy_resistance_score"),
                        "reopenability_score": c.get("reopenability_score"),
                        "commitment_validity_score": c.get("commitment_validity_score"),
                    })
            elif "load_score" in r:
                rows.append({
                    "run_id": r.get("run_id") or r.get("task_id") or r.get("task"),
                    "task_id": r.get("task_id") or r.get("task"),
                    "source_dir": rd,
                    "final_success": success,
                    "decision": r.get("decision") or r.get("first_decision"),
                    "load_score": r.get("load_score"),
                    "behavior_score": r.get("behavior_score"),
                    "transport_score": r.get("transport_score"),
                    "proxy_resistance_score": r.get("proxy_resistance_score"),
                    "reopenability_score": r.get("reopenability_score"),
                    "commitment_validity_score": r.get("commitment_validity_score"),
                })
    return rows


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return 0.0
    return num / (dx * dy)


def _bucket_calibration(rows: list[dict], key: str, n_buckets: int = 5) -> list[dict]:
    """Sort rows by `key`, split into equal-size buckets, report mean-key and success-rate."""
    valid = [r for r in rows if r.get(key) is not None and r.get("final_success") is not None]
    if not valid:
        return []
    valid.sort(key=lambda r: r[key])
    buckets: list[dict] = []
    bs = max(1, len(valid) // n_buckets)
    for i in range(n_buckets):
        chunk = valid[i * bs : (i + 1) * bs] if i < n_buckets - 1 else valid[i * bs:]
        if not chunk:
            continue
        mk = sum(r[key] for r in chunk) / len(chunk)
        succ = sum(1 for r in chunk if r["final_success"]) / len(chunk)
        buckets.append({"bucket": i, "n": len(chunk), "mean_score": mk, "success_rate": succ})
    return buckets


def _ablate_component(rows: list[dict], component: str) -> tuple[list[float], list[float]]:
    """Compute an ablated load score with `component` set to 1.0."""
    xs: list[float] = []
    ys: list[float] = []
    keys = [
        "behavior_score", "transport_score", "proxy_resistance_score",
        "reopenability_score", "commitment_validity_score",
    ]
    for r in rows:
        if r.get("final_success") is None:
            continue
        vals: list[float] = []
        skip = False
        for k in keys:
            v = r.get(k)
            if v is None:
                skip = True
                break
            vals.append(1.0 if k == component else float(v))
        if skip:
            continue
        prod = 1.0
        for v in vals:
            prod *= v
        xs.append(prod)
        ys.append(1.0 if r["final_success"] else 0.0)
    return xs, ys


def _brier(preds: list[float], labels: list[float]) -> float:
    if not preds:
        return 0.0
    return sum((p - l) ** 2 for p, l in zip(preds, labels)) / len(preds)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run_dirs", nargs="+", required=True, help="dirs with results.jsonl")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = _load_all_certs(args.run_dirs)
    print(f"loaded {len(rows)} certificate rows from {len(args.run_dirs)} run dirs")
    if not rows:
        return

    # ---- Correlations of each component with final_success ----
    print("\nComponent correlation with final_success:")
    corr_report = []
    for key in ("load_score", "behavior_score", "transport_score",
                "proxy_resistance_score", "reopenability_score",
                "commitment_validity_score"):
        pairs = [(r[key], 1.0 if r.get("final_success") else 0.0)
                 for r in rows if r.get(key) is not None and r.get("final_success") is not None]
        if not pairs:
            continue
        xs, ys = zip(*pairs)
        r = _pearson(list(xs), list(ys))
        corr_report.append({"component": key, "n": len(pairs), "pearson_r": r})
        print(f"  {key:<30} n={len(pairs):>4}  r={r:+.3f}")

    # ---- Calibration buckets ----
    print("\nCalibration by load_score bucket:")
    calib = _bucket_calibration(rows, "load_score", n_buckets=5)
    for b in calib:
        print(f"  bucket {b['bucket']}: n={b['n']:>4}  mean_load={b['mean_score']:.2f}  success={b['success_rate']:.2f}")

    # ---- Ablation: which components carry predictive weight? ----
    print("\nAblation (set component to 1.0, recompute product):")
    abl_report = []
    for comp in ("behavior_score", "transport_score", "proxy_resistance_score",
                 "reopenability_score", "commitment_validity_score"):
        xs, ys = _ablate_component(rows, comp)
        if not xs:
            continue
        pearson = _pearson(xs, ys)
        brier = _brier(xs, ys)
        abl_report.append({"ablated": comp, "n": len(xs), "pearson_r": pearson, "brier": brier})
        print(f"  ablate {comp:<26} n={len(xs):>4}  r={pearson:+.3f}  brier={brier:.3f}")

    # Baseline unablated
    xs = [r["load_score"] for r in rows if r.get("load_score") is not None and r.get("final_success") is not None]
    ys = [1.0 if r.get("final_success") else 0.0 for r in rows if r.get("load_score") is not None and r.get("final_success") is not None]
    baseline_r = _pearson(xs, ys)
    baseline_brier = _brier(xs, ys)
    print(f"  baseline (no ablation)      n={len(xs):>4}  r={baseline_r:+.3f}  brier={baseline_brier:.3f}")

    # ---- Persist ----
    (out / "component_correlations.json").write_text(json.dumps(corr_report, indent=2))
    (out / "calibration.json").write_text(json.dumps(calib, indent=2))
    (out / "ablation.json").write_text(json.dumps(abl_report, indent=2))
    (out / "baseline.json").write_text(json.dumps({
        "n": len(xs), "pearson_r": baseline_r, "brier": baseline_brier,
    }, indent=2))

    # Summary text
    summary = ["# Empirical bound test\n"]
    summary.append(f"n = {len(rows)} certificates aggregated from {len(args.run_dirs)} run dirs.\n")
    summary.append("## Component correlation with final_success (Pearson r)")
    for c in corr_report:
        summary.append(f"- {c['component']:<30} r = {c['pearson_r']:+.3f}  (n={c['n']})")
    summary.append("\n## Calibration by load_score bucket")
    summary.append(f"{'bucket':<8}{'n':>6}{'mean_load':>12}{'success':>10}")
    for b in calib:
        summary.append(f"{b['bucket']:<8}{b['n']:>6}{b['mean_score']:>12.2f}{b['success_rate']:>10.2f}")
    summary.append("\n## Ablation (set component to 1.0, recompute product-load, Pearson vs baseline)")
    summary.append(f"baseline pearson r = {baseline_r:+.3f}, brier = {baseline_brier:.3f}, n = {len(xs)}\n")
    summary.append(f"{'ablated':<32}{'n':>6}{'r':>8}{'d_r':>10}{'brier':>10}")
    for a in abl_report:
        dr = a["pearson_r"] - baseline_r
        summary.append(f"{a['ablated']:<32}{a['n']:>6}{a['pearson_r']:>+8.3f}{dr:>+10.3f}{a['brier']:>10.3f}")

    (out / "summary.md").write_text("\n".join(summary))
    print("\nwrote", out)


if __name__ == "__main__":
    main()
