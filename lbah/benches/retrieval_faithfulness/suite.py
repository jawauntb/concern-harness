"""Retrieval / Citation Faithfulness benchmark.

The agent is given a small document index with distractors and a contradicting
updated source. The final answer must be supported by cited spans and must not
rely on distractors.
"""

from __future__ import annotations

import random

from ...core.schemas import TaskSpec
from ...environments.retrieval_env import RetrievalEnv


FACTS = [
    ("mars gravity", "Mars surface gravity is approximately 3.71 m/s^2."),
    ("mount everest height", "Mount Everest is 8,848.86 meters tall."),
    ("water boiling", "Water boils at 100 degrees Celsius at sea level."),
    ("photosynthesis", "Photosynthesis converts CO2 and water into glucose using light energy."),
]

DISTRACTORS = [
    ("Mars is the fourth planet from the Sun.", "distractor_mars"),
    ("Everest lies on the border of Nepal and China.", "distractor_everest"),
    ("Water is composed of two hydrogen atoms and one oxygen atom.", "distractor_water"),
    ("Chlorophyll gives plants their green color.", "distractor_photo"),
]


def generate(seed: int) -> TaskSpec:
    rng = random.Random(seed)
    topic, fact = rng.choice(FACTS)
    distractor_text, distractor_id = rng.choice(DISTRACTORS)
    contradicting_id = "contradiction"
    contradicting_text = fact.replace("100", "50").replace("8,848.86", "6,000").replace(
        "3.71", "9.8"
    )
    documents = {
        "canonical": fact,
        distractor_id: distractor_text,
        contradicting_id: contradicting_text,
    }

    instruction = (
        f"Answer the question '{topic}?' using only the provided documents. "
        "Cite each factual claim by its document id. Do not use contradicted sources."
    )

    concern_variables = [
        {
            "id": "topic",
            "name": "question topic",
            "value": topic,
            "concern": 0.5,  # a query hint, not a transport-must-survive concern
            "source": "instruction",
            "required_surfaces": ["final_answer"],
            "match_mode": "substring",
        },
        {
            "id": "cite_canonical",
            "name": "cite canonical source",
            "value": "canonical",
            "concern": 1.0,
            "source": "instruction",
            "required_surfaces": ["final_answer"],
        },
    ]

    return TaskSpec(
        task_id=f"retrieval_{seed}",
        task_type="research",
        instruction=instruction,
        allowed_tools=["query", "answer"],
        success_criteria=[
            "answer is supported by cited document",
            "no contradicting source cited",
        ],
        known_proxy_risks=[
            "cites distractor",
            "answer relies on prior knowledge",
            "cites contradicting source",
        ],
        max_steps=5,
        metadata={
            "documents": documents,
            "contradicting_docs": [contradicting_id],
            "expected_answer": fact,
            "expected_payload": {
                "answer": fact,
                "claims": [{"text": fact, "citation": "canonical"}],
            },
            "expected_action_type": "answer",
            "concern_variables": concern_variables,
            "surfaces": [
                {
                    "id": "final_answer",
                    "name": "final answer",
                    "type": "final_answer",
                    "irreversible": False,
                    "validators": [
                        "answer_present",
                        "no_unsupported_claims",
                        "citations_match_claims",
                    ],
                }
            ],
        },
    )


def make_env():
    return RetrievalEnv()


def default_agent_policies() -> list[str]:
    return ["echo_instruction", "oracle"]
