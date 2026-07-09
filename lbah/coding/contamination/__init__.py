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
    run_contamination_probe_on_real_diff,
)
from .read_set import (
    ReadCarrier,
    ReadSetInstance,
    ReadSetProbeResult,
    ReadVerdict,
    concern_event_log_from_instance,
    generate_read_set_slice,
    make_read_set_instance,
    read_set_agent,
    read_set_commit_fn,
    run_read_set_probe,
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
    "ReadCarrier",
    "ReadSetInstance",
    "ReadSetProbeResult",
    "ReadVerdict",
    "agent_for",
    "apply_operator",
    "calibrate_surface_perturbations",
    "concern_event_log_from_coding",
    "concern_event_log_from_instance",
    "contamination_flag",
    "derived_agent",
    "generate_read_set_slice",
    "generate_slice",
    "leak_tracking_agent",
    "make_instance",
    "make_read_set_instance",
    "operators_by_class",
    "policy_commit_fn",
    "read_set_agent",
    "read_set_commit_fn",
    "run_contamination_probe",
    "run_contamination_probe_on_real_diff",
    "run_read_set_probe",
    "write_toy_repo",
]
