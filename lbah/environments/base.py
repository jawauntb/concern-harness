"""Environment protocol used by the runner."""

from __future__ import annotations

from typing import Any

from ..core.schemas import (
    ActionProposal,
    LoadBearingCertificate,
    Observation,
    State,
    TaskSpec,
)


class Environment:
    """Base class. Subclasses override `reset`, `execute`, `done`, and `success`."""

    #: If False, blocked steps are treated as recoverable — the runner keeps looping.
    terminal_on_block: bool = True

    def reset(self, task: TaskSpec) -> State:
        return State(task_id=task.task_id, step=0, done=False, scratch={})

    def execute(self, proposal: ActionProposal, state: State) -> State:
        state.step += 1
        state.last_observation = Observation(text=f"executed {proposal.action_type}")
        state.done = True
        return state

    def observe_block(
        self,
        proposal: ActionProposal,
        cert: LoadBearingCertificate,
        state: State,
    ) -> State:
        state.last_observation = Observation(
            text=f"blocked at surface {proposal.surface_id}: {cert.summary}",
            data={"cert": cert.model_dump()},
        )
        return state

    def ask_user_or_simulator(
        self,
        cert: LoadBearingCertificate,
        state: State,
    ) -> State:
        state.last_observation = Observation(
            text=f"user asked to clarify: {cert.summary}",
            data={"cert": cert.model_dump()},
        )
        return state

    def request_revision(
        self,
        proposal: ActionProposal,
        cert: LoadBearingCertificate,
        state: State,
    ) -> State:
        state.last_observation = Observation(
            text=f"revision requested: {cert.summary}",
            data={"failed_gates": [g for g in cert.summary.split() if "::" in g]},
        )
        return state

    def done(self, state: State) -> bool:
        return state.done

    def success(self, state: State) -> bool:
        return state.done and not (state.last_observation and state.last_observation.text and
                                   "blocked" in state.last_observation.text)

    def proxy_checks(
        self,
        proposal: ActionProposal,
        ledger: Any,
        state: State,
    ) -> list:
        """Environment-specific proxy checks (override for coding/browser envs)."""
        return []

    def extra_validators(
        self,
        proposal: ActionProposal,
        ledger: Any,
        state: State,
    ) -> list:
        """Environment-specific extra validators (hidden tests, etc)."""
        return []
