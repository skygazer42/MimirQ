from __future__ import annotations

from langchain_core.documents import Document


def test_detect_temporal_intent_keywords() -> None:
    from app.rag.core.temporal import detect_temporal_intent

    out = detect_temporal_intent("最新的部署方式是什么？")
    assert out.get("detected") is True
    assert "keyword" in (out.get("reason_codes") or [])


def test_detect_temporal_intent_year() -> None:
    from app.rag.core.temporal import detect_temporal_intent

    out = detect_temporal_intent("as of 2025, what changed?")
    assert out.get("detected") is True
    assert "year" in (out.get("reason_codes") or [])


def test_apply_recency_boost_reorders_docs() -> None:
    from app.rag.core.temporal import apply_recency_boost

    d1 = Document(page_content="old", metadata={"document_id": "d1", "score": 1.0})
    d2 = Document(page_content="new", metadata={"document_id": "d2", "score": 1.0})

    # Fixed "now": day 10.
    now_ts = 10 * 86400.0
    updated = {
        "d1": 1 * 86400.0,   # 9 days old
        "d2": 9 * 86400.0,   # 1 day old
    }

    out, meta = apply_recency_boost(
        [d1, d2],
        updated_ts_by_document_id=updated,
        boost_max=0.1,
        window_days=10,
        now_ts=now_ts,
    )
    assert meta.get("used") is True
    assert out[0].page_content == "new"

