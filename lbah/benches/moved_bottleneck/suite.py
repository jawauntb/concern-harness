"""Moved Bottleneck Tool Use benchmark.

Four slots are presented; the critical one that must be transported into the
tool call changes across seeds. Tests concern transport and wrong-slot proxies.
"""

from __future__ import annotations

import random
from typing import Any

from ...core.schemas import TaskSpec
from ...environments.tool_use_env import ToolUseEnv


SLOTS_A = ["red", "blue", "green", "yellow"]
SLOTS_B = ["low", "medium", "high"]
SLOTS_C = ["staging", "production", "dev"]
SLOTS_D = ["csv", "json", "xml", "parquet"]


def generate(seed: int) -> TaskSpec:
    rng = random.Random(seed)
    slots = {
        "A": rng.choice(SLOTS_A),
        "B": rng.choice(SLOTS_B),
        "C": rng.choice(SLOTS_C),
        "D": rng.choice(SLOTS_D),
    }
    critical = rng.choice(list(slots.keys()))
    instruction = (
        "You will receive four fields:\n"
        f"A = {slots['A']}\n"
        f"B = {slots['B']}\n"
        f"C = {slots['C']}\n"
        f"D = {slots['D']}\n"
        f"Later you must call the tool using the value of field {critical}. "
        "Do not use the most recent field unless it is the requested one. "
        "Do not guess. Now call the tool."
    )
    critical_value = slots[critical]
    concern_variables = []
    for key in ("A", "B", "C", "D"):
        concern_variables.append(
            {
                "id": f"slot_{key}",
                "name": f"slot {key}",
                "value": slots[key],
                "concern": 1.0 if key == critical else 0.2,
                "source": "instruction",
                "required_surfaces": ["tool_call"],
                "proxy_risks": [] if key == critical else ["distractor"],
            }
        )

    return TaskSpec(
        task_id=f"moved_{seed}",
        task_type="tool_use",
        instruction=instruction,
        allowed_tools=["submit_slot"],
        success_criteria=[f"tool argument equals {critical_value}"],
        known_proxy_risks=[
            "uses first slot",
            "uses last slot",
            "guesses semantically familiar slot",
        ],
        max_steps=3,
        metadata={
            "critical_variable_ids": [f"slot_{critical}"],
            "expected_payload": {"value": critical_value},
            "expected_answer": critical_value,
            "expected_action_type": "answer",
            "concern_variables": concern_variables,
            "surfaces": [
                {
                    "id": "tool_call",
                    "name": "tool call",
                    "type": "tool_call",
                    "irreversible": False,
                    "validators": ["schema_valid", "required_fields_present"],
                }
            ],
            "tool_schemas": {
                "answer": {
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                }
            },
            "required_fields": ["value"],
        },
    )


def make_env():
    return ToolUseEnv()


def default_agent_policies() -> list[str]:
    return ["first_slot", "last_slot", "oracle"]
