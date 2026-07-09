"""Phase 4: LLMConcernMapper wiring, prompt loading, gauge on mapped concerns."""

from __future__ import annotations

import json
from pathlib import Path

from lbah.adapters.dummy import EchoModel
from lbah.benches import load_suite
from lbah.core.schemas import State
from lbah.modules.concern_mapper import LLMConcernMapper
from lbah.prompts import load_prompt


def test_load_prompt_reads_concern_mapper_file():
    text = load_prompt("concern_mapper")
    assert "Concern Mapper" in text
    assert "Return JSON only" in text


def test_llm_concern_mapper_uses_prompt_file_and_parses_json():
    canned = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "concern_variables": [
                                {
                                    "id": "slot",
                                    "name": "critical slot",
                                    "value": "production",
                                    "concern": 0.9,
                                    "source": "llm",
                                    "required_surfaces": ["tool_call"],
                                    "proxy_risks": ["wrong_slot"],
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }
    model = EchoModel(name="echo", canned=canned)
    mapper = LLMConcernMapper(model, prefer_metadata=False)
    assert mapper.prompt == load_prompt("concern_mapper")

    suite = load_suite("moved_bottleneck")
    task = suite.generate(0)
    meta = dict(task.metadata or {})
    meta.pop("concern_variables", None)
    task = task.model_copy(update={"metadata": meta})
    state = State(task_id=task.task_id)
    vars_ = mapper.extract(task, state)
    assert len(vars_) == 1
    assert vars_[0].id == "slot"
    assert vars_[0].value == "production"


def test_llm_concern_mapper_falls_back_on_bad_json():
    model = EchoModel(name="echo", canned={"choices": [{"message": {"content": "not-json"}}]})
    mapper = LLMConcernMapper(model, prefer_metadata=False)
    suite = load_suite("moved_bottleneck")
    task = suite.generate(1)
    meta = dict(task.metadata or {})
    meta.pop("concern_variables", None)
    task = task.model_copy(update={"metadata": meta, "success_criteria": ["ok"]})
    vars_ = mapper.extract(task, State(task_id=task.task_id))
    assert vars_  # heuristic fallback
    assert any(v.source == "success_criteria" for v in vars_)


def test_llm_prefer_metadata_short_circuits(tmp_path: Path):
    model = EchoModel(
        name="echo",
        canned={"choices": [{"message": {"content": '{"concern_variables":[]}'}}]},
    )
    mapper = LLMConcernMapper(model, prefer_metadata=True)
    suite = load_suite("moved_bottleneck")
    task = suite.generate(0)
    assert (task.metadata or {}).get("concern_variables")
    vars_ = mapper.extract(task, State(task_id=task.task_id))
    assert vars_
    assert all(v.source != "echo" for v in vars_)
