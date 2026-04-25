from __future__ import annotations


def test_classify_chunk_type_detects_code() -> None:
    from app.rag.chunking.roles import ChunkType, classify_chunk_type

    out = classify_chunk_type(content="```python\nprint('hi')\n```", meta={})
    assert out == ChunkType.CODE.value


def test_classify_chunk_type_detects_formula() -> None:
    from app.rag.chunking.roles import ChunkType, classify_chunk_type

    out = classify_chunk_type(content="$$ a^2 + b^2 = c^2 $$", meta={"content_type": "formula"})
    assert out == ChunkType.FORMULA.value


def test_classify_chunk_type_detects_chart_data() -> None:
    from app.rag.chunking.roles import ChunkType, classify_chunk_type

    out = classify_chunk_type(content="Chart data:\n```json\n{\"title\":\"Q1\"}\n```", meta={"visual_kind": "chart"})
    assert out == ChunkType.CHART_DATA.value


def test_classify_chunk_type_detects_seal() -> None:
    from app.rag.chunking.roles import ChunkType, classify_chunk_type

    out = classify_chunk_type(content="杭州测试科技有限公司", meta={"doc_type_kwd": "seal"})
    assert out == ChunkType.SEAL.value
