"""Real-repository coding harness primitives.

The existing ``lbah.environments.coding_env`` module is a simulated diff
environment for benchmark tasks. This package is the first LBAH-Code slice:
inspect/edit/test/finish actions over an actual workspace, with concern-led
verification and retry feedback.
"""

from .actions import CodingAction, CodingObservation, CodingTask
from .agents import ModelCodingAgent, ScriptedCodingAgent
from .ledger import CodingConcern, CodingLedger
from .runner import CodingHarnessRunner, CodingRunResult
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
]
