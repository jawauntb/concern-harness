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
    ):
        self.agent = agent
        self.env = env
        self.modules = modules
        self.scorer = scorer or Scorer()
        self.mode = mode
        self.thresholds = thresholds or {}

    # ------------------------------------------------------------------

    def run(self, task: TaskSpec) -> RunResult:
        t0 = time.time()
        state: State = self.env.reset(task)
        variables = self.modules.concern_mapper.extract(task, state)
        surfaces = self.modules.surface_mapper.identify(task, variables)
        ledger = make_ledger(task, variables, surfaces)

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
                ledger.variables = merge_variables(ledger.variables, new_vars)
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
