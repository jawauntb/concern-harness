"""Overblocking test.

Feed KNOWN-CORRECT actions (from the OracleAgent) to the harness and count
the rate at which it blocks or revises them. A harness that blocks 100% of
tasks is trivially "safe"; a harness that blocks correct actions is broken.

We want the false-block rate <= a few percent across suites.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lbah.adapters.dummy import OracleAgent  # noqa: E402
from lbah.benches import load_suite  # noqa: E402
from lbah.core.runner import HarnessModules, LoadBearingHarness  # noqa: E402
from lbah.modules import (  # noqa: E402
    CommitmentController,
    ConcernMapper,
    ProxyAdversary,
    ReopenabilityGovernor,
    SurfaceMapper,
    TransportAuditor,
    Verifier,
)


def _harness():
    return HarnessModules(
        concern_mapper=ConcernMapper(),
        surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(),
        proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(),
        commitment_controller=CommitmentController(),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", nargs="+", required=True)
    ap.add_argument("--seeds", type=int, default=110)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stream = open(out / "results.jsonl", "w")
    rows: list[dict] = []
    t0 = time.time()

    for suite_name in args.suites:
        suite = load_suite(suite_name)
        for seed in range(args.seeds):
            task = suite.generate(seed)
            env = suite.make_env()
            agent = OracleAgent()
            harness = LoadBearingHarness(agent, env, _harness(), mode="guarded")
            result = harness.run(task)
            # First-step decision is what we care about: did the harness block
            # the oracle's very first (correct) attempt?
            first_decision = result.certificates[0].decision if result.certificates else "no_cert"
            all_decisions = [c.decision for c in result.certificates]
            row = {
                "suite": suite_name,
                "seed": seed,
                "task_id": task.task_id,
                "first_decision": first_decision,
                "all_decisions": all_decisions,
                "final_success": result.final_success,
                "load_score": result.load_score,
                "failed_gates_first_step": [
                    r.gate_name
                    for r in (
                        result.certificates[0].transport_results
                        + result.certificates[0].proxy_results
                        + result.certificates[0].reopenability_results
                        + result.certificates[0].validator_results
                    )
                    if not r.passed
                ] if result.certificates else [],
            }
            rows.append(row)
            stream.write(json.dumps(row) + "\n")
    stream.close()

    print(f"n={len(rows)} across suites={args.suites}, seeds={args.seeds}, wall={time.time()-t0:.1f}s")

    # Aggregate
    lines = ["suite               first_decision_distribution                                success  wall"]
    lines.append("-" * 105)
    for suite_name in args.suites:
        srows = [r for r in rows if r["suite"] == suite_name]
        first = Counter(r["first_decision"] for r in srows)
        success = sum(1 for r in srows if r["final_success"]) / len(srows)
        pretty = ", ".join(f"{k}={v}" for k, v in first.most_common())
        lines.append(f"{suite_name:<20}{pretty:<60}{success:>10.2f}")
    total = Counter(r["first_decision"] for r in rows)
    lines.append("-" * 105)
    lines.append(f"{'OVERALL':<20}{', '.join(f'{k}={v}' for k, v in total.most_common())}")

    # Compute false-block rate
    n = len(rows)
    n_first_allow = sum(1 for r in rows if r["first_decision"] == "allow")
    n_first_not_allow = n - n_first_allow
    lines.append("")
    lines.append(f"OVERBLOCKING (first-step not-allow on oracle): {n_first_not_allow}/{n} = {n_first_not_allow/n:.3f}")

    lb = "\n".join(lines)
    print("\n" + lb)
    (out / "leaderboard.txt").write_text(lb)


if __name__ == "__main__":
    main()
