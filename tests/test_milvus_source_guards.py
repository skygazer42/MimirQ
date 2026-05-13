from pathlib import Path
import re


def test_milvus_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/storage/vector/milvus.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
