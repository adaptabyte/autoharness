"""Manual/documentation ingestion: text in, searchable chunks out."""
from __future__ import annotations

import re
from pathlib import Path


def load_manual(path: str | Path) -> list[str]:
    """Load a .txt/.md manual (or plain text file) as paragraph chunks."""
    text = Path(path).read_text(errors="replace")
    chunks = [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]
    return chunks


def relevant_chunks(chunks: list[str], query: str, top_k: int = 4) -> list[str]:
    """Keyword-overlap retrieval — good enough for game manuals."""
    words = set(re.findall(r"\w+", query.lower()))
    scored = sorted(
        chunks,
        key=lambda c: len(words & set(re.findall(r"\w+", c.lower()))),
        reverse=True,
    )
    return scored[:top_k]
