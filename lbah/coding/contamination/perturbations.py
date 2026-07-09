"""Zhang & Guo-style surface vs semantic perturbation operators.

Surface (null) perturbations must not flip the contamination flag on derived
solves. Semantic (positive) perturbations must move the relevant probe.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel


PerturbClass = Literal["surface", "semantic"]
Target = Literal["issue", "leak_carrier"]
TransformFn = Callable[..., str]


class Perturbation(BaseModel):
    name: str
    target: Target
    klass: PerturbClass
    transform_description: str


def surface_issue(text: str) -> str:
    """Presentation-only change: whitespace / filler, meaning preserved."""
    return f"Please  {text.strip()}  "


def surface_leak(text: str) -> str:
    """Presentation-only change on the leak carrier."""
    return text.replace("\n", " \n ").replace("  ", " ")


def semantic_issue(text: str) -> str:
    """Meaning change: sum → product (derived commit_fn must move)."""
    return text.replace("sum", "product").replace("add", "multiply")


def semantic_leak(text: str, *, seed: int = 0) -> str:
    """Meaning change: rewrite the leak marker token."""
    if "LEAK_MARKER:" in text:
        return text.replace("LEAK_MARKER:", "ALT_LEAK:")
    return text + f"\nALT_LEAK:seed_{seed}"


OPERATORS: list[tuple[Perturbation, TransformFn]] = [
    (
        Perturbation(
            name="surface_whitespace_issue",
            target="issue",
            klass="surface",
            transform_description="pad/whitespace around issue text",
        ),
        lambda text, seed=0: surface_issue(text),
    ),
    (
        Perturbation(
            name="surface_whitespace_leak",
            target="leak_carrier",
            klass="surface",
            transform_description="whitespace normalize leak text",
        ),
        lambda text, seed=0: surface_leak(text),
    ),
    (
        Perturbation(
            name="semantic_sum_to_product",
            target="issue",
            klass="semantic",
            transform_description="change sum→product in issue",
        ),
        lambda text, seed=0: semantic_issue(text),
    ),
    (
        Perturbation(
            name="semantic_leak_marker",
            target="leak_carrier",
            klass="semantic",
            transform_description="rewrite LEAK_MARKER token",
        ),
        lambda text, seed=0: semantic_leak(text, seed=seed),
    ),
]


def apply_operator(name: str, text: str, *, seed: int = 0) -> str:
    for pert, fn in OPERATORS:
        if pert.name == name:
            return fn(text, seed=seed)
    raise KeyError(f"unknown perturbation operator {name!r}")


def operators_by_class(klass: PerturbClass) -> list[Perturbation]:
    return [p for p, _ in OPERATORS if p.klass == klass]
