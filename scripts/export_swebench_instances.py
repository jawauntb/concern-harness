#!/usr/bin/env python
"""Export small SWE-bench dataset slices as JSONL for `lbah code swebench`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="princeton-nlp/SWE-bench_Lite")
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        from datasets import load_dataset  # type: ignore
    except ImportError as exc:
        raise SystemExit("datasets is not installed; run `pip install datasets` or `pip install -e .[swebench]`") from exc

    rows = load_dataset(args.dataset, split=args.split)
    selected = rows.select(range(args.offset, min(args.offset + args.limit, len(rows))))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as handle:
        for row in selected:
            handle.write(json.dumps(dict(row)) + "\n")
    print(f"wrote {len(selected)} instances to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
