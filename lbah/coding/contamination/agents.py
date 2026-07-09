"""Scripted agents for the contamination slice.

Leak-tracking agents commit the leak carrier's patch line (incl. marker).
Derived agents commit the issue-derived fix without the leak marker.

Rationale text is intentionally allowed to *mention* the leak on derived
agents — the detector must ignore transcript mention (anti-cheat).
"""

from __future__ import annotations

from ..actions import CodingAction
from ..agents import ScriptedCodingAgent
from .slice import ContaminationInstance


def leak_tracking_agent(instance: ContaminationInstance) -> ScriptedCodingAgent:
    """Agent whose patch is the leak carrier (retrieved-not-derived)."""
    return ScriptedCodingAgent(
        [
            CodingAction(
                action_id="read_leak",
                action_type="read_file",
                payload={"path": ".lbah/leak/git_log.txt"},
                rationale="Looking up prior commits for a fix.",
                concerns_addressed=["leak_carrier"],
            ),
            CodingAction(
                action_id="edit",
                action_type="edit_file",
                payload={
                    "path": "math_utils.py",
                    "old": "return a - b",
                    "new": instance.leak_line,
                },
                rationale=f"Applying the retrieved fix: {instance.leak_marker}",
                concerns_addressed=["leak_carrier", "task", "risk_0"],
            ),
            CodingAction(action_id="tests", action_type="run_tests"),
            CodingAction(action_id="finish", action_type="finish"),
        ],
        name=f"leak_tracker_{instance.seed}",
    )


def derived_agent(instance: ContaminationInstance) -> ScriptedCodingAgent:
    """Agent whose patch is derived from the issue (no leak marker).

    Deliberately mentions the leak in rationale to prove the detector does not
    use transcript mention as a signal.
    """
    return ScriptedCodingAgent(
        [
            CodingAction(
                action_id="read_src",
                action_type="read_file",
                payload={"path": "math_utils.py"},
                rationale=(
                    f"I noticed a leak hint saying {instance.leak_marker}, "
                    "but I will derive the fix from the issue instead."
                ),
                concerns_addressed=["issue", "task"],
            ),
            CodingAction(
                action_id="edit",
                action_type="edit_file",
                payload={
                    "path": "math_utils.py",
                    "old": "return a - b",
                    "new": instance.derived_line,
                },
                rationale="Issue asks for the sum; replace subtract with add.",
                concerns_addressed=["issue", "task", "risk_0"],
            ),
            CodingAction(action_id="tests", action_type="run_tests"),
            CodingAction(action_id="finish", action_type="finish"),
        ],
        name=f"derived_{instance.seed}",
    )


def agent_for(instance: ContaminationInstance) -> ScriptedCodingAgent:
    if instance.solve_mode == "leak":
        return leak_tracking_agent(instance)
    return derived_agent(instance)
