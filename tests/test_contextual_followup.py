from __future__ import annotations

from langchain_core.documents import Document


def test_contextual_followup_builder_no_docs_returns_disabled() -> None:
    from app.rag.retrieval.contextual_followup import build_contextual_followup_query

    out = build_contextual_followup_query(
        query="how to debug retrieval drift",
        docs=[],
    )

    assert isinstance(out, dict)
    assert bool(out.get("used")) is False
    assert out.get("query") == "how to debug retrieval drift"
    assert "no_docs" in list(out.get("reason_codes") or [])


def test_contextual_followup_builder_adds_terms_from_metadata_and_content() -> None:
    from app.rag.retrieval.contextual_followup import build_contextual_followup_query

    docs = [
        Document(
            page_content="Refresh token rotation requires offline_access scope and reuse detection.",
            id="a",
            metadata={
                "title": "OAuth Token Rotation Guide",
                "keywords": ["refresh_token", "offline_access", "reuse_detection"],
            },
        ),
        Document(
            page_content="Session replay mitigation and revocation checks for OAuth refresh flows.",
            id="b",
            metadata={"heading": "OAuth Session Security"},
        ),
    ]

    out = build_contextual_followup_query(
        query="oauth login issue",
        docs=docs,
        max_docs=2,
        max_terms=4,
        min_term_chars=4,
    )

    assert bool(out.get("used")) is True
    assert isinstance(out.get("query"), str) and str(out.get("query")).startswith("oauth login issue")
    selected_terms = [str(v) for v in (out.get("selected_terms") or [])]
    assert selected_terms
    assert any(term in {"refresh_token", "offline_access", "reuse_detection"} for term in selected_terms)
    assert "selected_terms" in list(out.get("reason_codes") or [])


def test_contextual_followup_builder_respects_max_terms_and_dedupes() -> None:
    from app.rag.retrieval.contextual_followup import build_contextual_followup_query

    docs = [
        Document(
            page_content="inventory inventory turnover threshold threshold",
            id="a",
            metadata={"keywords": ["inventory", "turnover", "inventory"]},
        ),
        Document(
            page_content="inventory aging turnover ratio",
            id="b",
            metadata={"title": "Inventory Turnover Policy"},
        ),
    ]

    out = build_contextual_followup_query(
        query="inventory report",
        docs=docs,
        max_docs=2,
        max_terms=2,
        min_term_chars=3,
    )

    terms = [str(v) for v in (out.get("selected_terms") or [])]
    assert len(terms) == 2
    assert len(set(terms)) == 2
    assert "inventory" not in terms


def test_contextual_followup_builder_prioritizes_gap_terms() -> None:
    from app.rag.retrieval.contextual_followup import build_contextual_followup_query

    docs = [
        Document(
            page_content="sales table contains monthly totals.",
            id="a",
            metadata={"table_id": "sales"},
        )
    ]

    out = build_contextual_followup_query(
        query="monthly totals",
        docs=docs,
        evidence_gap={"missing_source_keys": ["inventory_ledger"], "anchor_missing_any": 1},
        max_docs=1,
        max_terms=3,
        min_term_chars=3,
    )

    assert bool(out.get("used")) is True
    reasons = [str(v) for v in (out.get("reason_codes") or [])]
    assert "gap_missing_source_keys" in reasons
    assert "gap_missing_anchor_fields" in reasons
    terms = [str(v) for v in (out.get("selected_terms") or [])]
    assert any("inventory" in t.lower() for t in terms)
