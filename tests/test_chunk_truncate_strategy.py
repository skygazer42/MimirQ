from langchain_core.documents import Document

from app.parsing.processors.processor import _truncate_chunks_for_limit


def test_truncate_chunks_head_strategy_keeps_first_n():
    chunks = [
        Document(page_content="a", metadata={}),
        Document(page_content="b", metadata={}),
        Document(page_content="c", metadata={"doc_type_kwd": "image"}),
        Document(page_content="d", metadata={}),
    ]

    out, info = _truncate_chunks_for_limit(chunks, max_chunks=2, strategy="head")
    assert [c.page_content for c in out] == ["a", "b"]
    assert info["strategy"] == "head"
    assert info["asset_total"] == 1
    assert info["asset_kept"] == 0


def test_truncate_chunks_asset_uniform_keeps_first_and_assets_then_samples():
    chunks = [
        Document(page_content="t0", metadata={}),
        Document(page_content="t1", metadata={}),
        Document(page_content="img2", metadata={"doc_type_kwd": "image"}),
        Document(page_content="t3", metadata={}),
        Document(page_content="img4", metadata={"doc_type_kwd": "image"}),
        Document(page_content="t5", metadata={}),
    ]

    out, info = _truncate_chunks_for_limit(chunks, max_chunks=3, strategy="asset_uniform")
    assert [c.page_content for c in out] == ["t0", "img2", "img4"]
    assert info["strategy"] == "asset_uniform"
    assert info["asset_total"] == 2
    assert info["asset_kept"] == 2


def test_truncate_chunks_asset_uniform_uniformly_samples_non_asset_chunks():
    chunks = [
        Document(page_content="t0", metadata={}),
        Document(page_content="t1", metadata={}),
        Document(page_content="t2", metadata={}),
        Document(page_content="img3", metadata={"doc_type_kwd": "image"}),
        Document(page_content="t4", metadata={}),
        Document(page_content="t5", metadata={}),
        Document(page_content="t6", metadata={}),
        Document(page_content="t7", metadata={}),
    ]

    out, info = _truncate_chunks_for_limit(chunks, max_chunks=4, strategy="asset_uniform")
    assert [c.page_content for c in out] == ["t0", "t1", "img3", "t7"]
    assert info["asset_total"] == 1
    assert info["asset_kept"] == 1

