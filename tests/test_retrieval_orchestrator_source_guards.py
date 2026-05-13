from pathlib import Path
import re


def test_retrieval_orchestrator_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/retrieval/orchestrator.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
