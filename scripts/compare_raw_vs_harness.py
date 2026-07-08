"""Compare raw Claude Opus 4.7 vs the same model driven through LBAH.

Both modes hit the same suite:seed tasks. The raw mode calls `claude -p` once
per task with just the instruction. The harness mode instantiates the full
LBAH runner with a ClaudeCodeCLIAdapter as the actor. Tasks run in parallel.

Usage:
    python scripts/compare_raw_vs_harness.py --tasks moved_bottleneck:3 tool_constraints:1 \
        --workers 4 --out runs/compare_claude/
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


# ---------------------------------------------------------------------------
# Raw mode: one shot to `claude -p` with only the task instruction.
# ---------------------------------------------------------------------------


RAW_SYSTEM = (
    "You are a tool-using agent. Read the instruction and reply with ONE JSON "
    "action, no prose, no fences: "
    "{action_id, surface_id, action_type, payload, rationale, "
    "claimed_variables_used}. Choose a plausible surface_id (tool_call, "
    "memory_write, final_answer) for the task."
)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _claude_call(prompt: str, system: str, timeout: float = 90.0) -> str:
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
        raise RuntimeError(f"claude CLI failed: {proc.stderr[-400:]}")
    return proc.stdout


def run_raw(task_ref: str) -> dict:
    suite_name, seed_str = task_ref.split(":", 1)
    suite = load_suite(suite_name)
    task = suite.generate(int(seed_str))
    env = suite.make_env()
    state = env.reset(task)
    t0 = time.time()
    raw_text = _claude_call(task.instruction, RAW_SYSTEM)
    try:
        proposal = ActionProposal.model_validate(json.loads(_strip_fences(raw_text)))
    except Exception as exc:
        return {
            "mode": "raw",
            "task": task_ref,
            "task_id": task.task_id,
            "final_success": False,
            "error": f"bad_json: {exc}",
            "wall_seconds": time.time() - t0,
        }
    state = env.execute(proposal, state)
    success_fn = getattr(env, "success", None)
    final = bool(success_fn(state)) if callable(success_fn) else state.done
    return {
        "mode": "raw",
        "task": task_ref,
        "task_id": task.task_id,
        "final_success": final,
        "proposal": proposal.model_dump(),
        "wall_seconds": time.time() - t0,
    }


# ---------------------------------------------------------------------------
# Harness mode: LoadBearingHarness + ClaudeCodeCLIAdapter.
# ---------------------------------------------------------------------------


def _make_harness(agent, env, mode: str = "guarded") -> LoadBearingHarness:
    modules = HarnessModules(
        concern_mapper=ConcernMapper(),
        surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(),
        proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(),
        commitment_controller=CommitmentController(),
    )
    return LoadBearingHarness(agent, env, modules, mode=mode)


def run_harness(task_ref: str) -> dict:
    suite_name, seed_str = task_ref.split(":", 1)
    suite = load_suite(suite_name)
    task = suite.generate(int(seed_str))
    env = suite.make_env()
    agent = ClaudeCodeCLIAdapter(name="claude_opus_4_7", model=MODEL, timeout=90.0)
    harness = _make_harness(agent, env)
    t0 = time.time()
    result = harness.run(task)
    return {
        "mode": "harness",
        "task": task_ref,
        "task_id": task.task_id,
        "final_success": result.final_success,
        "load_score": result.load_score,
        "transport_score": result.transport_score,
        "proxy_resistance_score": result.proxy_resistance_score,
        "reopenability_score": result.reopenability_score,
        "commitment_validity_score": result.commitment_validity_score,
        "wall_seconds": time.time() - t0,
        "failed_gates": result.failed_gates,
        "certificates": [c.model_dump() for c in result.certificates],
    }


# ---------------------------------------------------------------------------
# Parallel driver + reporting
# ---------------------------------------------------------------------------


def _leaderboard(rows: list[dict]) -> str:
    header = f"{'mode':<10}{'n':>4}{'success':>10}{'wall_avg':>10}"
    lines = [header, "-" * len(header)]
    by_mode: dict[str, list[dict]] = {}
    for r in rows:
        by_mode.setdefault(r["mode"], []).append(r)
    for mode, rs in by_mode.items():
        success = sum(1 for r in rs if r.get("final_success")) / len(rs)
        wall = sum(r.get("wall_seconds", 0) for r in rs) / len(rs)
        lines.append(f"{mode:<10}{len(rs):>4}{success:>10.2f}{wall:>10.2f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", required=True, help="suite:seed refs")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, str]] = []
    for t in args.tasks:
        jobs.append(("raw", t))
        jobs.append(("harness", t))

    print(f"Running {len(jobs)} jobs in parallel (workers={args.workers})...")
    results: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(run_raw if mode == "raw" else run_harness, t): (mode, t)
            for mode, t in jobs
        }
        for i, fut in enumerate(cf.as_completed(futs), 1):
            mode, t = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {
                    "mode": mode, "task": t, "final_success": False,
                    "error": f"exception: {exc}",
                }
            results.append(row)
            print(
                f"[{i}/{len(jobs)}] {row['mode']:<8} {row['task']:<30} "
                f"success={row.get('final_success')} "
                f"wall={row.get('wall_seconds', 0):.1f}s"
            )

    (out / "results.jsonl").write_text("\n".join(json.dumps(r) for r in results) + "\n")
    print("\n" + _leaderboard(results))
    (out / "leaderboard.txt").write_text(_leaderboard(results))


if __name__ == "__main__":
    main()
