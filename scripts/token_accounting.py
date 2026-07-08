"""Token-cost accounting.

We don't have exact token counts from `claude -p` (would need the API), so
we estimate via character length: ~4 chars/token for English + JSON. This
is a proxy, not a bill; it's fine for cross-arm ratios which is what we
care about.

Retrofit onto existing ablation results by regenerating each arm's prompt
and measuring:
    prompt_tokens_est ≈ len(system + user_prompt) / 4
    completion_tokens_est ≈ len(rationale + payload_json) / 4

Report:
    per-task tokens, per-successful-task tokens (cost / success), per-arm.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lbah.benches import load_suite  # noqa: E402


CHARS_PER_TOKEN = 4.0


RAW_SYSTEM = (
    "You are a tool-using agent. Read the instruction and reply with ONE JSON "
    "action, no prose, no fences: "
    "{action_id, surface_id, action_type, payload, rationale, "
    "claimed_variables_used}. Choose a plausible surface_id (tool_call, "
    "memory_write, final_answer) for the task."
)


def _load_suite_task(task_ref: str):
    suite_name, seed_str = task_ref.split(":", 1)
    suite = load_suite(suite_name)
    return suite.generate(int(seed_str))


def _tokens(s: str) -> float:
    return len(s) / CHARS_PER_TOKEN


def _raw_prompt_len(task) -> int:
    return int(_tokens(RAW_SYSTEM) + _tokens(task.instruction))


def _raw_schema_prompt_len(task) -> int:
    """Reproduce the raw+schema prompt built in ablation_matched_prompt.py."""
    meta = task.metadata or {}
    parts: list[str] = [task.instruction]
    if meta.get("tool_schemas"):
        parts.append(json.dumps(meta["tool_schemas"]))
    if meta.get("required_fields"):
        parts.append(",".join(meta["required_fields"]))
    fields_pin = []
    for cv in meta.get("concern_variables", []) or []:
        if cv.get("concern", 0) >= 0.5 and cv.get("value") is not None:
            fields_pin.append({"id": cv["id"], "value": cv["value"]})
    if fields_pin:
        parts.append(json.dumps(fields_pin))
    if meta.get("forbidden_values"):
        parts.append(json.dumps(meta["forbidden_values"]))
    body = "\n".join(parts)
    return int(_tokens(RAW_SYSTEM) + _tokens(body))


def _harness_prompt_len(task) -> int:
    """The harness ClaudeCodeCLIAdapter puts state + ledger inline. Estimate
    from the ledger JSON size, which is roughly what gets sent."""
    meta = task.metadata or {}
    ledger_json = json.dumps({
        "task": task.model_dump(),
        "variables": meta.get("concern_variables", []),
        "surfaces": meta.get("surfaces", []),
    })
    return int(_tokens(RAW_SYSTEM) + _tokens(ledger_json))


def _completion_tokens(proposal: dict | None) -> int:
    if not proposal:
        return 0
    return int(_tokens(json.dumps(proposal)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--sources",
        nargs="+",
        default=[
            "runs/ablation_matched",  # raw + raw+schema (initial run had bugs)
            "runs/ablation_matched_rawschema_fix",  # raw+schema after prompt fix
            "runs/ablation_matched_harness_v2",  # harness
        ],
    )
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    per_arm: dict[str, list[dict]] = {}
    for src in args.sources:
        p = Path(src) / "results.jsonl"
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("error"):
                continue
            arm = r.get("mode", "unknown")
            task_ref = r.get("task")
            if not task_ref or ":" not in task_ref:
                continue
            try:
                task = _load_suite_task(task_ref)
            except Exception:
                continue
            if arm == "raw":
                pt = _raw_prompt_len(task)
            elif arm == "raw+schema":
                pt = _raw_schema_prompt_len(task)
            elif arm == "harness":
                pt = _harness_prompt_len(task)
            else:
                continue
            ct = _completion_tokens(r.get("proposal") or {})
            total = pt + ct
            per_arm.setdefault(arm, []).append({
                "task": task_ref,
                "prompt_tokens_est": pt,
                "completion_tokens_est": ct,
                "total_tokens_est": total,
                "success": bool(r.get("final_success")),
                "wall_seconds": r.get("wall_seconds", 0),
            })

    lines = [f"{'arm':<14}{'n':>4}{'p_tok/task':>12}{'c_tok/task':>12}{'tok/task':>12}{'tok/success':>14}{'success':>10}"]
    lines.append("-" * 78)
    for arm in ("raw", "raw+schema", "harness"):
        rs = per_arm.get(arm, [])
        if not rs:
            continue
        n = len(rs)
        pt = sum(r["prompt_tokens_est"] for r in rs) / n
        ct = sum(r["completion_tokens_est"] for r in rs) / n
        tt = pt + ct
        succ = sum(1 for r in rs if r["success"]) / n
        tok_per_success = tt / succ if succ > 0 else float("inf")
        lines.append(f"{arm:<14}{n:>4}{pt:>12.0f}{ct:>12.0f}{tt:>12.0f}{tok_per_success:>14.0f}{succ:>10.2f}")

    lb = "\n".join(lines)
    print(lb)
    (out / "leaderboard.txt").write_text(lb)
    (out / "per_arm.json").write_text(json.dumps(per_arm, indent=2))


if __name__ == "__main__":
    main()
