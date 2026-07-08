"""LBAH command-line interface.

Subcommands:

    lbah run        --task PATH.yaml --agent CFG.yaml --mode guarded --out DIR
    lbah bench      --suite NAME     --agent CFG.yaml --mode guarded --seeds N --out DIR
    lbah compare    --suite NAME     --agents A.yaml B.yaml ... --mode guarded --seeds N --out DIR
    lbah leaderboard DIR
    lbah replay     PATH.json
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

import click
import yaml

from .adapters import (
    CLIAgentAdapter,
    ClaudeCodeCLIAdapter,
    ConcernMoERouter,
    DummyAgent,
    HTTPAgentAdapter,
    LocalLLMAdapter,
    OracleAgent,
    ProviderLLMAdapter,
)
from .adapters.moe_router import Expert
from .benches import SUITES, load_suite
from .core.runner import HarnessModules, LoadBearingHarness
from .core.schemas import TaskSpec
from .environments.base import Environment
from .environments.browser_env import BrowserEnv
from .environments.coding_env import CodingEnv
from .environments.memory_env import MemoryEnv
from .environments.retrieval_env import RetrievalEnv
from .environments.tool_use_env import ToolUseEnv
from .modules import (
    CommitmentController,
    ConcernMapper,
    ProxyAdversary,
    ReopenabilityGovernor,
    SurfaceMapper,
    TransportAuditor,
    Verifier,
)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_yaml(path: str | os.PathLike) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _build_agent_from_config(cfg: dict) -> Any:
    kind = cfg.get("type", "dummy")
    if kind == "dummy":
        return DummyAgent(
            name=cfg.get("name", "dummy"),
            policy=cfg.get("policy", "first_slot"),
            seed=int(cfg.get("seed", 0)),
        )
    if kind == "oracle":
        agent = OracleAgent()
        agent.name = cfg.get("name", "oracle")
        return agent
    if kind == "local_llm":
        return LocalLLMAdapter(
            name=cfg.get("name", "local"),
            url=cfg["url"],
            model=cfg.get("model", "local"),
            api_key=cfg.get("api_key"),
            temperature=float(cfg.get("temperature", 0.0)),
            max_tokens=int(cfg.get("max_tokens", 2048)),
        )
    if kind == "provider_llm":
        return ProviderLLMAdapter(
            name=cfg.get("name", "provider"),
            model=cfg.get("model", "claude-opus-4-8"),
            api_key=cfg.get("api_key"),
            temperature=float(cfg.get("temperature", 0.0)),
            max_tokens=int(cfg.get("max_tokens", 2048)),
        )
    if kind == "cli_agent":
        return CLIAgentAdapter(
            name=cfg.get("name", "cli"),
            command=cfg["command"],
            cwd=cfg.get("cwd"),
            timeout=float(cfg.get("timeout", 120)),
        )
    if kind == "http_agent":
        return HTTPAgentAdapter(
            name=cfg.get("name", "http"),
            url=cfg["url"],
            headers=cfg.get("headers") or {},
            timeout=float(cfg.get("timeout", 120)),
        )
    if kind == "claude_code_cli":
        return ClaudeCodeCLIAdapter(
            name=cfg.get("name", "claude_cli"),
            model=cfg.get("model", "claude-opus-4-7"),
            timeout=float(cfg.get("timeout", 90)),
            extra_args=cfg.get("extra_args") or [],
        )
    if kind == "moe_router":
        experts: list[Expert] = []
        for entry in cfg["experts"]:
            expert_agent = _build_agent_from_config(entry)
            experts.append(
                Expert(
                    key=entry["key"],
                    agent=expert_agent,
                    competences=entry.get("competences") or {},
                    cost=float(entry.get("cost", 1.0)),
                )
            )
        return ConcernMoERouter(
            name=cfg.get("name", "moe"),
            experts=experts,
            default_expert=cfg.get("default_expert"),
        )
    raise ValueError(f"unknown agent type '{kind}'")


def _env_for_task(task: TaskSpec) -> Environment:
    return {
        "coding": CodingEnv,
        "tool_use": ToolUseEnv,
        "research": RetrievalEnv,
        "browser": BrowserEnv,
        "memory": MemoryEnv,
        "multi_step": ToolUseEnv,
        "custom": ToolUseEnv,
    }[task.task_type]()


def _load_task(task_arg: str) -> TaskSpec:
    """Accept a YAML/JSON path or a spec `suite:seed`."""
    if ":" in task_arg and not os.path.exists(task_arg):
        suite_name, seed_str = task_arg.split(":", 1)
        suite = load_suite(suite_name)
        return suite.generate(int(seed_str))
    data = _load_yaml(task_arg)
    return TaskSpec.model_validate(data)


def _build_harness(agent: Any, env: Environment, mode: str, thresholds: dict) -> LoadBearingHarness:
    modules = HarnessModules(
        concern_mapper=ConcernMapper(),
        surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(),
        proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(),
        commitment_controller=CommitmentController(thresholds=thresholds),
    )
    return LoadBearingHarness(agent, env, modules, mode=mode, thresholds=thresholds)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.group(help="LBAH — Load-Bearing Agent Harness")
def cli() -> None:
    pass


@cli.command()
@click.option("--task", "task_arg", required=True, help="Path to task YAML/JSON or 'suite:seed'.")
@click.option("--agent", "agent_cfg", required=True, help="Path to agent YAML config.")
@click.option("--mode", default="guarded", type=click.Choice(["guarded", "audit"]))
@click.option("--out", "out_dir", required=True, help="Directory to write run artifacts.")
def run(task_arg: str, agent_cfg: str, mode: str, out_dir: str) -> None:
    """Run a single task through the harness."""
    task = _load_task(task_arg)
    cfg = _load_yaml(agent_cfg)
    agent = _build_agent_from_config(cfg)
    env = _env_for_task(task)
    harness = _build_harness(agent, env, mode, cfg.get("thresholds") or {})

    result = harness.run(task)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "run.json").write_text(result.model_dump_json(indent=2))

    click.echo(
        f"[{agent.name} on {task.task_id}] final_success={result.final_success} "
        f"load={result.load_score:.2f} transport={result.transport_score:.2f} "
        f"proxy={result.proxy_resistance_score:.2f} reopen={result.reopenability_score:.2f}"
    )


@cli.command()
@click.option("--suite", required=True, type=click.Choice(sorted(SUITES.keys())))
@click.option("--agent", "agent_cfg", required=True)
@click.option("--mode", default="guarded", type=click.Choice(["guarded", "audit"]))
@click.option("--seeds", default=16, type=int)
@click.option("--out", "out_dir", required=True)
def bench(suite: str, agent_cfg: str, mode: str, seeds: int, out_dir: str) -> None:
    """Run a whole benchmark suite over N seeds."""
    suite_mod = load_suite(suite)
    cfg = _load_yaml(agent_cfg)
    agent = _build_agent_from_config(cfg)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    jsonl_path = Path(out_dir) / "runs.jsonl"
    stats: list[dict] = []
    with open(jsonl_path, "w") as fh:
        for seed in range(seeds):
            task = suite_mod.generate(seed)
            env = suite_mod.make_env()
            harness = _build_harness(agent, env, mode, cfg.get("thresholds") or {})
            result = harness.run(task)
            row = {
                "run_id": f"{suite}_{cfg.get('name','agent')}_{seed}",
                "task_id": task.task_id,
                "agent": agent.name,
                "mode": mode,
                "final_success": result.final_success,
                "load_score": result.load_score,
                "behavior_score": result.behavior_score,
                "transport_score": result.transport_score,
                "proxy_resistance_score": result.proxy_resistance_score,
                "reopenability_score": result.reopenability_score,
                "commitment_validity_score": result.commitment_validity_score,
                "tokens": result.tokens,
                "wall_time_seconds": result.wall_time_seconds,
                "failed_gates": result.failed_gates,
            }
            stats.append(row)
            fh.write(json.dumps(row) + "\n")

    _write_summary(out_dir, suite, agent.name, mode, stats)
    click.echo(_summary_table([{"agent": agent.name, "mode": mode, "rows": stats}]))


@cli.command(context_settings={"ignore_unknown_options": True})
@click.option("--suite", required=True, type=click.Choice(sorted(SUITES.keys())))
@click.option("--agents", "agents_flag", default="", help="Comma or space-separated list of agent configs.")
@click.option("--mode", default="guarded")
@click.option("--seeds", default=16, type=int)
@click.option("--out", "out_dir", required=True)
@click.argument("agent_positional", nargs=-1, type=click.UNPROCESSED)
def compare(
    suite: str,
    agents_flag: str,
    mode: str,
    seeds: int,
    out_dir: str,
    agent_positional: tuple[str, ...],
) -> None:
    """Compare multiple agents on the same suite/seeds."""
    agent_cfgs: list[str] = []
    if agents_flag:
        agent_cfgs.extend(x for x in agents_flag.replace(",", " ").split() if x)
    agent_cfgs.extend(agent_positional)
    if not agent_cfgs:
        raise click.ClickException("provide agent configs via --agents or as positional args")
    modes = mode.split(",")
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    combined: list[dict] = []
    for agent_cfg in agent_cfgs:
        cfg = _load_yaml(agent_cfg)
        agent = _build_agent_from_config(cfg)
        for m in modes:
            suite_mod = load_suite(suite)
            rows: list[dict] = []
            for seed in range(seeds):
                task = suite_mod.generate(seed)
                env = suite_mod.make_env()
                harness = _build_harness(agent, env, m, cfg.get("thresholds") or {})
                result = harness.run(task)
                row = {
                    "run_id": f"{suite}_{agent.name}_{m}_{seed}",
                    "agent": agent.name,
                    "mode": m,
                    "task_id": task.task_id,
                    "final_success": result.final_success,
                    "load_score": result.load_score,
                    "transport_score": result.transport_score,
                    "proxy_resistance_score": result.proxy_resistance_score,
                    "reopenability_score": result.reopenability_score,
                    "commitment_validity_score": result.commitment_validity_score,
                    "behavior_score": result.behavior_score,
                    "tokens": result.tokens,
                    "wall_time_seconds": result.wall_time_seconds,
                    "failed_gates": result.failed_gates,
                }
                rows.append(row)
                all_rows.append(row)
            combined.append({"agent": agent.name, "mode": m, "rows": rows})

    (Path(out_dir) / "runs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in all_rows) + "\n"
    )
    _write_summary(out_dir, suite, "compare", mode, all_rows)
    click.echo(_summary_table(combined))


@cli.command()
@click.argument("run_dir", type=click.Path(exists=True))
def leaderboard(run_dir: str) -> None:
    """Aggregate a comparison directory into a leaderboard table."""
    rows: list[dict] = []
    jsonl = Path(run_dir) / "runs.jsonl"
    if not jsonl.exists():
        raise click.ClickException(f"no runs.jsonl in {run_dir}")
    with open(jsonl) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["agent"], r["mode"]), []).append(r)

    click.echo(_summary_table(
        [{"agent": a, "mode": m, "rows": rs} for (a, m), rs in sorted(groups.items())]
    ))


@cli.command()
@click.argument("run_path", type=click.Path(exists=True))
def replay(run_path: str) -> None:
    """Print certificates from a saved RunResult."""
    data = json.loads(Path(run_path).read_text())
    click.echo(f"Task: {data['task_id']}   Agent: {data['agent']}   Mode: {data['mode']}")
    click.echo(f"final_success={data['final_success']}   load_score={data['load_score']:.2f}")
    for i, cert in enumerate(data.get("certificates", [])):
        click.echo(f"\n--- step {i} [{cert['decision']}] load={cert['load_score']:.2f} ---")
        click.echo(f"  summary: {cert['summary']}")
        for group in ("transport_results", "proxy_results", "reopenability_results", "validator_results"):
            for r in cert.get(group, []):
                mark = "OK " if r["passed"] else "FAIL"
                click.echo(f"    {mark} {r['gate_name']}: {r['reason']}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mean(rows: list[dict], key: str) -> float:
    vals = [r[key] for r in rows if key in r and r[key] is not None]
    if not vals:
        return 0.0
    return statistics.fmean(vals)


def _rate(rows: list[dict], key: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.get(key)) / len(rows)


def _summary_table(groups: list[dict]) -> str:
    header = f"{'agent':<24}{'mode':<10}{'final':>8}{'load':>8}{'transport':>12}{'proxy':>8}{'reopen':>8}{'validity':>10}{'tokens':>8}"
    lines = [header, "-" * len(header)]
    for g in groups:
        rows = g["rows"]
        lines.append(
            f"{g['agent']:<24}{g['mode']:<10}"
            f"{_rate(rows, 'final_success'):>8.2f}"
            f"{_mean(rows, 'load_score'):>8.2f}"
            f"{_mean(rows, 'transport_score'):>12.2f}"
            f"{_mean(rows, 'proxy_resistance_score'):>8.2f}"
            f"{_mean(rows, 'reopenability_score'):>8.2f}"
            f"{_mean(rows, 'commitment_validity_score'):>10.2f}"
            f"{int(_mean(rows, 'tokens')):>8}"
        )
    return "\n".join(lines)


def _write_summary(out_dir: str, suite: str, agent: str, mode: str, rows: list[dict]) -> None:
    summary = {
        "suite": suite,
        "agent": agent,
        "mode": mode,
        "n": len(rows),
        "final_success_rate": _rate(rows, "final_success"),
        "load_score_mean": _mean(rows, "load_score"),
        "transport_score_mean": _mean(rows, "transport_score"),
        "proxy_resistance_mean": _mean(rows, "proxy_resistance_score"),
        "reopenability_mean": _mean(rows, "reopenability_score"),
        "commitment_validity_mean": _mean(rows, "commitment_validity_score"),
        "behavior_mean": _mean(rows, "behavior_score"),
        "tokens_mean": _mean(rows, "tokens"),
    }
    (Path(out_dir) / "summary.json").write_text(json.dumps(summary, indent=2))


def main(argv: list[str] | None = None) -> None:
    cli.main(args=argv, standalone_mode=True)


if __name__ == "__main__":
    main(sys.argv[1:])
