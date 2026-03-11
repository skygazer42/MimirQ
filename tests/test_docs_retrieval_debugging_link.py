from __future__ import annotations

from pathlib import Path


def test_docs_index_includes_retrieval_debugging_link() -> None:
    text = Path("docs/README.md").read_text(encoding="utf-8")
    assert "guides/retrieval_debugging.md" in text
