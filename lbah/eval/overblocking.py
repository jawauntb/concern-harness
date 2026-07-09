"""OracleAgent false-block (overblocking) measurement for autoresearch constraints."""

from __future__ import annotations

from typing import Any

from ..adapters.dummy import OracleAgent
from ..benches import load_suite
from ..core.runner import HarnessModules, LoadBearingHarness
from ..modules import (
    CommitmentController,
    ConcernMapper,
    ProxyAdversary,
    ReopenabilityGovernor,
    SurfaceMapper,
    TransportAuditor,
    Verifier,
)


def _modules(thresholds: dict[str, float] | None) -> HarnessModules:
    return HarnessModules(
        concern_mapper=ConcernMapper(),
        surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(),
        proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(),
        commitment_controller=CommitmentController(thresholds=thresholds or {}),
    )


def evaluate_oracle_overblocking(
    *,
    suites: list[str],
    seeds: int,
    gauge_budget: int = 0,
    gauge_min_concern: float = 0.5,
    thresholds: dict[str, float] | None = None,
    mode: str = "guarded",
) -> dict[str, float]:
    """Fraction of OracleAgent first-step decisions that are not allow."""
    rows: list[dict[str, Any]] = []
    for suite_name in suites:
        suite = load_suite(suite_name)
        for seed in range(seeds):
            task = suite.generate(seed)
            env = suite.make_env()
            harness = LoadBearingHarness(
                OracleAgent(),
                env,
                _modules(thresholds),
                mode=mode,
                thresholds=thresholds or {},
                gauge_probe_budget=gauge_budget,
                gauge_min_concern=gauge_min_concern,
            )
            result = harness.run(task)
            first = result.certificates[0].decision if result.certificates else "no_cert"
            rows.append(
                {
                    "suite": suite_name,
                    "seed": seed,
                    "first_decision": first,
                    "final_success": result.final_success,
                    "load_score": result.load_score,
                }
            )
    n = max(1, len(rows))
    false_block = sum(1 for r in rows if r["first_decision"] != "allow") / n
    success = sum(1 for r in rows if r["final_success"]) / n
    mean_load = sum(float(r.get("load_score") or 0.0) for r in rows) / n
    return {
        "oracle_false_block_rate": false_block,
        "oracle_success_rate": success,
        "oracle_mean_load_score": mean_load,
        "n_oracle": float(len(rows)),
    }
