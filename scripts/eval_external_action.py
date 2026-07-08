"""Score an externally-produced ActionProposal against a suite:seed task.

Usage:
    python scripts/eval_external_action.py \
        --task moved_bottleneck:3 \
        --action '{"action_id":"a","surface_id":"tool_call","action_type":"answer","payload":{"value":"blue"}}' \
        --label "raw_claude"

Emits a single JSON blob with the certificate + all sub-scores.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lbah.benches import load_suite  # noqa: E402
from lbah.core.certificates import make_certificate  # noqa: E402
from lbah.core.ledger import make_ledger  # noqa: E402
from lbah.core.schemas import ActionProposal  # noqa: E402
from lbah.modules import (  # noqa: E402
    ConcernMapper,
    ProxyAdversary,
    ReopenabilityGovernor,
    SurfaceMapper,
    TransportAuditor,
    Verifier,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="suite:seed")
    ap.add_argument("--action", required=True, help="JSON ActionProposal")
    ap.add_argument("--label", default="external")
    args = ap.parse_args()

    suite_name, seed_str = args.task.split(":", 1)
    suite = load_suite(suite_name)
    task = suite.generate(int(seed_str))
    env = suite.make_env()
    state = env.reset(task)

    variables = ConcernMapper().extract(task, state)
    surfaces = SurfaceMapper().identify(task, variables)
    ledger = make_ledger(task, variables, surfaces)

    proposal = ActionProposal.model_validate(json.loads(args.action))

    transport = TransportAuditor().check(proposal, ledger, state)
    proxy = ProxyAdversary().check(proposal, ledger, state, env)
    reopen = ReopenabilityGovernor().check(proposal, ledger, state)
    validators = Verifier().validate(proposal, ledger, state, env)

    cert = make_certificate(
        task=task, ledger=ledger, proposal=proposal,
        transport=transport, proxy=proxy, reopen=reopen, validators=validators,
    )

    # Simulate execution to see if the environment success check would pass
    env_success = False
    if cert.decision == "allow":
        state = env.execute(proposal, state)
        env_success_fn = getattr(env, "success", None)
        env_success = bool(env_success_fn(state)) if callable(env_success_fn) else state.done

    out = {
        "label": args.label,
        "task_id": task.task_id,
        "decision": cert.decision,
        "load_score": cert.load_score,
        "behavior_score": cert.behavior_score,
        "transport_score": cert.transport_score,
        "proxy_resistance_score": cert.proxy_resistance_score,
        "reopenability_score": cert.reopenability_score,
        "commitment_validity_score": cert.commitment_validity_score,
        "final_success_if_allowed": env_success,
        "summary": cert.summary,
        "failed_gates": [
            r.gate_name
            for r in (transport + proxy + reopen + validators)
            if not r.passed
        ],
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
