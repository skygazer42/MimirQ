from pathlib import Path
import re


def test_image_understanding_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/parsing/enrich/image_understanding.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
