from pathlib import Path
import re


def test_llama_index_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/chunking/strategies/llama_index.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
