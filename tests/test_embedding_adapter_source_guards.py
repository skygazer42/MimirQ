from pathlib import Path
import re


def test_embedding_adapter_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/embedding/adapter.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
