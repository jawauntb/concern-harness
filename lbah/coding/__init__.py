"""Real-repository coding harness primitives.

The existing ``lbah.environments.coding_env`` module is a simulated diff
environment for benchmark tasks. This package is the first LBAH-Code slice:
inspect/edit/test/finish actions over an actual workspace, with concern-led
verification and retry feedback.
"""

from .actions import CodingAction, CodingObservation, CodingTask
from .agents import ModelCodingAgent, ScriptedCodingAgent
from .ledger import CodingConcern, CodingLedger
from .recursive import (
    RecursiveCodingHarnessRunner,
    ScriptedChildAgent,
    apply_child_result,
    validate_child_result,
)
from .runner import CodingHarnessRunner, CodingRunResult
from .task_tree import (
    ChildTaskResult,
    ChildTaskSpec,
    TaskTreeNode,
    default_child_tasks,
)
from .tournament import (
    CandidatePatchTournamentRunner,
    CandidateRun,
    CandidateScore,
    TournamentRunResult,
    score_candidate_result,
    select_winning_candidate,
)
from .workspace import CodingWorkspace

__all__ = [
    "CodingAction",
    "CodingObservation",
    "CodingTask",
    "ScriptedCodingAgent",
    "CodingConcern",
    "CodingLedger",
    "CodingHarnessRunner",
    "CodingRunResult",
    "CodingWorkspace",
    "ModelCodingAgent",
    "ChildTaskResult",
    "ChildTaskSpec",
    "TaskTreeNode",
    "default_child_tasks",
    "RecursiveCodingHarnessRunner",
    "ScriptedChildAgent",
    "validate_child_result",
    "apply_child_result",
    "CandidatePatchTournamentRunner",
    "CandidateRun",
    "CandidateScore",
    "TournamentRunResult",
    "score_candidate_result",
    "select_winning_candidate",
]
