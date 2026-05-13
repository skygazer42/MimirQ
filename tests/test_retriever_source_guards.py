from pathlib import Path


def test_retriever_no_longer_uses_silent_pass_fallbacks() -> None:
    text = Path("app/rag/retriever.py").read_text(encoding="utf-8")
    assert "except Exception:\n            pass" not in text
    assert "except Exception:\n                pass" not in text
