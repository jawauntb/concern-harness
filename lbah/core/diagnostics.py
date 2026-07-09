"""Diagnostics for harness-effect and harness-evolution runs."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


GATE_FAMILIES = {
    "transport": "Concern variables failed to survive into the commitment surface.",
    "proxy": "The action may pass for a shortcut or gauge-equivalent reason.",
    "reopen": "The action used stale or reopenable state.",
    "validator": "The committed payload failed a deterministic surface contract.",
    "orchestration": "A multi-agent handoff lost concern or collapsed independent work.",
}


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path) as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def gate_family(gate_name: str) -> str:
    prefix = gate_name.split("::", 1)[0]
    if prefix in GATE_FAMILIES:
        return prefix
    if gate_name.startswith("orchestration::"):
        return "orchestration"
    return "other"


def summarize_runs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_config: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    failures: Counter[str] = Counter()
    families: Counter[str] = Counter()
    for row in rows:
        by_config[(row.get("agent", "agent"), row.get("mode", "mode"))].append(row)
        for gate in row.get("failed_gates") or []:
            failures[gate] += 1
            families[gate_family(gate)] += 1

    configs = []
    for (agent, mode), group in sorted(by_config.items()):
        n = len(group)
        configs.append(
            {
                "agent": agent,
                "mode": mode,
                "n": n,
                "final_success_rate": _rate(group, "final_success"),
                "load_score_mean": _mean(group, "load_score"),
                "behavior_score_mean": _mean(group, "behavior_score"),
                "transport_score_mean": _mean(group, "transport_score"),
                "proxy_resistance_mean": _mean(group, "proxy_resistance_score"),
                "reopenability_mean": _mean(group, "reopenability_score"),
                "commitment_validity_mean": _mean(group, "commitment_validity_score"),
                "tokens_mean": _mean(group, "tokens"),
                "component_score_coverage": _component_coverage(group),
            }
        )
    return {
        "n": len(rows),
        "configs": configs,
        "failed_gate_counts": dict(failures.most_common()),
        "failed_gate_family_counts": dict(families.most_common()),
    }


def improvement_proposals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _improvement_proposals_for_counts(summarize_runs(rows)["failed_gate_family_counts"])


def _improvement_proposals_for_counts(family_counts: dict[str, int]) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for family, count in family_counts.items():
        if family == "transport":
            proposals.append(
                _proposal(
                    family,
                    count,
                    "Tighten concern transport",
                    "Inspect failed variables, add exact-leaf checks or surface-specific required_surfaces, and rerun held-out proxy twins.",
                )
            )
        elif family == "proxy":
            proposals.append(
                _proposal(
                    family,
                    count,
                    "Add gauge-fixing contrasts",
                    "Promote recurring proxy failures into known_proxy_risks or env proxy_checks, then verify the control arm still passes.",
                )
            )
        elif family == "reopen":
            proposals.append(
                _proposal(
                    family,
                    count,
                    "Strengthen freshness policy",
                    "Add or narrow reopen_conditions so stale high-concern variables force recheck before commitment.",
                )
            )
        elif family == "validator":
            proposals.append(
                _proposal(
                    family,
                    count,
                    "Repair commitment-surface validators",
                    "Add deterministic validators for the failing surface or align task metadata with the actual payload contract.",
                )
            )
        elif family == "orchestration":
            proposals.append(
                _proposal(
                    family,
                    count,
                    "Audit multi-agent handoffs",
                    "Require orchestration traces on multi-agent tasks and verify access lists carry the top concern variables.",
                )
            )
        else:
            proposals.append(
                _proposal(
                    family,
                    count,
                    "Classify unknown gate failures",
                    "Map recurring unknown gates into a named family before changing harness behavior.",
                )
            )
    return proposals


def markdown_report(rows: list[dict[str, Any]]) -> str:
    summary = summarize_runs(rows)
    proposals = _improvement_proposals_for_counts(summary["failed_gate_family_counts"])
    lines = [
        "# LBAH Diagnostic Report",
        "",
        f"Runs analyzed: {summary['n']}",
        "",
        "## Model-Harness Configurations",
        "",
        "| Agent | Mode | n | Success | Load | Transport | Proxy | Reopen | Validity | Tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cfg in summary["configs"]:
        lines.append(
            "| {agent} | {mode} | {n} | {final_success_rate:.2f} | "
            "{load_score_mean:.2f} | {transport_score_mean:.2f} | "
            "{proxy_resistance_mean:.2f} | {reopenability_mean:.2f} | "
            "{commitment_validity_mean:.2f} | {tokens_mean:.0f} |".format(**cfg)
        )
    lines.extend(["", "## Failure Families", ""])
    if summary["failed_gate_family_counts"]:
        for family, count in summary["failed_gate_family_counts"].items():
            detail = GATE_FAMILIES.get(family, "Unclassified failure family.")
            lines.append(f"- `{family}`: {count} - {detail}")
    else:
        lines.append("- No failed gates recorded.")

    lines.extend(["", "## Improvement Proposals", ""])
    if proposals:
        for proposal in proposals:
            lines.append(
                f"- **{proposal['title']}** (`{proposal['family']}`, n={proposal['count']}): "
                f"{proposal['next_experiment']}"
            )
    else:
        lines.append("- No harness-evolution proposals; the run set recorded no gate failures.")
    return "\n".join(lines) + "\n"


def _proposal(family: str, count: int, title: str, next_experiment: str) -> dict[str, Any]:
    return {
        "family": family,
        "count": count,
        "title": title,
        "next_experiment": next_experiment,
    }


COMPONENT_SCORE_KEYS = (
    "behavior_score",
    "transport_score",
    "proxy_resistance_score",
    "reopenability_score",
    "commitment_validity_score",
)


def _component_coverage(rows: list[dict[str, Any]]) -> float:
    """Fraction of rows that persist all five per-component scores."""
    if not rows:
        return 0.0
    complete = sum(
        1
        for row in rows
        if all(row.get(k) is not None for k in COMPONENT_SCORE_KEYS)
    )
    return complete / len(rows)


def _mean(rows: list[dict[str, Any]], key: str) -> float:
    vals = [row[key] for row in rows if row.get(key) is not None]
    if not vals:
        return 0.0
    return sum(float(v) for v in vals) / len(vals)


def _rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get(key)) / len(rows)
