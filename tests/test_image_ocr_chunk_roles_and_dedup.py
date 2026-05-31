from __future__ import annotations

import uuid

from langchain_core.documents import Document

import app.parsing.enrich.image_understanding as iu
from app.parsing.processors.processor import ChunkAssetOptions, ChunkAssetStage


class _FakeProcessorSvc:
    """
    Minimal stub for ChunkAssetStage unit tests.

    We avoid MinIO + real image decoding. This test focuses on metadata roles and OCR dedup behavior.
    """

    def _extract_and_upload_image_to_minio(  # noqa: ANN001
        self,
        metadata,
        tenant_id,
        dataset_id,
        document_id,
        chunk_index,
        **_kwargs,
    ):
        # Best-effort: avoid leaving non-serializable objects in metadata during tests.
        metadata.pop("image", None)
        return None

    def _extract_img_id_from_content(self, _content):  # noqa: ANN001
        return None


def test_image_and_ocr_chunks_get_roles_and_ocr_is_separate(monkeypatch):  # noqa: ANN001
    # Stub OCR pipeline to avoid external dependencies.
    monkeypatch.setattr(iu, "load_image_for_ocr", lambda _meta, _tenant_id: ("img", False), raising=True)
    monkeypatch.setattr(iu, "ocr_image", lambda _img, _max_chars=2000: "HELLO", raising=True)

    stage = ChunkAssetStage(_FakeProcessorSvc())

    tenant_id = uuid.uuid4()
    dataset_id = str(uuid.uuid4())
    document_id = uuid.uuid4()

    chunks = [
        Document(
            page_content="Page 1",
            metadata={"doc_type_kwd": "image", "image": "dummy", "page": 1, "source": "demo.pdf"},
        )
    ]

    res = stage.run(
        chunks=chunks,
        tenant_id=tenant_id,
        document_id=document_id,
        options=ChunkAssetOptions(
            dataset_id=dataset_id,
            resolved_backend="docling",
            resolved_chunk_strategy="pdf_layout",
            image_caption_enabled=False,
            image_ocr_enabled=True,
            image_ocr_max_chars=2000,
            image_ocr_max_images=20,
        ),
    )

    out = res.chunks
    roles = [str((c.metadata or {}).get("chunk_role") or "") for c in out]
    assert "image" in roles
    assert "ocr" in roles

    img = next(c for c in out if (c.metadata or {}).get("chunk_role") == "image")
    ocr = next(c for c in out if (c.metadata or {}).get("chunk_role") == "ocr")

    assert (img.metadata or {}).get("image_ocr_text") == "HELLO"
    assert (ocr.page_content or "").strip() == "HELLO"
    assert (ocr.metadata or {}).get("doc_type_kwd") == "ocr"
    assert (ocr.metadata or {}).get("image_parent_chunk_index") == (img.metadata or {}).get("chunk_index")


def test_duplicate_ocr_chunks_are_deduped_by_hash(monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(iu, "load_image_for_ocr", lambda _meta, _tenant_id: ("img", False), raising=True)
    monkeypatch.setattr(iu, "ocr_image", lambda _img, _max_chars=2000: "SAME", raising=True)

    stage = ChunkAssetStage(_FakeProcessorSvc())

    tenant_id = uuid.uuid4()
    dataset_id = str(uuid.uuid4())
    document_id = uuid.uuid4()

    chunks = [
        Document(page_content="Page 1", metadata={"doc_type_kwd": "image", "image": "a", "page": 1, "source": "demo.pdf"}),
        Document(page_content="Page 2", metadata={"doc_type_kwd": "image", "image": "b", "page": 2, "source": "demo.pdf"}),
    ]

    res = stage.run(
        chunks=chunks,
        tenant_id=tenant_id,
        document_id=document_id,
        options=ChunkAssetOptions(
            dataset_id=dataset_id,
            resolved_backend="docling",
            resolved_chunk_strategy="pdf_layout",
            image_caption_enabled=False,
            image_ocr_enabled=True,
            image_ocr_max_chars=2000,
            image_ocr_max_images=20,
        ),
    )

    out = res.chunks
    ocr_chunks = [c for c in out if (c.metadata or {}).get("chunk_role") == "ocr"]
    assert len(ocr_chunks) == 1
    assert (ocr_chunks[0].page_content or "").strip() == "SAME"
