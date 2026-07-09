"""Concern mappers extract the variables that must survive into commitment."""

from __future__ import annotations

import json
from typing import Any

from ..core.schemas import ConcernVariable, State, TaskSpec
from ..prompts import load_prompt


class ConcernMapper:
    """Base: consults task.metadata.concern_variables if present.

    Any environment can populate `task.metadata["concern_variables"]` with a
    fully-formed list of dicts and this mapper will use them verbatim.
    """

    def extract(self, task: TaskSpec, state: State) -> list[ConcernVariable]:
        raw = (task.metadata or {}).get("concern_variables", [])
        if not raw:
            return self._heuristic(task)
        return [ConcernVariable.model_validate(v) for v in raw]

    def _heuristic(self, task: TaskSpec) -> list[ConcernVariable]:
        """Fallback: derive concern from the instruction plus success criteria."""
        variables: list[ConcernVariable] = []
        instr = task.instruction or ""
        for i, crit in enumerate(task.success_criteria):
            variables.append(
                ConcernVariable(
                    id=f"success_{i}",
                    name=crit[:40] or f"success criterion {i}",
                    value=crit,
                    concern=0.8,
                    source="success_criteria",
                    required_surfaces=["final_answer"],
                )
            )
        for i, risk in enumerate(task.known_proxy_risks):
            variables.append(
                ConcernVariable(
                    id=f"anti_proxy_{i}",
                    name=risk[:40] or f"proxy risk {i}",
                    value=None,
                    concern=0.7,
                    source="known_proxy_risks",
                    required_surfaces=["final_answer"],
                    proxy_risks=[risk],
                )
            )
        if not variables:
            variables.append(
                ConcernVariable(
                    id="instruction",
                    name="task instruction",
                    value=instr[:200],
                    concern=0.6,
                    source="instruction",
                    required_surfaces=["final_answer"],
                )
            )
        return variables


class MetadataConcernMapper(ConcernMapper):
    """Strict metadata-only mapper. Errors if task lacks metadata.concern_variables."""

    def extract(self, task: TaskSpec, state: State) -> list[ConcernVariable]:
        raw = (task.metadata or {}).get("concern_variables", [])
        if not raw:
            raise ValueError(
                f"MetadataConcernMapper requires task.metadata.concern_variables (task {task.task_id})"
            )
        return [ConcernVariable.model_validate(v) for v in raw]


class LLMConcernMapper(ConcernMapper):
    """LLM-backed concern mapper.

    Uses a `ModelAdapter` to identify variables. Falls back to the heuristic
    mapper if the model errors or returns invalid JSON.

    When ``prefer_metadata`` is True (default), hand-authored
    ``task.metadata.concern_variables`` short-circuit the model — useful in
    production. Eval scripts that measure mapper quality should set
    ``prefer_metadata=False`` (or strip metadata) so the model is forced.
    """

    def __init__(self, model: Any, *, prefer_metadata: bool = True):
        self.model = model
        self.prefer_metadata = prefer_metadata
        self.prompt = load_prompt("concern_mapper")

    def extract(self, task: TaskSpec, state: State) -> list[ConcernVariable]:
        if self.prefer_metadata:
            meta_vars = (task.metadata or {}).get("concern_variables")
            if meta_vars:
                return [ConcernVariable.model_validate(v) for v in meta_vars]

        prompt = json.dumps({"task": task.model_dump(), "state": state.model_dump()})
        try:
            response = self.model.complete(
                [
                    {"role": "system", "content": self.prompt},
                    {"role": "user", "content": prompt},
                ],
                schema={"type": "object"},
            )
            text = _response_content(response)
            data = json.loads(text)
            variables = [
                ConcernVariable.model_validate(v)
                for v in data.get("concern_variables", [])
            ]
            if not variables:
                return self._heuristic(task)
            return variables
        except Exception:
            return self._heuristic(task)


def _response_content(response: dict[str, Any]) -> str:
    """Normalize OpenAI-style and EchoModel canned shapes to a content string."""
    if "choices" in response:
        return str(response["choices"][0]["message"]["content"])
    if "content" in response:
        content = response["content"]
        return content if isinstance(content, str) else json.dumps(content)
    raise KeyError("model response missing content")
