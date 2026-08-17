from __future__ import annotations

from scripts.build_parsing_retrieval_fixture import build_retrieval_fixture


def test_query_normalization_prefers_explicit_ids_and_preserves_first_occurrence() -> None:
    fixture = build_retrieval_fixture(
        documents=[
            {"chunk_id": "chunk-a", "document_id": "doc", "text": "Alpha"},
            {"chunk_id": "chunk-b", "document_id": "doc", "text": "Beta"},
        ],
        queries=[
            {
                "id": " explicit ",
                "question": " Where? ",
                "expected_chunk_ids": [" chunk-b ", "chunk-b", "", None],
                "expected_chunk_indexes": [0],
            }
        ],
    )

    assert fixture["queries"] == [
        {
            "id": "explicit",
            "question": "Where?",
            "expected_chunk_ids": ["chunk-b"],
        }
    ]


def test_query_normalization_uses_valid_indexes_only_when_ids_are_empty() -> None:
    fixture = build_retrieval_fixture(
        documents=[
            {"chunk_id": "chunk-a", "document_id": "doc", "text": "Alpha"},
            {"chunk_id": "chunk-b", "document_id": "doc", "text": "Beta"},
        ],
        queries=[
            {
                "id": "   ",
                "question": "Indexed",
                "expected_chunk_ids": ["", None],
                "expected_chunk_indexes": [1, "1", -1, 99, "bad"],
            },
            {"question": "No matches", "expected_chunk_indexes": [99]},
            {"question": "   ", "expected_chunk_ids": ["chunk-a"]},
        ],
    )

    assert fixture["queries"] == [
        {
            "id": "q-1",
            "question": "Indexed",
            "expected_chunk_ids": ["chunk-b"],
        }
    ]


def test_fixture_defaults_and_document_metadata_keep_existing_contract() -> None:
    fixture = build_retrieval_fixture(
        documents=[
            {
                "id": "chunk-a",
                "element_text": " Alpha ",
                "metadata": {"source": "source.md", "page": 3},
                "bbox": [1, 2, 3, 4],
            },
            {"id": "empty", "text": ""},
        ],
        queries=[{"question": "Alpha?", "expected_chunk_indexes": [0]}],
        top_k=0,
        retrieval_mode=" HYBRID ",
    )

    assert fixture == {
        "schema": "mimirq.sample_retrieval_fixture.v1",
        "defaults": {"top_k": 1, "retrieval_mode": "hybrid"},
        "documents": [
            {
                "chunk_id": "chunk-a",
                "document_id": "source.md",
                "text": "Alpha",
                "metadata": {
                    "source": "source.md",
                    "page": 3,
                    "bbox": [1, 2, 3, 4],
                },
            }
        ],
        "queries": [
            {
                "id": "q-1",
                "question": "Alpha?",
                "expected_chunk_ids": ["chunk-a"],
            }
        ],
    }
