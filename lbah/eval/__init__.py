"""Held-out eval primitives and LBAH-gated autoresearch."""

from .autoresearch import (
    AutoresearchConfig,
    AutoresearchResult,
    KnobConfig,
    MetricsSnapshot,
    run_autoresearch,
)
from .heldout import (
    aggregate_heldout,
    evaluate_heldout,
    score_proposal,
    tracking_commit_fn,
)
from .overblocking import evaluate_oracle_overblocking

__all__ = [
    "AutoresearchConfig",
    "AutoresearchResult",
    "KnobConfig",
    "MetricsSnapshot",
    "aggregate_heldout",
    "evaluate_heldout",
    "evaluate_oracle_overblocking",
    "run_autoresearch",
    "score_proposal",
    "tracking_commit_fn",
]
