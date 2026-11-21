import uuid

from langchain_core.documents import Document


def test_chunk_quality_scoring_detects_boilerplate_page_marker() -> None:
    from app.services.chunking.quality_scoring import score_chunk_quality

    q = score_chunk_quality("Page 1 of 10", meta={})
    assert q["schema"] == "mimirq.chunk_quality.v1"
    assert q["score"] < 0.4
    assert "boilerplate_page_marker" in (q.get("labels") or [])


def test_chunk_quality_scoring_normal_text_is_good() -> None:
    from app.services.chunking.quality_scoring import score_chunk_quality

    q = score_chunk_quality(
        "This section describes the authentication flow and the token refresh behavior.",
        meta={},
    )
    assert q["schema"] == "mimirq.chunk_quality.v1"
    assert q["score"] >= 0.7
    assert q["grade"] == "good"


def test_chunk_asset_stage_attaches_chunk_quality_metadata(monkeypatch) -> None:
    from app.rag.ingestion.indexing.support import stages
    from app.rag.ingestion.indexing.support.results import ChunkAssetOptions

    monkeypatch.setattr(stages.settings, "MINIO_ENABLED", False)
    out = stages.process_chunk_assets(
        chunks=[Document(page_content="Page 1 of 10", metadata={"source": "demo.pdf", "file_type": "pdf"})],
        tenant_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        options=ChunkAssetOptions(
            dataset_id=str(uuid.uuid4()),
            resolved_backend="basic",
            resolved_chunk_strategy="langchain_recursive",
        ),
    )
    assert out.chunks
    meta = out.chunks[0].metadata or {}
    q = meta.get("chunk_quality")
    assert isinstance(q, dict)
    assert q.get("schema") == "mimirq.chunk_quality.v1"
