"""Load prompt text shipped under ``lbah/prompts/``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=32)
def load_prompt(stem: str) -> str:
    """Return the contents of ``{stem}.txt`` (without extension)."""
    path = _PROMPTS_DIR / f"{stem}.txt"
    if not path.exists():
        raise FileNotFoundError(f"prompt file not found: {path}")
    return path.read_text().strip()
