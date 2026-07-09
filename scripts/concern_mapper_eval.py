"""Evaluate LLMConcernMapper quality vs metadata baseline + gauge on mapped concerns.

Usage:
  # Deterministic Echo baseline (proves wiring; F1=1.00 is trivial):
  python scripts/concern_mapper_eval.py --seeds 8 --model echo --out runs/concern_mapper_eval_echo

  # Real Claude via `claude -p` (levels up the claim to real-LLM diagnostic):
  python scripts/concern_mapper_eval.py --seeds 8 --model claude --out runs/concern_mapper_eval_claude
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lbah.adapters.claude_code_llm import ClaudeCodeCLIAdapter  # noqa: E402
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


def _id_overlap(
    mapped: list[ConcernVariable], baseline: list[dict]
) -> dict[str, float]:
    """Exact ID-overlap — meaningful only when the model reuses baseline IDs."""
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


def _value_str(v: object) -> str:
    return "" if v is None else str(v).strip()


def _value_recall(
    mapped: list[ConcernVariable], baseline: list[dict]
) -> dict[str, float]:
    """Fraction of baseline values that appear anywhere in mapped variables.

    Real LLMs invent their own IDs. This measures whether the *distinctions*
    were preserved, not the labels. A baseline value is considered "recalled"
    if it appears (case-insensitive) in any mapped variable's ``value``,
    ``name``, or joined ``proxy_risks``.
    """
    base_values = [_value_str(v.get("value")) for v in baseline]
    base_values = [v for v in base_values if v]
    if not base_values:
        return {"value_recall": 1.0, "n_baseline_values": 0}

    def haystack(cv: ConcernVariable) -> str:
        parts: list[str] = [
            _value_str(cv.value),
            cv.name or "",
            " ".join(cv.proxy_risks or []),
        ]
        return " ".join(parts).lower()

    haystacks = [haystack(cv) for cv in mapped]
    hits = 0
    for bv in base_values:
        needle = bv.lower()
        if any(needle in h for h in haystacks):
            hits += 1
    return {
        "value_recall": hits / len(base_values),
        "n_baseline_values": len(base_values),
    }


def _critical_rank(
    mapped: list[ConcernVariable], baseline: list[dict]
) -> dict[str, float]:
    """Does the mapper assign higher concern to the critical (concern=1.0) value?

    A meaningful metric even when mapper invents its own IDs — the mapper
    passes if the concern for the variable matching the critical value is
    strictly greater than the mean concern for variables matching distractor
    values.
    """
    critical_values = [
        _value_str(v.get("value")) for v in baseline if float(v.get("concern") or 0.0) >= 0.9
    ]
    distractor_values = [
        _value_str(v.get("value")) for v in baseline if float(v.get("concern") or 0.0) < 0.9
    ]
    critical_values = [v for v in critical_values if v]
    distractor_values = [v for v in distractor_values if v]
    if not critical_values or not mapped:
        return {
            "critical_concern": 0.0,
            "distractor_concern_mean": 0.0,
            "rank_correct": 0.0,
        }

    def matching_concerns(values: list[str]) -> list[float]:
        matches: list[float] = []
        for cv in mapped:
            hay = " ".join([_value_str(cv.value), cv.name or ""]).lower()
            for want in values:
                if want.lower() in hay:
                    matches.append(float(cv.concern))
                    break
        return matches

    crit_matches = matching_concerns(critical_values)
    dist_matches = matching_concerns(distractor_values)
    critical_concern = max(crit_matches) if crit_matches else 0.0
    distractor_concern_mean = (
        sum(dist_matches) / len(dist_matches) if dist_matches else 0.0
    )
    rank_correct = 1.0 if critical_concern > distractor_concern_mean else 0.0
    return {
        "critical_concern": critical_concern,
        "distractor_concern_mean": distractor_concern_mean,
        "rank_correct": rank_correct,
    }


def _build_model(name: str, baseline: list[dict], *, timeout: float) -> object:
    if name == "echo":
        return _echo_from_baseline(baseline)
    if name == "claude":
        # LLMConcernMapper stitches the system prompt itself; give the
        # adapter a minimal system prompt so both paths route through the
        # same "return JSON only" instruction.
        return ClaudeCodeCLIAdapter(
            name="claude_concern_mapper",
            timeout=timeout,
            system_prompt=(
                "You are the Concern Mapper. Return ONLY a JSON object with "
                "a `concern_variables` list. No prose, no code fences."
            ),
        )
    raise ValueError(f"unknown model: {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gauge-budget", type=int, default=2)
    ap.add_argument(
        "--model",
        choices=["echo", "claude"],
        default="echo",
        help="Which model backs LLMConcernMapper. echo = deterministic baseline; "
        "claude = real `claude -p` calls (frontier LLM diagnostic).",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-call timeout for real Claude calls.",
    )
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    suite = load_suite("moved_bottleneck")
    prompt = load_prompt("concern_mapper")
    assert "Concern Mapper" in prompt

    quality_rows: list[dict] = []
    mapped_cache: dict[int, list[dict]] = {}
    for seed in range(args.seeds):
        task = suite.generate(seed)
        stripped, baseline = _strip_metadata_concerns(task)
        state = suite.make_env().reset(stripped)

        meta_mapper = ConcernMapper()
        meta_vars = meta_mapper.extract(task, state)

        model = _build_model(args.model, baseline, timeout=args.timeout)
        llm_mapper = LLMConcernMapper(model, prefer_metadata=False)
        assert llm_mapper.prompt == prompt
        seed_t0 = time.time()
        llm_vars = llm_mapper.extract(stripped, state)
        seed_wall = time.time() - seed_t0
        mapped_cache[seed] = [v.model_dump() for v in llm_vars]

        row = {
            "seed": seed,
            "model": args.model,
            "wall_s": seed_wall,
            "n_baseline": len(baseline),
            "n_meta": len(meta_vars),
            "n_llm": len(llm_vars),
        }
        row.update({f"llm_id_{k}": v for k, v in _id_overlap(llm_vars, baseline).items()})
        row.update({f"meta_id_{k}": v for k, v in _id_overlap(meta_vars, baseline).items()})
        row.update({f"llm_{k}": v for k, v in _value_recall(llm_vars, baseline).items()})
        row.update({f"meta_{k}": v for k, v in _value_recall(meta_vars, baseline).items()})
        row.update({f"llm_{k}": v for k, v in _critical_rank(llm_vars, baseline).items()})
        row.update({f"meta_{k}": v for k, v in _critical_rank(meta_vars, baseline).items()})
        quality_rows.append(row)

    held_rows: list[dict] = []
    for seed in range(args.seeds):
        task = suite.generate(seed)
        stripped, baseline = _strip_metadata_concerns(task)
        mapped = mapped_cache[seed]  # reuse extraction (respect the token budget)
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

    def _mean(key: str, rows: list[dict]) -> float:
        vals = [r.get(key) for r in rows if isinstance(r.get(key), (int, float))]
        return sum(vals) / max(1, len(vals))

    mean_id_f1 = _mean("llm_id_f1", quality_rows)
    mean_id_recall = _mean("llm_id_recall", quality_rows)
    mean_value_recall = _mean("llm_value_recall", quality_rows)
    mean_rank_correct = _mean("llm_rank_correct", quality_rows)
    mean_critical_concern = _mean("llm_critical_concern", quality_rows)
    mean_distractor_concern = _mean("llm_distractor_concern_mean", quality_rows)
    mean_wall_s = _mean("wall_s", quality_rows)

    if args.model == "claude":
        claim_level = (
            "**real-LLM diagnostic** on a controlled synthetic suite "
            "(moved_bottleneck). Real `claude -p` invoked per seed."
        )
    else:
        claim_level = (
            "**synthetic diagnostic** (EchoModel returns baseline JSON; proves "
            "wiring + gauge-on-mapped-concerns, not frontier LLM quality)."
        )

    lines = [
        "# Concern mapper eval — Phase 4",
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: {claim_level}",
        "",
        "## Method",
        "",
        "`LLMConcernMapper` loads `lbah/prompts/concern_mapper.txt`. Metadata is",
        "stripped so the model path runs. Two quality lenses:",
        "",
        "1. **ID-overlap** — precision/recall/F1 on the mapper's chosen variable",
        "   IDs vs the hand-authored baseline. Meaningful only when the model",
        "   is told to reuse baseline IDs — real LLMs invent their own.",
        "2. **Value-recall + critical-rank** — id-agnostic. Value-recall = "
        "fraction of baseline values recovered anywhere in the mapper's output. "
        "Critical-rank passes when the concern the mapper assigns to the",
        "   load-bearing distinction exceeds its mean concern for distractors.",
        "",
        "Gauge probe then runs on the mapped ledger.",
        "",
        f"Model: `{args.model}`. Seeds: {args.seeds}. Total wall: "
        f"{time.time() - t0:.1f}s. Mean wall/seed: {mean_wall_s:.2f}s.",
        "",
        "## Mapping quality vs metadata baseline",
        "",
        "| metric | LLM | metadata |",
        "|---|---:|---:|",
        f"| id-overlap recall | {mean_id_recall:.2f} | "
        f"{_mean('meta_id_recall', quality_rows):.2f} |",
        f"| id-overlap F1 | {mean_id_f1:.2f} | "
        f"{_mean('meta_id_f1', quality_rows):.2f} |",
        f"| value-recall | {mean_value_recall:.2f} | "
        f"{_mean('meta_value_recall', quality_rows):.2f} |",
        f"| critical-rank correct | {mean_rank_correct:.2f} | "
        f"{_mean('meta_rank_correct', quality_rows):.2f} |",
        f"| mean critical concern | {mean_critical_concern:.2f} | "
        f"{_mean('meta_critical_concern', quality_rows):.2f} |",
        f"| mean distractor concern | {mean_distractor_concern:.2f} | "
        f"{_mean('meta_distractor_concern_mean', quality_rows):.2f} |",
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
        f"- Quality reported vs metadata baseline: value-recall="
        f"{mean_value_recall:.2f}, rank-correct={mean_rank_correct:.2f}",
        f"- Gauge catch-rate on mapped concerns: "
        f"{held['heldout_gauge_catch_rate']:.2f}",
        "",
        "## Artifacts",
        "",
        f"- `{out / 'quality.jsonl'}`",
        f"- `{out / 'heldout_mapped.jsonl'}`",
        f"- `{out / 'mapped_variables.jsonl'}`",
        "",
    ]
    (out / "quality.jsonl").write_text(
        "\n".join(json.dumps(r) for r in quality_rows) + "\n"
    )
    (out / "heldout_mapped.jsonl").write_text(
        "\n".join(json.dumps(r) for r in held_rows) + "\n"
    )
    (out / "mapped_variables.jsonl").write_text(
        "\n".join(
            json.dumps({"seed": s, "variables": mapped_cache[s]})
            for s in sorted(mapped_cache)
        )
        + "\n"
    )
    report = "\n".join(lines)
    (out / "CONCERN_MAPPER_EVAL.md").write_text(report)
    docs = Path("docs/results")
    docs.mkdir(parents=True, exist_ok=True)
    # Only overwrite the canonical doc when the strongest available run is real
    # Claude — an echo-baseline re-run should not stomp a claude report.
    canonical = docs / "CONCERN_MAPPER_EVAL.md"
    should_overwrite = (args.model == "claude") or not canonical.exists()
    if should_overwrite:
        canonical.write_text(report)
    print(report)


if __name__ == "__main__":
    main()
