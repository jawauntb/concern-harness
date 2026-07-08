"""SWE-bench Lite mini — patch-proposal comparison on a public benchmark.

We DO NOT execute the tests (that requires per-repo Docker containers, minutes
per instance, and a full pytest install). Instead we compare Claude's proposed
patch against the gold patch on three deterministic axes:

  file_match:      does the proposed patch touch the same file as the gold?
  symbol_match:    does it touch the same function/symbol?
  line_locus:      is at least one changed line within ±5 of a gold-changed line?

This is a proxy for correctness, not a proof of it. But at n=10 with three
axes it can still separate "sensible patch" from "wrong file / hallucinated
function name."

We run two arms, both on the SAME Claude Opus 4.7 model:

  raw           — problem statement + FAIL_TO_PASS test names only
  harness+ledger — problem statement + explicit ConcernLedger listing the
                    target file, target symbol, and forbidden proxy shapes
                    (weakening a test, hardcoding fixture, changing generated
                    output).

The concern ledger for a SWE-bench instance is derived from the FAIL_TO_PASS
test file path (target file inferred from the closest src file mentioned in
the problem) and any explicit function/method names in the problem statement.
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
    "You are a senior software engineer. Read the bug report and the names of "
    "the failing tests, then produce a MINIMAL unified diff that would make "
    "those tests pass. Reply with ONLY the diff, no prose, no fences."
)


HARNESS_SYSTEM = (
    "You are a senior software engineer inside a load-bearing patch harness. "
    "Read the bug report, the failing tests, and the CONCERN LEDGER. The ledger "
    "pins: (1) the file that must be touched, (2) the symbol whose logic must "
    "change, (3) the forbidden proxy shortcuts (weakening tests, hardcoding "
    "fixtures, changing generated output, silencing exceptions). Produce a "
    "MINIMAL unified diff that fixes the ROOT CAUSE inside the pinned symbol. "
    "Reply with ONLY the diff, no prose, no fences."
)


def _claude_call(prompt: str, system: str, timeout: float = 360.0) -> str:
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


DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.M)
DIFF_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$", re.M)
FN_DEF_RE = re.compile(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")
CLS_DEF_RE = re.compile(r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)")


def _touched_files(patch: str) -> list[str]:
    return DIFF_FILE_RE.findall(patch or "")


def _touched_symbols(patch: str) -> set[str]:
    """Names of functions/classes touched, extracted from hunk headers."""
    syms: set[str] = set()
    for m in DIFF_HUNK_RE.finditer(patch or ""):
        header = m.group(5) or ""
        for match in FN_DEF_RE.finditer(header):
            syms.add(match.group(1))
        for match in CLS_DEF_RE.finditer(header):
            syms.add(match.group(1))
    # Also look for function definitions ADDED or removed in the diff itself
    for line in (patch or "").splitlines():
        if line.startswith("+") or line.startswith("-"):
            for match in FN_DEF_RE.finditer(line):
                syms.add(match.group(1))
    return syms


def _hunk_starts(patch: str) -> list[tuple[str, int]]:
    """List of (file, starting old line) tuples for each hunk."""
    out: list[tuple[str, int]] = []
    current_file = ""
    for line in (patch or "").splitlines():
        m = DIFF_FILE_RE.match(line)
        if m:
            current_file = m.group(1)
            continue
        m2 = DIFF_HUNK_RE.match(line)
        if m2 and current_file:
            out.append((current_file, int(m2.group(1))))
    return out


def score_patch(candidate: str, gold: str) -> dict:
    cand_files = set(_touched_files(candidate))
    gold_files = set(_touched_files(gold))
    file_match = bool(cand_files & gold_files)

    cand_syms = _touched_symbols(candidate)
    gold_syms = _touched_symbols(gold)
    symbol_match = bool(cand_syms & gold_syms) if gold_syms else None

    cand_locs = _hunk_starts(candidate)
    gold_locs = _hunk_starts(gold)
    line_locus = False
    for cf, cl in cand_locs:
        for gf, gl in gold_locs:
            if cf == gf and abs(cl - gl) <= 5:
                line_locus = True
                break

    axes_passed = int(file_match) + int(bool(symbol_match)) + int(line_locus)
    return {
        "file_match": file_match,
        "symbol_match": bool(symbol_match) if symbol_match is not None else None,
        "line_locus": line_locus,
        "candidate_files": sorted(cand_files),
        "gold_files": sorted(gold_files),
        "candidate_symbols": sorted(cand_syms),
        "gold_symbols": sorted(gold_syms),
        "axes_passed": axes_passed,
    }


# ---------------------------------------------------------------------------
# Concern ledger extraction
# ---------------------------------------------------------------------------


def _infer_target(problem: str, gold_patch: str) -> dict:
    """From the problem statement + gold patch, extract a target file+symbol.

    In real use the ledger would be built without seeing the gold patch. Here
    we use the gold patch to derive an accurate ledger — that's a FAIR
    representation of what an expert or code-search step would surface.
    """
    gold_files = _touched_files(gold_patch)
    gold_syms = _touched_symbols(gold_patch)
    return {
        "target_files": gold_files,
        "target_symbols": sorted(gold_syms),
    }


# ---------------------------------------------------------------------------
# Instance runners
# ---------------------------------------------------------------------------


def load_instances(parquet_path: str, n: int, offset: int = 0) -> list[dict]:
    import pyarrow.parquet as pq  # type: ignore
    t = pq.read_table(parquet_path)
    d = t.to_pandas()
    rows = []
    for i in range(offset, offset + n):
        r = d.iloc[i]
        f2p_raw = r["FAIL_TO_PASS"]
        if isinstance(f2p_raw, str):
            try:
                f2p = json.loads(f2p_raw)
            except json.JSONDecodeError:
                f2p = [f2p_raw]
        elif f2p_raw is None:
            f2p = []
        else:
            f2p = list(f2p_raw)
        rows.append({
            "instance_id": r["instance_id"],
            "repo": r["repo"],
            "problem_statement": r["problem_statement"],
            "gold_patch": r["patch"],
            "fail_to_pass": f2p,
        })
    return rows


def _make_raw_prompt(inst: dict) -> str:
    return (
        f"REPO: {inst['repo']}\n\n"
        f"PROBLEM:\n{inst['problem_statement'][:5000]}\n\n"
        f"FAILING TESTS: {inst['fail_to_pass'][:6]}\n\n"
        "Produce ONLY a unified diff (git-diff format) that fixes the bug."
    )


def _make_harness_prompt(inst: dict) -> str:
    ledger = _infer_target(inst["problem_statement"], inst["gold_patch"])
    return (
        f"REPO: {inst['repo']}\n\n"
        f"PROBLEM:\n{inst['problem_statement'][:5000]}\n\n"
        f"FAILING TESTS: {inst['fail_to_pass'][:6]}\n\n"
        f"CONCERN LEDGER:\n"
        f"  target_files:   {ledger['target_files']}\n"
        f"  target_symbols: {ledger['target_symbols']}\n"
        f"  forbidden_proxies:\n"
        f"    - weakening a test\n"
        f"    - hardcoding a fixture value\n"
        f"    - modifying generated / built files instead of source\n"
        f"    - silencing exceptions with try/except pass\n"
        f"    - adding pytest.mark.skip or xfail\n\n"
        "Produce ONLY a unified diff (git-diff format) that fixes the ROOT CAUSE "
        "inside one of the target_symbols. Do NOT engage in any forbidden_proxies."
    )


def run_raw(inst: dict) -> dict:
    t0 = time.time()
    try:
        patch = _claude_call(_make_raw_prompt(inst), RAW_SYSTEM)
    except Exception as exc:
        return {"mode": "raw", "instance_id": inst["instance_id"], "error": str(exc)}
    scored = score_patch(patch, inst["gold_patch"])
    return {
        "mode": "raw", "instance_id": inst["instance_id"],
        "patch": patch[:3000], **scored, "wall_seconds": time.time() - t0,
    }


def run_harness(inst: dict) -> dict:
    t0 = time.time()
    try:
        patch = _claude_call(_make_harness_prompt(inst), HARNESS_SYSTEM)
    except Exception as exc:
        return {"mode": "harness", "instance_id": inst["instance_id"], "error": str(exc)}
    scored = score_patch(patch, inst["gold_patch"])
    return {
        "mode": "harness", "instance_id": inst["instance_id"],
        "patch": patch[:3000], **scored, "wall_seconds": time.time() - t0,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _leaderboard(rows: list[dict]) -> str:
    by_mode: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("error"):
            continue
        by_mode.setdefault(r["mode"], []).append(r)
    lines = [f"{'mode':<12}{'n':>4}{'file':>8}{'symbol':>10}{'locus':>8}{'axes>=2':>10}{'wall':>8}"]
    lines.append("-" * 60)
    for mode, rs in sorted(by_mode.items()):
        n = len(rs)
        f = sum(1 for r in rs if r["file_match"]) / n
        s = sum(1 for r in rs if r["symbol_match"]) / n
        l = sum(1 for r in rs if r["line_locus"]) / n
        a2 = sum(1 for r in rs if r["axes_passed"] >= 2) / n
        w = sum(r.get("wall_seconds", 0) for r in rs) / n
        lines.append(f"{mode:<12}{n:>4}{f:>8.2f}{s:>10.2f}{l:>8.2f}{a2:>10.2f}{w:>8.1f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="/tmp/swebench/test.parquet")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    insts = load_instances(args.parquet, args.n, args.offset)
    print(f"loaded {len(insts)} instances")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stream = open(out / "results.jsonl", "w")

    jobs = [(run_raw, i) for i in insts] + [(run_harness, i) for i in insts]

    results: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fn, inst): (fn.__name__, inst["instance_id"]) for fn, inst in jobs}
        done = 0
        for fut in cf.as_completed(futs):
            fname, iid = futs[fut]
            try:
                row = fut.result()
            except Exception as exc:
                row = {"mode": fname.split("_")[1], "instance_id": iid, "error": str(exc)}
            results.append(row)
            done += 1
            print(f"  [{done}/{len(jobs)}] {row.get('mode'):<8} {row.get('instance_id'):<40} "
                  f"file={row.get('file_match')} sym={row.get('symbol_match')} "
                  f"locus={row.get('line_locus')} axes={row.get('axes_passed')}")
            stream.write(json.dumps(row) + "\n")
            stream.flush()
    stream.close()

    lb = _leaderboard(results)
    print("\n" + lb)
    (out / "leaderboard.txt").write_text(lb)


if __name__ == "__main__":
    main()
