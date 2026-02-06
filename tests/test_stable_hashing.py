from __future__ import annotations

from langchain_core.documents import Document


def _is_hex(s: str) -> bool:
    if not s:
        return False
    allowed = set("0123456789abcdef")
    return all(ch in allowed for ch in s)


def test_stable_hash_is_hex_and_deterministic() -> None:
    from app.rag.core.hashing import stable_hash  # noqa: WPS433

    a = stable_hash("hello", length=16)
    b = stable_hash("hello", length=16)
    c = stable_hash("world", length=16)

    assert a == b
    assert a != c
    assert len(a) == 16
    assert _is_hex(a)


def test_doc_key_uses_stable_content_hash() -> None:
    from app.rag.engine import RAGEngine  # noqa: WPS433

    doc = Document(page_content="hello world", metadata={})
    key = RAGEngine._doc_key(doc)

    assert key.startswith("content:")
    suffix = key.split("content:", 1)[1]
    assert len(suffix) == 16
    assert _is_hex(suffix)


def test_retriever_result_key_uses_stable_content_hash() -> None:
    from app.rag.retriever import HybridRetriever  # noqa: WPS433

    r = HybridRetriever()
    key = r._result_key({"content": "hello world", "metadata": {}})

    assert key.startswith("content:")
    suffix = key.split("content:", 1)[1]
    assert len(suffix) == 16
    assert _is_hex(suffix)
