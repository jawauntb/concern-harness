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
from .swebench import (
    SWEBenchInstance,
    infer_swebench_allowed_paths,
    load_swebench_instances,
    parse_swebench_test_list,
    swebench_run_artifact,
    swebench_test_command,
    swebench_to_coding_task,
    write_swebench_run_artifact,
)
from .swebench_eval import (
    SWEBenchBackendKind,
    SWEBenchEvaluationOptions,
    SWEBenchEvaluationResult,
    SWEBenchExecutionBackend,
    SWEBenchFailureKind,
    SWEBenchPreparedWorkspace,
    SWEBenchSuiteResult,
    classify_swebench_failure,
    prepare_swebench_workspace,
    resolve_swebench_repo_source,
    run_swebench_instance,
    run_swebench_smoke_suite,
    run_swebench_tests,
    sanitize_swebench_id,
    summarize_swebench_results,
    swebench_eval_commands,
    write_swebench_evaluation_artifacts,
)
from .task_tree import (
    ChildTaskResult,
    ChildTaskSpec,
    TaskTreeNode,
    default_child_tasks,
)
from .tournament import (
    CandidatePatchTournamentRunner,
    CandidateReviewSignal,
    CandidateRun,
    CandidateScore,
    TournamentRunResult,
    extract_candidate_review_signals,
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
    "SWEBenchInstance",
    "parse_swebench_test_list",
    "infer_swebench_allowed_paths",
    "swebench_test_command",
    "swebench_to_coding_task",
    "load_swebench_instances",
    "swebench_run_artifact",
    "write_swebench_run_artifact",
    "SWEBenchExecutionBackend",
    "SWEBenchBackendKind",
    "SWEBenchFailureKind",
    "SWEBenchEvaluationOptions",
    "SWEBenchPreparedWorkspace",
    "SWEBenchEvaluationResult",
    "SWEBenchSuiteResult",
    "sanitize_swebench_id",
    "resolve_swebench_repo_source",
    "prepare_swebench_workspace",
    "run_swebench_instance",
    "run_swebench_smoke_suite",
    "summarize_swebench_results",
    "run_swebench_tests",
    "swebench_eval_commands",
    "classify_swebench_failure",
    "write_swebench_evaluation_artifacts",
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
    "CandidateReviewSignal",
    "CandidateRun",
    "CandidateScore",
    "TournamentRunResult",
    "extract_candidate_review_signals",
    "score_candidate_result",
    "select_winning_candidate",
]
