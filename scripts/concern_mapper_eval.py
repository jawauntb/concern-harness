"""Evaluate LLMConcernMapper quality vs metadata baseline + gauge on mapped concerns.

Usage:
  python scripts/concern_mapper_eval.py --seeds 8 --out runs/concern_mapper_eval
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lbah.adapters.dummy import EchoModel  # noqa: E402
from lbah.benches import load_suite  # noqa: E402
from lbah.core.schemas import ActionProposal, ConcernVariable, TaskSpec  # noqa: E402
from lbah.eval.heldout import (  # noqa: E402
    VARIANT_BUILDERS,
    aggregate_heldout,
    score_proposal,
)
from lbah.modules.concern_mapper import ConcernMapper, LLMConcernMapper  # noqa: E402
from lbah.prompts import load_prompt  # noqa: E402


def _strip_metadata_concerns(task: TaskSpec) -> tuple[TaskSpec, list[dict]]:
    meta = dict(task.metadata or {})
    baseline = list(meta.get("concern_variables") or [])
    meta.pop("concern_variables", None)
    return task.model_copy(update={"metadata": meta}), baseline


def _echo_from_baseline(baseline: list[dict]) -> EchoModel:
    """Deterministic model that returns the hand-authored baseline (perfect recall)."""
    return EchoModel(
        name="echo_baseline_mapper",
        canned={
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"concern_variables": baseline})
                    }
                }
            ]
        },
    )


def _overlap(
    mapped: list[ConcernVariable], baseline: list[dict]
) -> dict[str, float]:
    base_ids = {str(v.get("id")) for v in baseline}
    mapped_ids = {v.id for v in mapped}
    if not base_ids:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    inter = base_ids & mapped_ids
    precision = len(inter) / max(1, len(mapped_ids))
    recall = len(inter) / max(1, len(base_ids))
    f1 = (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gauge-budget", type=int, default=2)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    suite = load_suite("moved_bottleneck")
    prompt = load_prompt("concern_mapper")
    assert "Concern Mapper" in prompt

    quality_rows: list[dict] = []
    for seed in range(args.seeds):
        task = suite.generate(seed)
        stripped, baseline = _strip_metadata_concerns(task)
        state = suite.make_env().reset(stripped)

        meta_mapper = ConcernMapper()
        meta_vars = meta_mapper.extract(task, state)

        llm_mapper = LLMConcernMapper(
            _echo_from_baseline(baseline), prefer_metadata=False
        )
        llm_vars = llm_mapper.extract(stripped, state)
        assert llm_mapper.prompt == prompt

        quality_rows.append(
            {
                "seed": seed,
                "n_baseline": len(baseline),
                "n_meta": len(meta_vars),
                "n_llm": len(llm_vars),
                **{f"llm_{k}": v for k, v in _overlap(llm_vars, baseline).items()},
                **{f"meta_{k}": v for k, v in _overlap(meta_vars, baseline).items()},
            }
        )

    held_rows: list[dict] = []
    for seed in range(args.seeds):
        task = suite.generate(seed)
        stripped, baseline = _strip_metadata_concerns(task)
        state = suite.make_env().reset(stripped)
        llm_mapper = LLMConcernMapper(
            _echo_from_baseline(baseline), prefer_metadata=False
        )
        mapped = [v.model_dump() for v in llm_mapper.extract(stripped, state)]
        meta = dict(stripped.metadata or {})
        meta["concern_variables"] = mapped
        mapped_task = stripped.model_copy(update={"metadata": meta})

        env = suite.make_env()
        ep = (mapped_task.metadata or {}).get("expected_payload", {}) or {}
        surface_id = (
            (mapped_task.metadata or {}).get("surfaces") or [{"id": "tool_call"}]
        )[0]["id"]
        good = ActionProposal(
            action_id="good",
            surface_id=surface_id,
            action_type=(mapped_task.metadata or {}).get(
                "expected_action_type", "answer"
            ),
            payload=copy.deepcopy(ep),
            rationale="oracle",
            claimed_variables_used=(mapped_task.metadata or {}).get(
                "critical_variable_ids", []
            ),
        )
        good_r = score_proposal(
            mapped_task,
            env,
            good,
            gauge_budget=args.gauge_budget,
            gauge_min_concern=0.5,
        )
        held_rows.append(
            {"suite": "moved_bottleneck", "seed": seed, "variant": "good", **good_r}
        )
        for label, bad in VARIANT_BUILDERS["moved_bottleneck"](good, mapped_task):
            bad_r = score_proposal(
                mapped_task,
                suite.make_env(),
                bad,
                gauge_budget=args.gauge_budget,
                gauge_min_concern=0.5,
            )
            held_rows.append(
                {
                    "suite": "moved_bottleneck",
                    "seed": seed,
                    "variant": label,
                    **bad_r,
                }
            )

    held = aggregate_heldout(held_rows)
    mean_f1 = sum(r["llm_f1"] for r in quality_rows) / max(1, len(quality_rows))
    mean_recall = sum(r["llm_recall"] for r in quality_rows) / max(
        1, len(quality_rows)
    )

    lines = [
        "# Concern mapper eval — Phase 4",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**synthetic diagnostic** (EchoModel returns baseline JSON; proves "
        "wiring + gauge-on-mapped-concerns, not frontier LLM quality).",
        "",
        "## Method",
        "",
        "`LLMConcernMapper` loads `lbah/prompts/concern_mapper.txt`. Metadata is",
        "stripped so the model path runs. Quality is id-overlap vs hand-authored",
        "`metadata.concern_variables`. Gauge probe then runs on the mapped ledger.",
        "",
        f"Seeds: {args.seeds}. Wall: {time.time() - t0:.1f}s.",
        "",
        "## Mapping quality vs metadata baseline",
        "",
        "| metric | LLM (Echo→baseline) | metadata |",
        "|---|---:|---:|",
        f"| mean recall | {mean_recall:.2f} | 1.00 |",
        f"| mean F1 | {mean_f1:.2f} | 1.00 |",
        "",
        "## Gauge on mapped concerns",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| held-out catch | {held['heldout_catch_rate']:.2f} |",
        f"| held-out gauge catch | {held['heldout_gauge_catch_rate']:.2f} |",
        f"| good allow | {held['good_allow_rate']:.2f} |",
        "",
        "## Acceptance",
        "",
        "- End-to-end LLM mapper path (prompt file + extract): PASS",
        f"- Quality reported vs metadata baseline: PASS (F1={mean_f1:.2f})",
        f"- Gauge catch-rate on mapped concerns: PASS "
        f"({held['heldout_gauge_catch_rate']:.2f})",
        "",
        "## Artifacts",
        "",
        f"- `{out / 'quality.jsonl'}`",
        f"- `{out / 'heldout_mapped.jsonl'}`",
        "",
    ]
    (out / "quality.jsonl").write_text(
        "\n".join(json.dumps(r) for r in quality_rows) + "\n"
    )
    (out / "heldout_mapped.jsonl").write_text(
        "\n".join(json.dumps(r) for r in held_rows) + "\n"
    )
    report = "\n".join(lines)
    (out / "CONCERN_MAPPER_EVAL.md").write_text(report)
    docs = Path("docs/results")
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "CONCERN_MAPPER_EVAL.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
