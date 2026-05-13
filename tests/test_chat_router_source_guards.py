from pathlib import Path
import re


def test_chat_router_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/api/v1/chat.py").read_text(encoding="utf-8")
    assert re.search(r"except[^\n]*:\n[ \t]*pass\b", text) is None
