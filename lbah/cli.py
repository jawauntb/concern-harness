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
from typing import Any, cast

import click
import yaml

from .adapters import (
    CLIAgentAdapter,
    ClaudeCodeCLIAdapter,
    ConcernMoERouter,
    DummyAgent,
    EchoModel,
    HTTPAgentAdapter,
    LocalLLMAdapter,
    OpenAICompatibleHarnessAdapter,
    OracleAgent,
    ProviderLLMAdapter,
)
from .adapters.moe_router import Expert
from .benches import SUITES, load_suite
from .core.runner import HarnessModules, LoadBearingHarness
from .core.schemas import TaskSpec
from .core.diagnostics import (
    improvement_proposals,
    markdown_report,
    read_jsonl,
    summarize_runs,
)
from .coding import (
    CodingHarnessRunner,
    CodingTask,
    CodingWorkspace,
    ModelCodingAgent,
    SWEBenchBackendKind,
    SWEBenchCacheLevel,
    SWEBenchEvaluationOptions,
    SWEBenchExecutionBackend,
    SWEBenchOfficialHarnessSpec,
    ScriptedCodingAgent,
    load_swebench_instances,
    run_swebench_smoke_suite,
    write_official_swebench_inputs,
    write_swebench_subset_manifests,
)
from .coding.actions import CodingAction
from .coding.runner import load_coding_task
from .environments.base import Environment
from .environments.browser_env import BrowserEnv
from .environments.coding_env import CodingEnv
from .environments.memory_env import MemoryEnv
from .environments.retrieval_env import RetrievalEnv
from .environments.tool_use_env import ToolUseEnv
from .modules import (
    CommitmentController,
    ConcernMapper,
    LLMConcernMapper,
    MetadataConcernMapper,
    OrchestrationAuditor,
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


def _load_scripted_coding_agent(path: str | os.PathLike) -> ScriptedCodingAgent:
    with open(path) as f:
        data: Any = yaml.safe_load(f) or {}
    if isinstance(data, list):
        actions_raw = data
        name = "scripted_coder"
    elif isinstance(data, dict):
        actions_raw = data.get("actions", [])
        name = data.get("name", "scripted_coder")
    else:
        actions_raw = []
        name = "scripted_coder"
    if not isinstance(actions_raw, list):
        raise ValueError("scripted coding agent file must contain an actions list")
    actions = [CodingAction.model_validate(action) for action in actions_raw]
    return ScriptedCodingAgent(actions=actions, name=name)


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
    if kind in {"openai_harness", "fugu", "external_openai_harness"}:
        return OpenAICompatibleHarnessAdapter(
            name=cfg.get("name", kind),
            base_url=cfg["base_url"],
            model=cfg["model"],
            api_key=cfg.get("api_key") or os.environ.get(cfg.get("api_key_env", "")),
            endpoint_path=cfg.get("endpoint_path", "/v1/chat/completions"),
            headers=cfg.get("headers") or {},
            timeout=float(cfg.get("timeout", 300)),
            temperature=float(cfg.get("temperature", 0.0)),
            max_tokens=int(cfg.get("max_tokens", 4096)),
            system_prompt=cfg.get("system_prompt"),
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


def _mode_defaults(mode: str) -> dict[str, Any]:
    """Load optional gauge defaults from configs/{mode}_mode.yaml if present."""
    path = Path(__file__).resolve().parents[1] / "configs" / f"{mode}_mode.yaml"
    if not path.exists():
        return {}
    data = _load_yaml(path)
    return {
        k: data[k]
        for k in ("gauge_probe_budget", "gauge_min_concern", "thresholds")
        if k in data
    }


def _build_concern_mapper(
    kind: str = "default",
    *,
    mapper_model_cfg: str | None = None,
    prefer_metadata: bool = True,
) -> Any:
    """Build a concern mapper; ``llm`` uses ProviderLLMAdapter or EchoModel."""
    if kind == "metadata":
        return MetadataConcernMapper()
    if kind == "default":
        return ConcernMapper()
    if kind != "llm":
        raise click.ClickException(f"unknown concern mapper: {kind}")
    if mapper_model_cfg:
        cfg = _load_yaml(mapper_model_cfg)
        model = _build_agent_from_config(cfg)
        if not hasattr(model, "complete"):
            raise click.ClickException(
                "mapper model config must expose a ModelAdapter.complete()"
            )
    else:
        # Deterministic stand-in for CI / offline runs.
        model = EchoModel(
            name="echo_concern_mapper",
            canned={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "concern_variables": [
                                        {
                                            "id": "echo_placeholder",
                                            "name": "echo placeholder",
                                            "value": None,
                                            "concern": 0.5,
                                            "source": "echo",
                                            "required_surfaces": ["final_answer"],
                                            "proxy_risks": [],
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )
    return LLMConcernMapper(model, prefer_metadata=prefer_metadata)


def _build_harness(
    agent: Any,
    env: Environment,
    mode: str,
    thresholds: dict,
    *,
    gauge_probe_budget: int = 0,
    gauge_min_concern: float = 0.5,
    concern_mapper: Any | None = None,
) -> LoadBearingHarness:
    modules = HarnessModules(
        concern_mapper=concern_mapper or ConcernMapper(),
        surface_mapper=SurfaceMapper(),
        transport_auditor=TransportAuditor(),
        orchestration_auditor=OrchestrationAuditor(),
        proxy_adversary=ProxyAdversary(),
        reopenability_governor=ReopenabilityGovernor(),
        verifier=Verifier(),
        commitment_controller=CommitmentController(thresholds=thresholds),
    )
    return LoadBearingHarness(
        agent,
        env,
        modules,
        mode=mode,
        thresholds=thresholds,
        gauge_probe_budget=gauge_probe_budget,
        gauge_min_concern=gauge_min_concern,
    )


def _resolve_gauge(
    mode: str,
    gauge_budget: int | None,
    gauge_min_concern: float | None,
    agent_thresholds: dict | None = None,
) -> tuple[dict, int, float]:
    """Merge mode-YAML defaults with CLI overrides (CLI wins when set)."""
    defaults = _mode_defaults(mode)
    thresholds = {
        **(defaults.get("thresholds") or {}),
        **(agent_thresholds or {}),
    }
    budget = (
        gauge_budget
        if gauge_budget is not None
        else int(defaults.get("gauge_probe_budget", 0))
    )
    min_concern = (
        gauge_min_concern
        if gauge_min_concern is not None
        else float(defaults.get("gauge_min_concern", 0.5))
    )
    return thresholds, budget, min_concern


def _run_result_row(
    *,
    run_id: str,
    task_id: str,
    agent: str,
    mode: str,
    result: Any,
) -> dict[str, Any]:
    """Serialize a RunResult with 100% per-component score coverage."""
    return {
        "run_id": run_id,
        "task_id": task_id,
        "agent": agent,
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
        "gauge_gate_count": sum(
            1
            for c in result.certificates
            for _ in c.gauge_results
        ),
    }


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
@click.option(
    "--gauge-budget",
    default=None,
    type=int,
    help="Top-N concern vars to gauge-probe per step (default: mode YAML, else 0).",
)
@click.option(
    "--gauge-min-concern",
    default=None,
    type=float,
    help="Minimum concern weight for gauge probing (default: mode YAML, else 0.5).",
)
@click.option(
    "--concern-mapper",
    "concern_mapper_kind",
    default="default",
    type=click.Choice(["default", "metadata", "llm"]),
    help="Concern mapper backend (llm reads lbah/prompts/concern_mapper.txt).",
)
@click.option(
    "--mapper-model",
    "mapper_model_cfg",
    default=None,
    help="Optional model YAML for --concern-mapper llm (else EchoModel).",
)
@click.option(
    "--mapper-force-llm/--mapper-prefer-metadata",
    default=False,
    help="When using llm mapper, ignore hand-authored metadata.concern_variables.",
)
def run(
    task_arg: str,
    agent_cfg: str,
    mode: str,
    out_dir: str,
    gauge_budget: int | None,
    gauge_min_concern: float | None,
    concern_mapper_kind: str,
    mapper_model_cfg: str | None,
    mapper_force_llm: bool,
) -> None:
    """Run a single task through the harness."""
    task = _load_task(task_arg)
    cfg = _load_yaml(agent_cfg)
    agent = _build_agent_from_config(cfg)
    env = _env_for_task(task)
    thresholds, budget, min_concern = _resolve_gauge(
        mode, gauge_budget, gauge_min_concern, cfg.get("thresholds") or {}
    )
    mapper = _build_concern_mapper(
        concern_mapper_kind,
        mapper_model_cfg=mapper_model_cfg,
        prefer_metadata=not mapper_force_llm,
    )
    harness = _build_harness(
        agent,
        env,
        mode,
        thresholds,
        gauge_probe_budget=budget,
        gauge_min_concern=min_concern,
        concern_mapper=mapper,
    )

    result = harness.run(task)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "run.json").write_text(result.model_dump_json(indent=2))

    click.echo(
        f"[{agent.name} on {task.task_id}] final_success={result.final_success} "
        f"load={result.load_score:.2f} transport={result.transport_score:.2f} "
        f"proxy={result.proxy_resistance_score:.2f} reopen={result.reopenability_score:.2f} "
        f"gauge_budget={budget}"
    )


@cli.command()
@click.option("--suite", required=True, type=click.Choice(sorted(SUITES.keys())))
@click.option("--agent", "agent_cfg", required=True)
@click.option("--mode", default="guarded", type=click.Choice(["guarded", "audit"]))
@click.option("--seeds", default=16, type=int)
@click.option("--out", "out_dir", required=True)
@click.option("--gauge-budget", default=None, type=int)
@click.option("--gauge-min-concern", default=None, type=float)
@click.option(
    "--concern-mapper",
    "concern_mapper_kind",
    default="default",
    type=click.Choice(["default", "metadata", "llm"]),
)
@click.option("--mapper-model", "mapper_model_cfg", default=None)
@click.option("--mapper-force-llm/--mapper-prefer-metadata", default=False)
def bench(
    suite: str,
    agent_cfg: str,
    mode: str,
    seeds: int,
    out_dir: str,
    gauge_budget: int | None,
    gauge_min_concern: float | None,
    concern_mapper_kind: str,
    mapper_model_cfg: str | None,
    mapper_force_llm: bool,
) -> None:
    """Run a whole benchmark suite over N seeds."""
    suite_mod = load_suite(suite)
    cfg = _load_yaml(agent_cfg)
    agent = _build_agent_from_config(cfg)
    thresholds, budget, min_concern = _resolve_gauge(
        mode, gauge_budget, gauge_min_concern, cfg.get("thresholds") or {}
    )
    mapper = _build_concern_mapper(
        concern_mapper_kind,
        mapper_model_cfg=mapper_model_cfg,
        prefer_metadata=not mapper_force_llm,
    )

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    jsonl_path = Path(out_dir) / "runs.jsonl"
    stats: list[dict] = []
    with open(jsonl_path, "w") as fh:
        for seed in range(seeds):
            task = suite_mod.generate(seed)
            env = suite_mod.make_env()
            harness = _build_harness(
                agent,
                env,
                mode,
                thresholds,
                gauge_probe_budget=budget,
                gauge_min_concern=min_concern,
                concern_mapper=mapper,
            )
            result = harness.run(task)
            row = _run_result_row(
                run_id=f"{suite}_{cfg.get('name','agent')}_{seed}",
                task_id=task.task_id,
                agent=agent.name,
                mode=mode,
                result=result,
            )
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
@click.option("--gauge-budget", default=None, type=int)
@click.option("--gauge-min-concern", default=None, type=float)
@click.argument("agent_positional", nargs=-1, type=click.UNPROCESSED)
def compare(
    suite: str,
    agents_flag: str,
    mode: str,
    seeds: int,
    out_dir: str,
    gauge_budget: int | None,
    gauge_min_concern: float | None,
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
            thresholds, budget, min_concern = _resolve_gauge(
                m, gauge_budget, gauge_min_concern, cfg.get("thresholds") or {}
            )
            suite_mod = load_suite(suite)
            rows: list[dict] = []
            for seed in range(seeds):
                task = suite_mod.generate(seed)
                env = suite_mod.make_env()
                harness = _build_harness(
                    agent,
                    env,
                    m,
                    thresholds,
                    gauge_probe_budget=budget,
                    gauge_min_concern=min_concern,
                )
                result = harness.run(task)
                row = _run_result_row(
                    run_id=f"{suite}_{agent.name}_{m}_{seed}",
                    task_id=task.task_id,
                    agent=agent.name,
                    mode=m,
                    result=result,
                )
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
@click.argument("runs_jsonl", type=click.Path(exists=True))
@click.option("--out", "out_path", default="", help="Optional path for report output.")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown")
def diagnose(runs_jsonl: str, out_path: str, fmt: str) -> None:
    """Explain harness failures and propose next harness-evolution experiments."""
    rows = read_jsonl(runs_jsonl)
    if fmt == "json":
        rendered = json.dumps(
            {
                "summary": summarize_runs(rows),
                "improvement_proposals": improvement_proposals(rows),
            },
            indent=2,
        ) + "\n"
    else:
        rendered = markdown_report(rows)
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(rendered)
        click.echo(f"wrote {out_path}")
    else:
        click.echo(rendered.rstrip())


@cli.group(name="code", help="Run real-repository coding harness tasks.")
def code_group() -> None:
    pass


@code_group.command(name="run")
@click.option("--task", "task_path", required=True, type=click.Path(exists=True))
@click.option("--repo", "repo_path", default="", help="Workspace repo path; overrides task.repo_path.")
@click.option("--actions", "actions_path", default=None, type=click.Path(exists=True))
@click.option("--model-agent", "model_agent_cfg", default=None, type=click.Path(exists=True), help="Model config to drive a model-backed coding agent.")
@click.option("--out", "out_dir", required=True, help="Directory to write coding run artifacts.")
def code_run(
    task_path: str,
    repo_path: str,
    actions_path: str | None,
    model_agent_cfg: str | None,
    out_dir: str,
) -> None:
    """Run an inspect/edit/test/finish coding loop."""
    task: CodingTask = load_coding_task(task_path, repo_path or None)
    if not task.repo_path:
        raise click.ClickException("provide --repo or task.repo_path")
    if bool(actions_path) == bool(model_agent_cfg):
        raise click.ClickException("provide exactly one of --actions or --model-agent")
    try:
        if actions_path is not None:
            agent = _load_scripted_coding_agent(actions_path)
        else:
            assert model_agent_cfg is not None
            cfg = _load_yaml(model_agent_cfg)
            model = _build_agent_from_config(cfg)
            if not callable(getattr(model, "complete", None)):
                raise ValueError("--model-agent config must build a ModelAdapter with complete()")
            agent = ModelCodingAgent(
                model,
                name=cfg.get("coding_name") or f"{cfg.get('name', cfg.get('type', 'model'))}_coder",
                temperature=float(cfg.get("coding_temperature", cfg.get("temperature", 0.0))),
                max_tokens=int(cfg.get("coding_max_tokens", cfg.get("max_tokens", 2048))),
            )
        workspace = CodingWorkspace(task.repo_path, task)
        result = CodingHarnessRunner(agent, workspace).run(task)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "coding_run.json").write_text(result.model_dump_json(indent=2))
    (out / "final.diff").write_text(result.final_diff)
    cert_n = len(result.certificates)
    load = result.load_score
    click.echo(
        f"[code {task.task_id}] success={result.success} steps={result.steps} "
        f"modified={','.join(result.modified_files) or '-'} "
        f"certs={cert_n} load={load:.2f}"
    )


@code_group.command(name="swebench")
@click.option("--instances", "instances_path", required=True, type=click.Path(exists=True), help="SWE-bench-style JSON or JSONL instances.")
@click.option("--repo-source", default="", help="Single local source repo path to clone for every instance.")
@click.option("--repo-root", default="", help="Root containing repos by owner/name, owner__name, or name.")
@click.option("--actions", "actions_path", default=None, type=click.Path(exists=True))
@click.option("--model-agent", "model_agent_cfg", default=None, type=click.Path(exists=True), help="Model config to drive a model-backed coding agent.")
@click.option("--limit", default=None, type=int, help="Maximum number of instances to run.")
@click.option("--offset", default=0, type=int, help="Instance offset within the input file.")
@click.option("--max-steps", default=40, type=int, show_default=True)
@click.option("--timeout", "timeout_seconds", default=300.0, type=float, show_default=True)
@click.option("--backend", type=click.Choice(["local", "docker"]), default="local", show_default=True)
@click.option("--docker-image", default="", help="Docker image used when --backend docker.")
@click.option("--include-pass-to-pass/--skip-pass-to-pass", default=True, show_default=True)
@click.option("--official/--no-official", default=False, show_default=True, help="Write official SWE-bench harness prediction files and commands.")
@click.option("--official-dataset", default="princeton-nlp/SWE-bench_Verified", show_default=True)
@click.option("--official-run-id", default="lbah-code", show_default=True)
@click.option("--official-max-workers", default=1, type=int, show_default=True)
@click.option("--official-cache-level", type=click.Choice(["none", "base", "env", "instance"]), default="env", show_default=True)
@click.option("--official-timeout", default=None, type=int)
@click.option("--official-namespace", default="")
@click.option("--subset-sizes", default="5,20,50", show_default=True, help="Comma-separated official subset manifest sizes.")
@click.option("--out", "out_dir", required=True, help="Directory to write suite artifacts.")
def code_swebench(
    instances_path: str,
    repo_source: str,
    repo_root: str,
    actions_path: str | None,
    model_agent_cfg: str | None,
    limit: int | None,
    offset: int,
    max_steps: int,
    timeout_seconds: float,
    backend: str,
    docker_image: str,
    include_pass_to_pass: bool,
    official: bool,
    official_dataset: str,
    official_run_id: str,
    official_max_workers: int,
    official_cache_level: str,
    official_timeout: int | None,
    official_namespace: str,
    subset_sizes: str,
    out_dir: str,
) -> None:
    """Run a SWE-bench-style smoke suite through LBAH-Code."""
    if bool(actions_path) == bool(model_agent_cfg):
        raise click.ClickException("provide exactly one of --actions or --model-agent")
    if backend == "docker" and not docker_image:
        raise click.ClickException("--backend docker requires --docker-image")

    try:
        instances = load_swebench_instances(instances_path, limit=limit, offset=offset)
        if actions_path is not None:
            def scripted_agent_factory(_instance, _task):
                return _load_scripted_coding_agent(actions_path)
            agent_factory = scripted_agent_factory
        else:
            assert model_agent_cfg is not None
            cfg = _load_yaml(model_agent_cfg)
            model = _build_agent_from_config(cfg)
            if not callable(getattr(model, "complete", None)):
                raise ValueError("--model-agent config must build a ModelAdapter with complete()")

            def model_agent_factory(_instance, _task):
                return ModelCodingAgent(
                    model,
                    name=cfg.get("coding_name") or f"{cfg.get('name', cfg.get('type', 'model'))}_coder",
                    temperature=float(cfg.get("coding_temperature", cfg.get("temperature", 0.0))),
                    max_tokens=int(cfg.get("coding_max_tokens", cfg.get("max_tokens", 2048))),
                )
            agent_factory = model_agent_factory

        options = SWEBenchEvaluationOptions(
            repo_source=repo_source or None,
            repo_root=repo_root or None,
            out_dir=out_dir,
            max_steps=max_steps,
            timeout_seconds=timeout_seconds,
            include_pass_to_pass=include_pass_to_pass,
            backend=SWEBenchExecutionBackend(
                kind=cast(SWEBenchBackendKind, backend),
                docker_image=docker_image or None,
                timeout_seconds=timeout_seconds,
            ),
        )
        suite = run_swebench_smoke_suite(instances, agent_factory, options)
        official_inputs = None
        if official:
            official_spec = SWEBenchOfficialHarnessSpec(
                dataset_name=official_dataset,
                run_id=official_run_id,
                max_workers=official_max_workers,
                cache_level=cast(SWEBenchCacheLevel, official_cache_level),
                timeout=official_timeout,
                namespace=official_namespace or None,
            )
            official_inputs = write_official_swebench_inputs(
                Path(out_dir) / "official",
                suite.results,
                spec=official_spec,
                model_name_or_path=official_run_id,
            )
            write_swebench_subset_manifests(
                Path(out_dir) / "official" / "subsets",
                official_inputs.instance_ids,
                sizes=_parse_int_list(subset_sizes),
                predictions_path=official_inputs.predictions_path,
                spec=official_spec,
            )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    failures = ", ".join(f"{kind}={count}" for kind, count in sorted(suite.failure_counts.items()))
    official_msg = f" official={official_inputs.command_path}" if official_inputs else ""
    click.echo(
        f"[swebench] solved={suite.solved}/{suite.total} "
        f"rate={suite.solve_rate:.2f} failures={failures or '-'} out={out_dir}{official_msg}"
    )


@cli.command()
@click.argument("run_path", type=click.Path(exists=True))
@click.option(
    "--lineage",
    "lineage_var",
    default=None,
    help="Print the provenance (event chain) of a concern variable instead of certificates.",
)
def replay(run_path: str, lineage_var: str | None) -> None:
    """Print certificates from a saved RunResult, or a variable's lineage."""
    data = json.loads(Path(run_path).read_text())
    is_coding = "final_diff" in data or "mode" not in data
    if is_coding:
        click.echo(
            f"Task: {data['task_id']}   Agent: {data['agent']}   "
            f"(coding) success={data.get('success')}   load_score={float(data.get('load_score') or 0):.2f}"
        )
    else:
        click.echo(f"Task: {data['task_id']}   Agent: {data['agent']}   Mode: {data['mode']}")
        click.echo(f"final_success={data['final_success']}   load_score={data['load_score']:.2f}")

    if lineage_var is not None:
        _replay_lineage(data, lineage_var)
        return

    for i, cert in enumerate(data.get("certificates", [])):
        click.echo(f"\n--- step {i} [{cert['decision']}] load={cert['load_score']:.2f} ---")
        click.echo(f"  summary: {cert['summary']}")
        for group in (
            "transport_results",
            "proxy_results",
            "gauge_results",
            "reopenability_results",
            "validator_results",
        ):
            for r in cert.get(group, []):
                mark = "OK " if r["passed"] else "FAIL"
                click.echo(f"    {mark} {r['gate_name']}: {r['reason']}")


def _replay_lineage(data: dict, var_id: str) -> None:
    """Print the append-only event chain that produced a concern variable."""
    raw = data.get("event_log")
    if not raw:
        click.echo(
            "\n(no event_log on this run — it predates event-sourcing or was "
            "produced without it)"
        )
        return

    # Coding runs use CodingEventLog; core runs use ConcernEventLog.
    if "task_id" in raw and "task" not in raw:
        from .coding.events import CodingEventLog

        log = CodingEventLog.model_validate(raw)
        events = log.lineage(var_id)
        if not events:
            known = sorted({e.concern_id for e in log.events if e.concern_id})
            click.echo(f"\nno events for concern '{var_id}'. known: {known}")
            return
        current = log.project().by_id(var_id)
        click.echo(f"\nLineage of '{var_id}' ({len(events)} events):")
        for e in events:
            fields = ", ".join(f"{k}={v!r}" for k, v in e.payload.items() if k != "id")
            src = f" <- {e.source}" if e.source else ""
            click.echo(f"  [{e.seq}] {e.type}{src}: {fields}")
        if current is not None:
            click.echo(
                f"  => projected: text={current.text!r} concern={current.concern} "
                f"status={current.status}"
            )
        return

    from .core.events import ConcernEventLog

    log = ConcernEventLog.model_validate(raw)
    events = log.lineage(var_id)
    if not events:
        known = sorted({e.variable_id for e in log.events if e.variable_id})
        click.echo(f"\nno events for variable '{var_id}'. known: {known}")
        return
    current = log.project().by_id(var_id)
    click.echo(f"\nLineage of '{var_id}' ({len(events)} events):")
    for e in events:
        fields = ", ".join(f"{k}={v!r}" for k, v in e.payload.items() if k != "id")
        src = f" <- {e.source}" if e.source else ""
        click.echo(f"  [{e.seq}] {e.type}{src}: {fields}")
    if current is not None:
        click.echo(
            f"  => projected: value={current.value!r} concern={current.concern} "
            f"freshness={current.freshness}"
        )


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


def _parse_int_list(raw: str) -> list[int]:
    values: list[int] = []
    for part in raw.replace(" ", ",").split(","):
        if not part:
            continue
        value = int(part)
        if value <= 0:
            raise ValueError("subset sizes must be positive integers")
        values.append(value)
    if not values:
        raise ValueError("at least one subset size is required")
    return values


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
