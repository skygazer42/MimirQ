from types import SimpleNamespace

from app.rag.retrieval.sibling_expand import expand_document_siblings, select_document_expansion_mode


def _row(
    chunk_id: str,
    *,
    chunk_index: int,
    header_path: str | None = "Guide",
    content: str = "body",
) -> SimpleNamespace:
    metadata = {} if header_path is None else {"header_path": header_path}
    return SimpleNamespace(
        id=chunk_id,
        tenant_id="tenant-1",
        document_id="doc-short",
        chunk_index=chunk_index,
        page_number=chunk_index + 1,
        start_char=chunk_index * 10,
        end_char=(chunk_index + 1) * 10,
        content=content,
        doc_metadata=metadata,
    )


def test_expand_document_siblings_preserves_order_filters_and_metadata() -> None:
    anchor = {
        "chunk_id": "anchor",
        "content": "anchor body",
        "metadata": {"document_id": "doc-short", "header_path": "Guide"},
        "score": 0.5,
    }
    repeated_short_doc_result = {
        "chunk_id": "ignored-anchor",
        "metadata": {"document_id": "doc-short", "header_path": "Guide"},
        "score": 0.6,
    }
    normal = {
        "chunk_id": "normal",
        "content": "normal body",
        "metadata": {"document_id": "doc-long"},
        "score": 0.5,
    }
    rows = [
        _row("different-heading", chunk_index=3, header_path="Other"),
        _row("sibling", chunk_index=2, content="sibling body"),
        _row("anchor", chunk_index=1),
        _row("", chunk_index=4),
    ]

    expanded = expand_document_siblings(
        results=[anchor, repeated_short_doc_result, normal, normal],
        document_chunks_by_doc={"doc-short": rows},
        short_doc_ids={"doc-short"},
        max_added=1,
        original_results_by_chunk_id={"anchor": anchor},
    )

    assert expanded == [
        anchor,
        {
            "chunk_id": "sibling",
            "content": "sibling body",
            "metadata": {
                "header_path": "Guide",
                "tenant_id": "tenant-1",
                "document_id": "doc-short",
                "chunk_index": 2,
                "chunk_id": "sibling",
                "page": 3,
                "start_char": 20,
                "end_char": 30,
                "sibling_of": "anchor",
                "retrieval_role": "sibling",
            },
            "score": 0.4,
        },
        normal,
    ]


def test_expand_document_siblings_builds_original_map_and_honors_global_budget() -> None:
    first_anchor = {
        "chunk_id": "first",
        "metadata": {"document_id": "doc-one"},
        "score": 1.0,
    }
    second_anchor = {
        "chunk_id": "second",
        "metadata": {"document_id": "doc-two"},
        "score": 0.5,
    }
    rows_by_doc = {
        "doc-one": [_row("first", chunk_index=0, header_path=None), _row("first-added", chunk_index=1)],
        "doc-two": [
            SimpleNamespace(
                **{
                    **vars(_row("second", chunk_index=0, header_path=None)),
                    "document_id": "doc-two",
                }
            ),
            SimpleNamespace(
                **{
                    **vars(_row("budget-skipped", chunk_index=1)),
                    "document_id": "doc-two",
                }
            ),
        ],
    }

    expanded = expand_document_siblings(
        results=[first_anchor, second_anchor],
        document_chunks_by_doc=rows_by_doc,
        short_doc_ids={"doc-one", "doc-two"},
        max_added=1,
    )

    assert [item["chunk_id"] for item in expanded] == ["first", "first-added", "second"]
    assert expanded[1]["score"] == 0.8


def test_select_document_expansion_mode_handles_thresholds_and_invalid_values() -> None:
    assert select_document_expansion_mode(total_chunks=2, short_doc_max_chunks=3) == "sibling"
    assert select_document_expansion_mode(total_chunks=4, short_doc_max_chunks=3) == "neighbor"
    assert select_document_expansion_mode(total_chunks="bad", short_doc_max_chunks=3) == "neighbor"
    assert select_document_expansion_mode(total_chunks=2, short_doc_max_chunks="bad") == "neighbor"
