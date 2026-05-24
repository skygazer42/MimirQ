from __future__ import annotations

from scripts.remote_keyword_bm25_fallback_probe import evaluate_keyword_case


def test_keyword_bm25_fallback_probe_accepts_xlsx_first_hit() -> None:
    xlsx_document_id = "doc-xlsx"
    retrieve_body = {
        "citations": [
            {"document_id": xlsx_document_id},
            {"document_id": "doc-yaml"},
        ],
        "metrics": {
            "retrieval_per_query": [
                {
                    "retriever_debug": {
                        "counts": {"vector_candidates": 0, "bm25_candidates": 3},
                        "channels": {
                            "vector": {"enabled": False, "candidates": 0, "filter_applied": True},
                            "lexical_db": {
                                "enabled": True,
                                "used": False,
                                "candidates": 0,
                                "run_reason": "keyword_primary",
                            },
                            "keyword_strategy": {
                                "primary": "lexical_db",
                                "bm25_secondary_enabled": False,
                                "bm25_used": True,
                                "lexical_db_used": False,
                            },
                        },
                    }
                }
            ]
        },
    }
    chat_body = {
        "citations": [
            {"document_id": xlsx_document_id},
        ],
        "content": "APAC belongs to Review in the Excel budget sheet.",
    }

    failures = evaluate_keyword_case(
        name="xlsx_only_bm25",
        xlsx_document_id=xlsx_document_id,
        retrieve_body=retrieve_body,
        chat_body=chat_body,
        require_first_doc=True,
    )

    assert failures == []


def test_keyword_bm25_fallback_probe_flags_vector_or_wrong_doc_drift() -> None:
    xlsx_document_id = "doc-xlsx"
    retrieve_body = {
        "citations": [
            {"document_id": "doc-docx"},
            {"document_id": "doc-yaml"},
        ],
        "metrics": {
            "retrieval_per_query": [
                {
                    "retriever_debug": {
                        "counts": {"vector_candidates": 2, "bm25_candidates": 0},
                        "channels": {
                            "vector": {"enabled": False, "candidates": 2, "filter_applied": True},
                            "lexical_db": {
                                "enabled": True,
                                "used": False,
                                "candidates": 0,
                                "run_reason": "keyword_primary",
                            },
                            "keyword_strategy": {
                                "primary": "lexical_db",
                                "bm25_secondary_enabled": False,
                                "bm25_used": False,
                                "lexical_db_used": False,
                            },
                        },
                    }
                }
            ]
        },
    }
    chat_body = {
        "citations": [{"document_id": "doc-docx"}],
        "content": "No Review answer here.",
    }

    failures = evaluate_keyword_case(
        name="xlsx_mixed_bm25",
        xlsx_document_id=xlsx_document_id,
        retrieve_body=retrieve_body,
        chat_body=chat_body,
        require_first_doc=True,
    )

    assert any("retrieve_missing_xlsx" in item for item in failures)
    assert any("chat_missing_xlsx" in item for item in failures)
    assert any("vector_candidates" in item for item in failures)
    assert any("bm25_candidates" in item for item in failures)
    assert any("bm25_used" in item for item in failures)
