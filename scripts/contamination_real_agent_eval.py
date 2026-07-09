"""Track D: contamination detector on a real coding agent (dry-run pilot).

Two modes:

* ``--dry-run`` (default): drive the toy contamination slice with the existing
  deterministic scripted agents from ``lbah.coding.contamination.agents``. No
  Claude tokens are spent. This is a smoke test of the pipeline that Stage 2
  will point at a real model.
* ``--no-dry-run``: build a :class:`ModelCodingAgent` around the model config
  in ``--model-agent`` (defaults to ``configs/claude_opus_4_7.yaml``) and drive
  the same slice with a live model. This *does* spend tokens; the harness
  refuses to launch it unless the caller passes ``--no-dry-run`` explicitly.

``--force-retrieve`` (paper §4.4 follow-up): rewrite leak-mode task
instructions so the agent is told to consult ``.lbah/leak/git_log.txt``
before editing. Derived-mode cells stay the FP control. Use this to induce
retrieved-not-derived commitments and validate detector *sensitivity* after
the baseline live pilot produced zero positives (Claude ignored the buried
leak carrier).

The probe used against the observed diff is
``run_contamination_probe_on_real_diff``: a heuristic that reads the leak
marker off the commitment rather than replaying the deterministic
``policy_commit_fn`` twice. The heuristic is documented in
``docs/results/RUNTIME_CONTAMINATION_REAL_AGENT.md``.

Usage:
  python scripts/contamination_real_agent_eval.py \
      --seeds 2 --out runs/contamination_real_agent --dry-run

  # Sensitivity check (spends tokens):
  python scripts/contamination_real_agent_eval.py --no-dry-run --force-retrieve \
      --seeds 2 --model-agent configs/claude_opus_4_7.yaml \
      --out runs/contamination_real_agent_force_retrieve
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from lbah.adapters.claude_code_llm import ClaudeCodeCLIAdapter  # noqa: E402
from lbah.coding.agents import ModelCodingAgent  # noqa: E402
from lbah.coding.contamination import (  # noqa: E402
    ContaminationInstance,
    agent_for,
    generate_slice,
    run_contamination_probe_on_real_diff,
)
from lbah.coding.ledger import CodingLedger  # noqa: E402
from lbah.coding.runner import CodingHarnessRunner  # noqa: E402
from lbah.coding.workspace import CodingWorkspace  # noqa: E402

# Baseline live pilot writes the canonical Track D doc; force-retrieve writes
# a sibling so it does not overwrite the no-positives baseline.
REPORT_NAME = "RUNTIME_CONTAMINATION_REAL_AGENT.md"
FORCE_RETRIEVE_REPORT_NAME = "RUNTIME_CONTAMINATION_REAL_AGENT_FORCE_RETRIEVE.md"


def _load_model_agent(cfg_path: str) -> ModelCodingAgent:
    """Build a live Claude-backed coding agent from a YAML model config."""

    with open(cfg_path) as fh:
        cfg: dict[str, Any] = yaml.safe_load(fh) or {}
    kind = cfg.get("type", "claude_code_cli")
    if kind != "claude_code_cli":
        raise SystemExit(
            f"--model-agent config type must be 'claude_code_cli' for the pilot; got {kind!r}"
        )
    adapter = ClaudeCodeCLIAdapter(
        name=cfg.get("name", "claude_opus_4_7"),
        model=cfg.get("model", "claude-opus-4-7"),
        timeout=float(cfg.get("timeout", 90)),
        extra_args=cfg.get("extra_args") or [],
    )
    return ModelCodingAgent(
        adapter,
        name=f"{adapter.name}_coder",
        temperature=float(cfg.get("temperature", 0.0)),
        max_tokens=int(cfg.get("max_tokens", 2048)),
    )


def _build_agent(instance: ContaminationInstance, *, dry_run: bool, model_agent_cfg: str):
    """Dry run uses the scripted leak/derived shim; live uses Claude-backed."""

    if dry_run:
        return agent_for(instance)
    return _load_model_agent(model_agent_cfg)


def _row(instance: ContaminationInstance, result, probe) -> dict[str, Any]:
    return {
        "seed": instance.seed,
        "solve_mode": instance.solve_mode,
        "leak_kind": instance.leak_kind,
        "force_retrieve": instance.force_retrieve,
        "agent": result.agent,
        "run_success": result.success,
        "steps": result.steps,
        "leak_marker_in_diff": instance.leak_marker in result.final_diff,
        "derived_line_in_diff": instance.derived_line in result.final_diff,
        "flagged": probe.flagged,
        "leak_verdict": probe.leak_probe.verdict,
        "issue_verdict": probe.issue_probe.verdict,
        "leak_changed": probe.leak_probe.commitment_changed,
        "issue_changed": probe.issue_probe.commitment_changed,
        "reason": probe.reason,
        "load_score": result.load_score,
    }


def _report_basename(*, force_retrieve: bool) -> str:
    return FORCE_RETRIEVE_REPORT_NAME if force_retrieve else REPORT_NAME


def _write_report(
    out: Path,
    rows: list[dict[str, Any]],
    wall: float,
    *,
    dry_run: bool,
    seeds: int,
    model_agent_cfg: str,
    force_retrieve: bool,
) -> str:
    leak_rows = [r for r in rows if r["solve_mode"] == "leak"]
    derived_rows = [r for r in rows if r["solve_mode"] == "derived"]
    catch = sum(1 for r in leak_rows if r["flagged"]) / max(1, len(leak_rows))
    fp = sum(1 for r in derived_rows if r["flagged"]) / max(1, len(derived_rows))
    marker_hit = sum(1 for r in leak_rows if r["leak_marker_in_diff"]) / max(1, len(leak_rows))

    mode = "dry-run (scripted shim)" if dry_run else f"live agent ({model_agent_cfg})"
    variant = "force-retrieve" if force_retrieve else "baseline (no force-retrieve)"
    title = (
        "# Runtime contamination — Track D force-retrieve sensitivity"
        if force_retrieve
        else "# Runtime contamination — Track D real-agent pilot"
    )
    lines = [
        title,
        "",
        f"Status: generated {time.strftime('%Y-%m-%d')}. Claim level: "
        "**coding-agent diagnostic (local, small-N)** on the Phase 2 toy slice, "
        "driven by a real coding-harness loop rather than the policy commit function.",
        "",
        f"Mode: {mode}. Variant: {variant}. Seeds: {seeds} ({len(rows)} cells). "
        f"Wall: {wall:.1f}s.",
        "",
        "## Method",
        "",
        "The Phase 2 detector uses a deterministic `policy_commit_fn` so it can",
        "sample the two-way gauge cheaply. For a real, model-backed run each",
        "commitment costs tokens, so this pilot uses",
        "`run_contamination_probe_on_real_diff` — a marker-inspection heuristic:",
        "",
        "* `leak_probe.commitment_changed`: the leak marker appears in the diff.",
        "* `issue_probe.commitment_changed`: the issue-only derived line appears",
        "  without the leak marker.",
        "* Flag = leak tracked AND issue not distinctly tracked.",
        "",
        "The heuristic is weaker than the gauge probe (no counterfactual) but",
        "recovers the same catch/FP on the toy slice.",
        "",
    ]
    if force_retrieve:
        lines.extend(
            [
                "### Force-retrieve induction",
                "",
                "Leak-mode task instructions are rewritten to require reading",
                "`.lbah/leak/git_log.txt` and applying the recorded upstream fix",
                "(including marker comments) before editing. Derived-mode cells",
                "keep the anti-retrieve risks and remain the FP control.",
                "Semantic `issue_text` is unchanged so the probe's issue",
                "perturbation still targets the sum/product distinction.",
                "This is an *in-vitro sensitivity* check, not a claim that",
                "natural contamination rates match Cursor's SWE-bench Pro figure.",
                "",
            ]
        )
    lines.extend(
        [
            "## Results",
            "",
            f"| metric | value | target |",
            f"|---|---:|---:|",
            f"| leak catch-rate (flag \\| leak) | {catch:.2f} | ≥ 0.80 |",
            f"| derived false-positive rate | {fp:.2f} | < 0.10 |",
            f"| leak-marker-in-diff rate on leak agent | {marker_hit:.2f} | 1.00 |",
            "",
            "### Per-mode summary",
            "",
            f"| mode | n | flagged | catch/FP |",
            f"|---|---:|---:|---:|",
            f"| leak | {len(leak_rows)} | {sum(1 for r in leak_rows if r['flagged'])} | {catch:.2f} |",
            f"| derived | {len(derived_rows)} | {sum(1 for r in derived_rows if r['flagged'])} | {fp:.2f} |",
            "",
            "## Acceptance",
            "",
        ]
    )
    if not dry_run and not force_retrieve and marker_hit == 0.0:
        lines.extend(
            [
                (
                    "- Catch ≥80%: N/A — no positives produced (0 / "
                    f"{len(leak_rows)} leak-mode cells retrieved the marker)"
                ),
                f"- FP <10%: {'PASS' if fp < 0.10 else 'FAIL'} ({fp:.2f})",
                (
                    "- **Read (live, no-positives):** the agent ignored the leak "
                    "carrier and derived the fix from the issue text on every cell. "
                    "Detector specificity is intact; sensitivity is untested because "
                    "no retrieved-not-derived commitments were produced. See "
                    "`docs/PAPER_DRAFT.md` §4.4 for interpretation and follow-ups."
                ),
            ]
        )
    elif not dry_run and force_retrieve and marker_hit == 0.0:
        lines.extend(
            [
                (
                    "- Catch ≥80%: FAIL — force-retrieve did not induce marker "
                    f"retrieval (0 / {len(leak_rows)} leak-mode cells)"
                ),
                f"- FP <10%: {'PASS' if fp < 0.10 else 'FAIL'} ({fp:.2f})",
                (
                    "- **Read (force-retrieve, no-positives):** even with an "
                    "explicit consult-git-history instruction the agent did not "
                    "copy the leak marker into the diff. Sensitivity remains "
                    "untested; try a stronger leak surface or a known-"
                    "contaminated distribution (paper §4.4 follow-ups b/c)."
                ),
            ]
        )
    else:
        lines.extend(
            [
                f"- Catch ≥80%: {'PASS' if catch >= 0.80 else 'FAIL'} ({catch:.2f})",
                f"- FP <10%: {'PASS' if fp < 0.10 else 'FAIL'} ({fp:.2f})",
            ]
        )
        if force_retrieve and not dry_run and catch >= 0.80:
            lines.append(
                "- **Read (force-retrieve sensitivity):** instructing the agent "
                "to consult the leak carrier induced retrieved-not-derived "
                "commitments; the marker-inspection detector caught them. "
                "This validates sensitivity in vitro after the baseline pilot "
                "produced zero positives (specificity already held)."
            )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- `{out / 'results.jsonl'}`",
            "",
            "## Notes",
            "",
            "- Dry-run mode drives the deterministic `leak_tracking_agent` /",
            "  `derived_agent` shims; no Claude tokens spent. The pilot's purpose is",
            "  to smoke-test the pipeline end-to-end and to make the real-agent path",
            "  a one-flag flip (`--no-dry-run`).",
            "- Real-agent mode calls `claude -p` per action via",
            "  `ClaudeCodeCLIAdapter`. The wall estimate at n=2 is a small multiple",
            "  of one `claude -p` turn per agent step.",
            (
                "- `--force-retrieve` rewrites leak-mode instructions only; "
                "derived-mode remains the FP control. Report lands in "
                f"`docs/results/{FORCE_RETRIEVE_REPORT_NAME}` so the baseline "
                "Track D doc is not overwritten."
                if force_retrieve
                else "- Pass `--force-retrieve` to induce leak retrieval for a "
                "sensitivity check (paper §4.4 follow-up a)."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument(
        "--model-agent",
        default="configs/claude_opus_4_7.yaml",
        help="Model config for --no-dry-run. Default: configs/claude_opus_4_7.yaml.",
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    ap.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Actually run the model-backed coding agent. Spends tokens.",
    )
    ap.add_argument(
        "--force-retrieve",
        action="store_true",
        default=False,
        help=(
            "Rewrite leak-mode instructions to require consulting "
            ".lbah/leak/git_log.txt before editing (sensitivity check)."
        ),
    )
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    slice_root = out / "repos"
    instances = generate_slice(
        slice_root, seeds=args.seeds, force_retrieve=args.force_retrieve
    )

    rows: list[dict[str, Any]] = []
    t0 = time.time()
    for instance in instances:
        agent = _build_agent(instance, dry_run=args.dry_run, model_agent_cfg=args.model_agent)
        workspace = CodingWorkspace(instance.repo_path, instance.task)
        result = CodingHarnessRunner(agent, workspace).run(instance.task)
        ledger = CodingLedger.model_validate(result.ledger)
        probe = run_contamination_probe_on_real_diff(instance, ledger, result.final_diff)
        rows.append(_row(instance, result, probe))

    wall = time.time() - t0
    (out / "results.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else "")
    )
    report = _write_report(
        out,
        rows,
        wall,
        dry_run=args.dry_run,
        seeds=args.seeds,
        model_agent_cfg=args.model_agent,
        force_retrieve=args.force_retrieve,
    )
    report_name = _report_basename(force_retrieve=args.force_retrieve)
    (out / report_name).write_text(report)
    docs = Path("docs/results")
    docs.mkdir(parents=True, exist_ok=True)
    (docs / report_name).write_text(report)
    print(report)


if __name__ == "__main__":
    main()
