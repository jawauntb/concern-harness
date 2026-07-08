"""BFCL v3 Simple: public tool-calling benchmark.

Three arms:
  raw          — question only, "call the function"
  raw+schema   — question + tool schema (JSONSchema-like)
  harness      — LBAH ledger: schema + required fields + concern variables
                 derived from the user question's entities + gates on top.

Scoring per BFCL convention: for each parameter, the model's value must be
in `ground_truth[param]`. All required params must be present. Values compared
case-insensitively for strings (BFCL's own AST scorer normalizes).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MODEL = "claude-opus-4-7"


RAW_SYSTEM = (
    "You are a tool-using agent. Emit exactly one JSON tool call, no prose, "
    "no fences: {\"name\": \"<function_name>\", \"args\": {...}}. Match the "
    "expected function name and provide all required arguments."
)


HARNESS_SYSTEM = (
    "You are the actor inside a Load-Bearing Agent Harness. Emit exactly one "
    "JSON action, no prose, no fences: {\"name\": \"<function_name>\", "
    "\"args\": {...}}. The CONCERN LEDGER pins which arguments must appear "
    "and with which values. Do not invent extra fields."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _claude(prompt: str, system: str, timeout: float = 60.0) -> str:
    proc = subprocess.run(
        ["claude", "-p", "--model", MODEL, "--output-format", "text",
         "--append-system-prompt", system, prompt],
        text=True, capture_output=True, timeout=timeout, check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI: {proc.stderr[-400:]}")
    return proc.stdout


# ---------------------------------------------------------------------------
# Load instances
# ---------------------------------------------------------------------------


def _read_jsonl_or_json(path: str) -> list[dict]:
    text = Path(path).read_text().strip()
    if text.startswith("["):
        return json.loads(text)
    # JSON Lines
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def load_bfcl(questions_path: str, answers_path: str, n: int, offset: int = 0) -> list[dict]:
    qs = _read_jsonl_or_json(questions_path)
    ans = {a["id"]: a for a in _read_jsonl_or_json(answers_path)}
    out: list[dict] = []
    for q in qs[offset : offset + n]:
        gid = q["id"]
        gt = ans.get(gid, {}).get("ground_truth", [])
        out.append({"id": gid, "question": q["question"], "function": q["function"], "gt": gt})
    return out


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _norm(v):
    if isinstance(v, str):
        return v.strip().lower()
    return v


def score(prediction: dict, gt_list: list) -> dict:
    """BFCL-style scoring: prediction must call the expected function name
    with argument values that appear in the ground-truth accepted values.
    """
    if not gt_list:
        return {"passed": False, "reason": "no ground truth"}
    gt = gt_list[0]  # first (and typically only) gold function
    gt_name = list(gt.keys())[0]
    gt_args = gt[gt_name]

    pred_name = prediction.get("name")
    pred_args = prediction.get("args") or prediction.get("arguments") or {}
    if pred_name != gt_name:
        return {"passed": False, "reason": f"name mismatch: got {pred_name!r} want {gt_name!r}"}
    for param, accepted in gt_args.items():
        p = pred_args.get(param)
        if p is None:
            # BFCL treats missing optional params as pass if any accepted value is "" or None
            if "" in accepted or None in accepted:
                continue
            return {"passed": False, "reason": f"missing arg {param}"}
        pn = _norm(p)
        accepted_n = [_norm(a) for a in accepted]
        if pn not in accepted_n:
            return {"passed": False, "reason": f"arg {param}: got {p!r} not in accepted {accepted!r}"}
    return {"passed": True, "reason": "ok"}


# ---------------------------------------------------------------------------
# Arm builders
# ---------------------------------------------------------------------------


def _extract_user_content(q):
    if isinstance(q, list) and q and isinstance(q[0], list):
        for msg in q[0]:
            if msg.get("role") == "user":
                return msg.get("content", "")
    return ""


def raw_prompt(inst) -> tuple[str, str]:
    user = _extract_user_content(inst["question"])
    fn = inst["function"][0] if inst["function"] else {}
    prompt = (
        f"USER: {user}\n\n"
        f"FUNCTION AVAILABLE: {fn.get('name', '?')} — {fn.get('description', '')}\n"
        "Call the function with the correct arguments. Emit ONE JSON object: "
        "{\"name\": \"<function_name>\", \"args\": {...}}. No prose."
    )
    return prompt, RAW_SYSTEM


def raw_schema_prompt(inst) -> tuple[str, str]:
    user = _extract_user_content(inst["question"])
    fn = inst["function"][0] if inst["function"] else {}
    prompt = (
        f"USER: {user}\n\n"
        f"FUNCTION SCHEMA:\n{json.dumps(fn, indent=2)}\n\n"
        "Emit ONE JSON object matching {\"name\": \"<function_name>\", "
        "\"args\": {...}}. Use exact key names from the schema. Include every "
        "required argument. Do not add extra keys."
    )
    return prompt, RAW_SYSTEM


def harness_prompt(inst) -> tuple[str, str]:
    user = _extract_user_content(inst["question"])
    fn = inst["function"][0] if inst["function"] else {}
    # Derive concern variables: every required parameter is a high-concern
    # transport variable whose value is *not* pinned (must be inferred from
    # the user question).
    required = (fn.get("parameters") or {}).get("required", [])
    concern_vars = []
    for r in required:
        prop = ((fn.get("parameters") or {}).get("properties") or {}).get(r, {})
        concern_vars.append({
            "id": r,
            "concern": 1.0,
            "type": prop.get("type"),
            "description": prop.get("description", ""),
            "required_surface": "tool_call",
        })
    ledger = {
        "target_function": fn.get("name"),
        "concern_variables": concern_vars,
        "no_extra_fields": True,
        "match_mode": "exact_leaf",
    }
    prompt = (
        f"USER: {user}\n\n"
        f"FUNCTION SCHEMA:\n{json.dumps(fn, indent=2)}\n\n"
        f"CONCERN LEDGER:\n{json.dumps(ledger, indent=2)}\n\n"
        "Emit ONE JSON object: {\"name\": \"<function_name>\", \"args\": {...}}. "
        "Every high-concern variable must appear in args with the correct value "
        "extracted from the USER message. Do not invent fields."
    )
    return prompt, HARNESS_SYSTEM


def run_arm(inst: dict, arm: str) -> dict:
    if arm == "raw":
        prompt, sys_p = raw_prompt(inst)
    elif arm == "raw+schema":
        prompt, sys_p = raw_schema_prompt(inst)
    elif arm == "harness":
        prompt, sys_p = harness_prompt(inst)
    else:
        return {"id": inst["id"], "arm": arm, "error": f"unknown arm {arm}"}

    t0 = time.time()
    try:
        text = _claude(prompt, sys_p, timeout=60.0)
    except Exception as exc:
        return {"id": inst["id"], "arm": arm, "error": str(exc), "wall_seconds": time.time() - t0}
    try:
        pred = json.loads(_strip_fences(text))
    except json.JSONDecodeError as exc:
        return {"id": inst["id"], "arm": arm, "error": f"bad_json: {exc}", "raw": text[:400], "wall_seconds": time.time() - t0}
    scored = score(pred, inst["gt"])
    return {
        "id": inst["id"],
        "arm": arm,
        "prediction": pred,
        "passed": scored["passed"],
        "reason": scored["reason"],
        "wall_seconds": time.time() - t0,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default="/tmp/bfcl/simple.json")
    ap.add_argument("--answers", default="/tmp/bfcl/simple_answer.json")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--arms", nargs="+", default=["raw", "raw+schema", "harness"])
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stream = open(out / "results.jsonl", "w")

    insts = load_bfcl(args.questions, args.answers, args.n, args.offset)
    print(f"loaded {len(insts)} instances")

    jobs = [(arm, inst) for arm in args.arms for inst in insts]
    print(f"{len(jobs)} jobs = {len(args.arms)} arms x {len(insts)} tasks; workers={args.workers}")

    results: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_arm, i, a): (a, i["id"]) for a, i in jobs}
        done = 0
        for fut in cf.as_completed(futs):
            try:
                row = fut.result()
            except Exception as exc:
                a, iid = futs[fut]
                row = {"id": iid, "arm": a, "error": str(exc)}
            results.append(row)
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            done += 1
            if done % 25 == 0 or done <= 5 or done == len(jobs):
                print(f"  [{done}/{len(jobs)}] {row.get('arm'):<12} {row.get('id'):<20} passed={row.get('passed')} err={bool(row.get('error'))}")
    stream.close()

    # Leaderboard
    lines = [f"{'arm':<14}{'n':>5}{'success':>10}{'wall':>8}{'errors':>8}"]
    lines.append("-" * 45)
    by_arm: dict[str, list[dict]] = {}
    for r in results:
        by_arm.setdefault(r["arm"], []).append(r)
    for arm in sorted(by_arm.keys()):
        rs = by_arm[arm]
        n = len(rs)
        succ = sum(1 for r in rs if r.get("passed")) / n
        wall = sum(r.get("wall_seconds", 0) for r in rs) / n
        errors = sum(1 for r in rs if r.get("error"))
        lines.append(f"{arm:<14}{n:>5}{succ:>10.2f}{wall:>8.1f}{errors:>8}")

    lb = "\n".join(lines)
    print("\n" + lb)
    (out / "leaderboard.txt").write_text(lb)


if __name__ == "__main__":
    main()
