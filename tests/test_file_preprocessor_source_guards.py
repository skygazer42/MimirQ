from pathlib import Path
import re


def test_file_preprocessor_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/parsing/preprocess/file_preprocessor.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
