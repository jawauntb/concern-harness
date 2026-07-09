"""Runtime-contamination detection for coding commitments."""

from .agents import agent_for, derived_agent, leak_tracking_agent
from .perturbations import OPERATORS, apply_operator, operators_by_class
from .probe import (
    ContaminationProbeResult,
    calibrate_surface_perturbations,
    concern_event_log_from_coding,
    contamination_flag,
    policy_commit_fn,
    run_contamination_probe,
)
from .slice import (
    ContaminationInstance,
    generate_slice,
    make_instance,
    write_toy_repo,
)

__all__ = [
    "ContaminationInstance",
    "ContaminationProbeResult",
    "OPERATORS",
    "agent_for",
    "apply_operator",
    "calibrate_surface_perturbations",
    "concern_event_log_from_coding",
    "contamination_flag",
    "derived_agent",
    "generate_slice",
    "leak_tracking_agent",
    "make_instance",
    "operators_by_class",
    "policy_commit_fn",
    "run_contamination_probe",
    "write_toy_repo",
]
