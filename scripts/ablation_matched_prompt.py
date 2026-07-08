"""Matched-prompt ablation.

Three arms hitting the SAME model (claude-opus-4-7) on the SAME seeds:

  raw          — natural-language instruction only.
  raw+schema   — instruction + JSON schema + explicit field spec + forbidden list.
                 Prompt is as rich as the harness's prompt, but no gates run.
  harness      — the full LBAH runner (ledger + transport/proxy/reopen/verifier gates).

The interesting question is `harness vs raw+schema`. If they tie, the harness
is buying you prompt engineering. If harness wins, the gates are doing work
the prompt alone couldn't.
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

from lbah.adapters import ClaudeCodeCLIAdapter  # noqa: E402
from lbah.benches import load_suite  # noqa: E402
from lbah.core.runner import HarnessModules, LoadBearingHarness  # noqa: E402
from lbah.core.schemas import ActionProposal  # noqa: E402
from lbah.modules import (  # noqa: E402
    CommitmentController,
    ConcernMapper,
    ProxyAdversary,
    ReopenabilityGovernor,
    SurfaceMapper,
    TransportAuditor,
    Verifier,
)


MODEL = "claude-opus-4-7"


RAW_SYSTEM = (
    "You are a tool-using agent. Read the instruction and reply with ONE JSON "
    "action, no prose, no fences: "
    "{action_id, surface_id, action_type, payload, rationale, "
    "claimed_variables_used}. Choose a plausible surface_id (tool_call, "
    "memory_write, final_answer) for the task."
)


RAW_SCHEMA_SYSTEM = (
    "You are a tool-using agent. You will be given a task and a strict wrapper "
    "schema you must return. The wrapper is: "
    "{\"action_id\":\"<string>\",\"surface_id\":\"<string>\",\"action_type\":\"<string>\","
    "\"payload\":{...},\"rationale\":\"<string>\",\"claimed_variables_used\":[]}. "
    "The PAYLOAD is where you place the actual tool arguments (attendees, date, "
    "calendar, status, value, etc.). The tool schema tells you what keys go "
    "INSIDE payload, NOT what the outer wrapper looks like. Include every "
    "required payload field with its exact key name. Never invent fields. Never "
    "elaborate values (e.g. do NOT convert a weekday name to an ISO date). Never "
    "include values listed as forbidden. Return JSON only, no prose, no fences."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _claude_call(prompt: str, system: str, timeout: float = 120.0) -> str:
    proc = subprocess.run(
        [
            "claude", "-p", "--model", MODEL,
            "--output-format", "text",
            "--append-system-prompt", system,
            prompt,
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI: {proc.stderr[-400:]}")
    return proc.stdout


def _build_schema_prompt(task) -> str:
    """Build a schema-rich prompt using the same info the harness ledger uses,
    but delivered as a plain prompt (no gates)."""
    meta = task.metadata or {}
    surfaces = meta.get("surfaces", []) or []
    surface_id = surfaces[0]["id"] if surfaces else "final_answer"
    concern_vars = meta.get("concern_variables", []) or []
    forbidden_values = meta.get("forbidden_values", {})
    required_fields = meta.get("required_fields", [])
    tool_schemas = meta.get("tool_schemas", {})
    schema_hint = ""
    if tool_schemas:
        schema_hint = "\nSCHEMA:\n" + json.dumps(tool_schemas, indent=2)

    forbidden_hint = ""
    if forbidden_values:
        forbidden_hint = "\nFORBIDDEN_VALUES:\n" + json.dumps(forbidden_values, indent=2)

    required_hint = ""
    if required_fields:
        required_hint = "\nREQUIRED_FIELDS: " + ", ".join(required_fields)

    fields_pin = []
    for cv in concern_vars:
        if cv.get("concern", 0) >= 0.5 and cv.get("value") is not None:
            fields_pin.append({
                "id": cv["id"],
                "value": cv["value"],
                "must_appear_in": cv.get("required_surfaces", []),
            })
    fields_hint = "\nFIELDS_TO_PRESERVE:\n" + json.dumps(fields_pin, indent=2) if fields_pin else ""

    return (
        f"INSTRUCTION:\n{task.instruction}\n\n"
        f"OUTER surface_id (put in wrapper): {surface_id}\n"
        f"PAYLOAD schema (keys that go INSIDE the wrapper's payload field):"
        f"{schema_hint}\n"
        f"{required_hint}\n"
        f"{fields_hint}\n"
        f"{forbidden_hint}\n\n"
        "Return ONE JSON object with the WRAPPER shape "
        "{action_id, surface_id, action_type, payload, rationale, claimed_variables_used}. "
        "Put the tool arguments INSIDE `payload`. Values in FIELDS_TO_PRESERVE "
        "must appear in payload verbatim. Do NOT include any FORBIDDEN_VALUES."
    )


# ---------------------------------------------------------------------------
# Arm runners
# ---------------------------------------------------------------------------


def run_raw(task_ref: str) -> dict:
    suite_name, seed_str = task_ref.split(":", 1)
    suite = load_suite(suite_name)
    task = suite.generate(int(seed_str))
    env = suite.make_env()
    state = env.reset(task)
    t0 = time.time()
    try:
        text = _claude_call(task.instruction, RAW_SYSTEM)
    except Exception as exc:
        return {"mode": "raw", "task": task_ref, "final_success": False, "error": str(exc)}
    try:
        proposal = ActionProposal.model_validate(json.loads(_strip_fences(text)))
    except Exception as exc:
        return {"mode": "raw", "task": task_ref, "final_success": False, "error": f"bad_json: {exc}"}
    state = env.execute(proposal, state)
    success_fn = getattr(env, "success", None)
    final = bool(success_fn(state)) if callable(success_fn) else state.done
    return {
        "mode": "raw", "task": task_ref, "task_id": task.task_id,
        "final_success": final, "proposal": proposal.model_dump(),
        "wall_seconds": time.time() - t0,
    }


def run_raw_schema(task_ref: str) -> dict:
    suite_name, seed_str = task_ref.split(":", 1)
    suite = load_suite(suite_name)
    task = suite.generate(int(seed_str))
    env = suite.make_env()
    state = env.reset(task)
    prompt = _build_schema_prompt(task)
    t0 = time.time()
    try:
        text = _claude_call(prompt, RAW_SCHEMA_SYSTEM)
    except Exception as exc:
        return {"mode": "raw+schema", "task": task_ref, "final_success": False, "error": str(exc)}
    try:
        proposal = ActionProposal.model_validate(json.loads(_strip_fences(text)))
    except Exception as exc:
        return {"mode": "raw+schema", "task": task_ref, "final_success": False, "error": f"bad_json: {exc}"}
    state = env.execute(proposal, state)
    success_fn = getattr(env, "success", None)
    final = bool(success_fn(state)) if callable(success_fn) else state.done
    return {
        "mode": "raw+schema", "task": task_ref, "task_id": task.task_id,
        "final_success": final, "proposal": proposal.model_dump(),
        "wall_seconds": time.time() - t0,
    }


def run_harness(task_ref: str) -> dict:
    suite_name, seed_str = task_ref.split(":", 1)
    suite = load_suite(suite_name)
    task = suite.generate(int(seed_str))
    env = suite.make_env()
    agent = ClaudeCodeCLIAdapter(name="claude_opus_4_7", model=MODEL, timeout=120.0)
    modules = HarnessModules(
        concern_mapper=ConcernMapper(), surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(), proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(), commitment_controller=CommitmentController(),
    )
    harness = LoadBearingHarness(agent, env, modules, mode="guarded")
    t0 = time.time()
    try:
        result = harness.run(task)
    except Exception as exc:
        return {"mode": "harness", "task": task_ref, "final_success": False, "error": str(exc)}
    return {
        "mode": "harness", "task": task_ref, "task_id": task.task_id,
        "final_success": result.final_success,
        "load_score": result.load_score,
        "transport_score": result.transport_score,
        "proxy_resistance_score": result.proxy_resistance_score,
        "reopenability_score": result.reopenability_score,
        "commitment_validity_score": result.commitment_validity_score,
        "wall_seconds": time.time() - t0,
        "failed_gates": result.failed_gates,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


ARMS = {"raw": run_raw, "raw+schema": run_raw_schema, "harness": run_harness}


def _leaderboard(rows: list[dict]) -> str:
    header = f"{'mode':<14}{'n':>4}{'success':>10}{'wall_avg':>10}{'errors':>8}"
    lines = [header, "-" * len(header)]
    by_mode: dict[str, list[dict]] = {}
    for r in rows:
        by_mode.setdefault(r["mode"], []).append(r)
    for mode, rs in sorted(by_mode.items()):
        n = len(rs)
        success = sum(1 for r in rs if r.get("final_success")) / n
        wall = sum(r.get("wall_seconds", 0) for r in rs) / n
        errors = sum(1 for r in rs if r.get("error"))
        lines.append(f"{mode:<14}{n:>4}{success:>10.2f}{wall:>10.2f}{errors:>8}")
    return "\n".join(lines)


def _per_suite(rows: list[dict]) -> str:
    lines = [f"{'suite':<24}{'mode':<14}{'n':>4}{'success':>10}"]
    lines.append("-" * 52)
    by_key: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        suite = r["task"].split(":", 1)[0]
        by_key.setdefault((suite, r["mode"]), []).append(r)
    for (suite, mode), rs in sorted(by_key.items()):
        success = sum(1 for r in rs if r.get("final_success")) / len(rs)
        lines.append(f"{suite:<24}{mode:<14}{len(rs):>4}{success:>10.2f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suites", nargs="+", required=True, help="suite names")
    ap.add_argument("--seeds", type=int, default=110)
    ap.add_argument("--arms", nargs="+", default=list(ARMS.keys()))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tasks: list[str] = []
    for suite in args.suites:
        for seed in range(args.seeds):
            tasks.append(f"{suite}:{seed}")

    jobs = [(arm, t) for arm in args.arms for t in tasks]
    print(f"{len(jobs)} jobs = {len(args.arms)} arms x {len(tasks)} tasks; workers={args.workers}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stream = open(out / "results.jsonl", "w")

    results: list[dict] = []
    completed = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(ARMS[arm], t): (arm, t) for arm, t in jobs}
        for fut in cf.as_completed(futs):
            arm, t = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {"mode": arm, "task": t, "final_success": False, "error": f"exc: {exc}"}
            results.append(row)
            completed += 1
            if completed % 25 == 0 or completed <= 5 or completed == len(jobs):
                print(f"  [{completed}/{len(jobs)}] {row['mode']:<12} {row['task']:<25} "
                      f"success={row.get('final_success')} err={bool(row.get('error'))}")
            stream.write(json.dumps(row) + "\n")
            stream.flush()
    stream.close()

    lb = _leaderboard(results) + "\n\nPer-suite:\n" + _per_suite(results)
    print("\n" + lb)
    (out / "leaderboard.txt").write_text(lb)


if __name__ == "__main__":
    main()
