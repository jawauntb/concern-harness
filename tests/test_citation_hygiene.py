"""Citation hygiene: docs must not reintroduce purged placeholder arXiv IDs."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "docs"

# IDs previously present in SOTA_HARNESS_INTEGRATION.md and flagged as fabricated
# in DESIGN_ROADMAP Phase 4 / G6. Do not reintroduce.
PURGED = {
    "2606.21228",
    "2605.27922",
    "2605.18747",
    "2603.25723",
    "2604.25850",
}

ARXIV_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", re.IGNORECASE)


def test_purged_arxiv_ids_absent_from_docs():
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        text = path.read_text(errors="ignore")
        for match in ARXIV_RE.finditer(text):
            arxiv_id = match.group(1)
            if arxiv_id in PURGED:
                hits.append(f"{path.relative_to(ROOT.parent)}:{arxiv_id}")
    assert not hits, "purged placeholder arXiv IDs found:\n" + "\n".join(hits)
