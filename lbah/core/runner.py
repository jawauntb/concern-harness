"""The main harness loop."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .schemas import (
    ActionProposal,
    LoadBearingCertificate,
    RunResult,
    State,
    TaskSpec,
)
from .certificates import make_certificate
from .scorer import Scorer
from .ledger import make_ledger, merge_variables
from .events import events_from_ledger


@dataclass
class HarnessModules:
    concern_mapper: Any
    surface_mapper: Any
    transport_auditor: Any
    proxy_adversary: Any
    reopenability_governor: Any
    verifier: Any
    orchestration_auditor: Any | None = None
    commitment_controller: Any | None = None  # optional; certificates.decide_from_gates is default


class LoadBearingHarness:
    """The runtime that turns an agent + environment into load-bearing certificates."""

    def __init__(
        self,
        agent: Any,
        env: Any,
        modules: HarnessModules,
        scorer: Scorer | None = None,
        mode: str = "guarded",
        thresholds: dict[str, float] | None = None,
        gauge_probe_budget: int = 0,
        gauge_min_concern: float = 0.5,
    ):
        self.agent = agent
        self.env = env
        self.modules = modules
        self.scorer = scorer or Scorer()
        self.mode = mode
        self.thresholds = thresholds or {}
        # Gauge-fixing counterfactuals re-invoke the agent, so they are off by
        # default. Set gauge_probe_budget > 0 to probe the top-N highest-concern
        # variables per step (see ProxyAdversary and core.events).
        self.gauge_probe_budget = gauge_probe_budget
        self.gauge_min_concern = gauge_min_concern

    # ------------------------------------------------------------------

    def run(self, task: TaskSpec) -> RunResult:
        t0 = time.time()
        state: State = self.env.reset(task)
        variables = self.modules.concern_mapper.extract(task, state)
        surfaces = self.modules.surface_mapper.identify(task, variables)
        ledger = make_ledger(task, variables, surfaces)
        # Append-only mirror of the ledger. The runner keeps `ledger` as the
        # working object modules read/mutate, and mirrors every mutation into
        # `log` so log.project() stays equal to `ledger`. The log is what the
        # gauge-fixing probe forks from.
        log = events_from_ledger(ledger)

        certificates: list[LoadBearingCertificate] = []
        tokens = 0

        for step in range(task.max_steps):
            state.step = step
            proposal: ActionProposal = self.agent.propose_action(
                state.model_dump(),
                ledger.model_dump(),
            )
            tokens += getattr(self.agent, "last_tokens", 0) or 0

            transport = self.modules.transport_auditor.check(proposal, ledger, state)
            if self.gauge_probe_budget > 0:
                def commit_fn(projected, _state=state):
                    # Re-derive the commitment the agent would make from a given
                    # ledger projection. Only propose_action is called (never
                    # observe), so agent history is not disturbed by the probe.
                    return self.agent.propose_action(
                        _state.model_dump(), projected.model_dump()
                    ).payload

                proxy = self.modules.proxy_adversary.check(
                    proposal,
                    ledger,
                    state,
                    self.env,
                    log=log,
                    commit_fn=commit_fn,
                    gauge_budget=self.gauge_probe_budget,
                    gauge_min_concern=self.gauge_min_concern,
                )
            else:
                proxy = self.modules.proxy_adversary.check(proposal, ledger, state, self.env)
            if self.modules.orchestration_auditor is not None:
                orchestration = self.modules.orchestration_auditor.check(proposal, ledger, state)
                transport.extend(r for r in orchestration if r.gate_kind == "transport")
                proxy.extend(r for r in orchestration if r.gate_kind == "proxy")
            reopen = self.modules.reopenability_governor.check(proposal, ledger, state)
            validators = self.modules.verifier.validate(proposal, ledger, state, self.env)

            cert = make_certificate(
                task=task,
                ledger=ledger,
                proposal=proposal,
                transport=transport,
                proxy=proxy,
                reopen=reopen,
                validators=validators,
                thresholds=self.thresholds,
            )

            if self.mode == "audit":
                # In audit mode we always execute, never block; but still emit certificates.
                cert.decision = "allow"

            certificates.append(cert)

            if cert.decision == "allow":
                state = self.env.execute(proposal, state)
                self.agent.observe(state.model_dump())
                if self.env.done(state):
                    break
            elif cert.decision == "block":
                state = self.env.observe_block(proposal, cert, state)
                self.agent.observe(state.model_dump())
                # A block is terminal for that surface; break unless environment allows retry.
                if getattr(self.env, "terminal_on_block", True):
                    break
            elif cert.decision == "reopen":
                reopen_action = self.modules.reopenability_governor.reopen_action(cert, ledger)
                if reopen_action is not None:
                    state = self.env.execute(reopen_action, state)
                    # After reopen we mark the referenced variables fresh
                    for vid in reopen_action.claimed_variables_used:
                        v = ledger.by_id(vid)
                        if v is not None:
                            v.freshness = 1.0
                            log.append(
                                "set_freshness",
                                variable_id=vid,
                                payload={"freshness": 1.0},
                                source="reopenability_governor",
                            )
                self.agent.observe(state.model_dump())
            elif cert.decision == "ask_user":
                state = self.env.ask_user_or_simulator(cert, state)
                self.agent.observe(state.model_dump())
            elif cert.decision == "revise":
                state = self.env.request_revision(proposal, cert, state)
                self.agent.observe(state.model_dump())

            # Allow modules to append newly-discovered concern variables.
            new_vars = getattr(self.modules.proxy_adversary, "surfaced_variables", [])
            if new_vars:
                before = {
                    v.id: (v.value, v.concern, v.freshness) for v in ledger.variables
                }
                ledger.variables = merge_variables(ledger.variables, new_vars)
                # Mirror the *result* of the merge (which prefers higher concern)
                # so the log's projection stays equal to the working ledger.
                for v in ledger.variables:
                    sig = (v.value, v.concern, v.freshness)
                    if v.id not in before:
                        log.append(
                            "declare_variable",
                            variable_id=v.id,
                            payload=v.model_dump(),
                            source=v.source,
                        )
                    elif before[v.id] != sig:
                        log.append(
                            "revise_variable",
                            variable_id=v.id,
                            payload=v.model_dump(),
                            source=v.source,
                        )
                self.modules.proxy_adversary.surfaced_variables = []  # reset

            if self.env.done(state):
                break

        wall = time.time() - t0
        env_success = getattr(self.env, "success", None)
        env_success_val: bool | None = None
        if callable(env_success):
            try:
                env_success_val = bool(env_success(state))
            except Exception:
                env_success_val = None

        return self.scorer.score(
            task=task,
            agent_name=getattr(self.agent, "name", "agent"),
            mode=self.mode,
            final_state=state,
            certificates=certificates,
            tokens=tokens,
            wall_time_seconds=wall,
            extra_success=env_success_val,
        )
