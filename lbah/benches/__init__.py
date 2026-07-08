"""Benchmark suites.

Every suite exposes:

    generate(seed: int) -> TaskSpec
    make_env() -> Environment
    default_agent_policies() -> list[str]

so that the CLI can enumerate tasks without hard-coding YAML paths.
"""

from importlib import import_module

SUITES = {
    "moved_bottleneck": "lbah.benches.moved_bottleneck.suite",
    "tool_constraints": "lbah.benches.tool_constraints.suite",
    "coding_proxy": "lbah.benches.coding_proxy.suite",
    "retrieval_faithfulness": "lbah.benches.retrieval_faithfulness.suite",
    "stale_confidence": "lbah.benches.stale_confidence.suite",
}


def load_suite(name: str):
    if name not in SUITES:
        raise KeyError(f"unknown suite {name}; known: {sorted(SUITES.keys())}")
    return import_module(SUITES[name])
