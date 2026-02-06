from __future__ import annotations


def test_build_candidate_payload_includes_header_path_and_structure() -> None:
    from app.rag.reranker.llm_based import _build_candidate_payload

    meta = {
        "header_path": "H1 > H2",
        "structure": {
            "list": {"item_count": 3, "min_level": 0, "max_level": 2},
            "table": {"title": "Orders", "sheet_name": "Sheet 1"},
        },
    }
    out = _build_candidate_payload(cid="c1", text="hello world", meta=meta, max_chars=1000)
    assert out is not None
    assert out.get("id") == "c1"
    assert out.get("header_path") == "H1 > H2"

    structure = out.get("structure") or {}
    assert isinstance(structure, dict)
    assert (structure.get("list") or {}).get("item_count") == 3
    assert (structure.get("table") or {}).get("title") == "Orders"


def test_build_candidate_payload_truncates_text_and_header_path() -> None:
    from app.rag.reranker.llm_based import _build_candidate_payload

    meta = {"header_path": "x" * 1000}
    out = _build_candidate_payload(cid="c1", text="y" * 20, meta=meta, max_chars=10)
    assert out is not None
    assert out.get("text") == ("y" * 10 + "...")
    assert isinstance(out.get("header_path"), str)
    assert len(str(out.get("header_path") or "")) <= 200

