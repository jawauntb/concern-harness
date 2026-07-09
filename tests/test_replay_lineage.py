"""RunResult carries the event log; `lbah replay --lineage` reads it back."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from lbah.cli import cli
from lbah.core.events import ConcernEventLog
from lbah.core.runner import HarnessModules, LoadBearingHarness
from lbah.core.schemas import ActionProposal, TaskSpec
from lbah.environments.tool_use_env import ToolUseEnv
from lbah.modules import (
    CommitmentController,
    ConcernMapper,
    ProxyAdversary,
    ReopenabilityGovernor,
    SurfaceMapper,
    TransportAuditor,
    Verifier,
)


class TopConcernAgent:
    name = "top_concern"
    last_tokens = 0

    def propose_action(self, state, ledger):
        variables = ledger.get("variables") or []
        surfaces = ledger.get("surfaces") or []
        surface_id = surfaces[0]["id"] if surfaces else "final_answer"
        top = max(variables, key=lambda v: v.get("concern", 0.0)) if variables else None
        return ActionProposal(
            action_id=f"a{state.get('step', 0)}",
            surface_id=surface_id,
            action_type="answer",
            payload={"value": top.get("value") if top else None},
        )

    def observe(self, observation):
        return None


def _modules() -> HarnessModules:
    return HarnessModules(
        concern_mapper=ConcernMapper(),
        surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(),
        proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(),
        commitment_controller=CommitmentController(),
    )


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="ctrl",
        task_type="tool_use",
        instruction="use the critical value",
        metadata={
            "concern_variables": [
                {"id": "crit", "name": "crit", "value": "alpha", "concern": 0.95, "source": "task", "required_surfaces": ["tool_call"]},
            ],
            "required_surfaces": [{"id": "tool_call", "name": "tool call", "type": "tool_call"}],
        },
    )


def _run():
    return LoadBearingHarness(TopConcernAgent(), ToolUseEnv(), _modules(), mode="audit").run(_task())


def test_run_result_carries_event_log():
    result = _run()
    assert result.event_log is not None
    log = ConcernEventLog.model_validate(result.event_log)
    assert log.lineage("crit"), "expected declare event for crit in the surfaced log"
    assert log.project().by_id("crit").value == "alpha"


def test_event_log_survives_json_roundtrip():
    result = _run()
    data = json.loads(result.model_dump_json())
    log = ConcernEventLog.model_validate(data["event_log"])
    assert log.project().by_id("crit").value == "alpha"


def test_replay_lineage_cli(tmp_path: Path):
    result = _run()
    run_path = tmp_path / "run.json"
    run_path.write_text(result.model_dump_json())

    out = CliRunner().invoke(cli, ["replay", str(run_path), "--lineage", "crit"])
    assert out.exit_code == 0, out.output
    assert "Lineage of 'crit'" in out.output
    assert "declare_variable" in out.output
    assert "projected: value='alpha'" in out.output


def test_replay_lineage_unknown_variable(tmp_path: Path):
    result = _run()
    run_path = tmp_path / "run.json"
    run_path.write_text(result.model_dump_json())

    out = CliRunner().invoke(cli, ["replay", str(run_path), "--lineage", "nope"])
    assert out.exit_code == 0, out.output
    assert "no events for variable 'nope'" in out.output
    assert "crit" in out.output  # lists known variables


def test_replay_without_lineage_still_prints_certificates(tmp_path: Path):
    result = _run()
    run_path = tmp_path / "run.json"
    run_path.write_text(result.model_dump_json())

    out = CliRunner().invoke(cli, ["replay", str(run_path)])
    assert out.exit_code == 0, out.output
    assert "step 0" in out.output


def test_replay_lineage_missing_log_is_graceful(tmp_path: Path):
    result = _run()
    payload = json.loads(result.model_dump_json())
    payload["event_log"] = None  # simulate a pre-event-sourcing run
    run_path = tmp_path / "run.json"
    run_path.write_text(json.dumps(payload))

    out = CliRunner().invoke(cli, ["replay", str(run_path), "--lineage", "crit"])
    assert out.exit_code == 0, out.output
    assert "no event_log on this run" in out.output
