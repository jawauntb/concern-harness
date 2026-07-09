"""Aggregate scoring for a whole run."""

from __future__ import annotations

from .schemas import LoadBearingCertificate, RunResult, State, TaskSpec


class Scorer:
    """Reduce a step-by-step certificate stream into a RunResult."""

    def score(
        self,
        task: TaskSpec,
        agent_name: str,
        mode: str,
        final_state: State,
        certificates: list[LoadBearingCertificate],
        *,
        tokens: int = 0,
        wall_time_seconds: float = 0.0,
        cost_estimate: float = 0.0,
        extra_success: bool | None = None,
        event_log: dict | None = None,
    ) -> RunResult:
        if not certificates:
            return RunResult(
                task_id=task.task_id,
                agent=agent_name,
                mode=mode,
                final_success=bool(extra_success) if extra_success is not None else False,
                final_state=final_state.model_dump(),
                certificates=[],
                load_score=0.0,
                tokens=tokens,
                wall_time_seconds=wall_time_seconds,
                cost_estimate=cost_estimate,
                notes="no certificates emitted",
                event_log=event_log,
            )

        # Prefer the certificate from the last executed (allowed) step; fall back to last.
        last_allowed = next(
            (c for c in reversed(certificates) if c.decision == "allow"),
            certificates[-1],
        )

        behavior_success = (
            extra_success
            if extra_success is not None
            else last_allowed.behavior_passed and last_allowed.decision == "allow"
        )

        # Aggregate across the run: mean of allowed steps if any, else final.
        allowed = [c for c in certificates if c.decision == "allow"] or [last_allowed]

        def _mean(attr: str) -> float:
            vals = [getattr(c, attr) for c in allowed]
            return sum(vals) / len(vals) if vals else 0.0

        load = _mean("load_score")
        behavior = _mean("behavior_score")
        transport = _mean("transport_score")
        proxy = _mean("proxy_resistance_score")
        reopen = _mean("reopenability_score")
        validity = _mean("commitment_validity_score")

        failed_gates: list[str] = []
        for c in certificates:
            for r in (
                c.transport_results
                + c.proxy_results
                + c.gauge_results
                + c.reopenability_results
                + c.validator_results
            ):
                if not r.passed:
                    failed_gates.append(r.gate_name)

        return RunResult(
            task_id=task.task_id,
            agent=agent_name,
            mode=mode,
            final_success=bool(behavior_success),
            final_state=final_state.model_dump(),
            certificates=certificates,
            load_score=load,
            behavior_score=behavior,
            transport_score=transport,
            proxy_resistance_score=proxy,
            reopenability_score=reopen,
            commitment_validity_score=validity,
            tokens=tokens,
            wall_time_seconds=wall_time_seconds,
            cost_estimate=cost_estimate,
            failed_gates=sorted(set(failed_gates)),
            event_log=event_log,
        )
