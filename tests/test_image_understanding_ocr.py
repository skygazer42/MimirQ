from uuid import uuid4

from langchain_core.documents import Document
from PIL import Image as PILImage

from app.core.config import settings
from app.parsing.processors.processor import ChunkAssetStage, DocumentProcessorService


def test_chunk_asset_stage_adds_ocr_text_for_image_chunk(monkeypatch):  # noqa: ANN001
    import app.parsing.enrich.image_understanding as iu_mod
    import app.parsing.processors.processor as processor_mod

    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIO_IMAGE_MAX_BYTES", 0, raising=False)

    monkeypatch.setattr(
        iu_mod,
        "ocr_image",
        lambda *_a, **_k: "HELLO_OCR",
        raising=True,
    )

    monkeypatch.setattr(
        processor_mod.minio_service,
        "upload_image",
        lambda *_a, **_k: "img-1",
        raising=True,
    )

    tenant_id = uuid4()
    image = PILImage.new("RGB", (2, 2), color=(255, 0, 0))
    chunks = [
        Document(
            page_content="",
            metadata={"doc_type_kwd": "image", "image": image},
        )
    ]

    stage = ChunkAssetStage(DocumentProcessorService())
    out = stage.run(
        chunks=chunks,
        tenant_id=tenant_id,
        dataset_id="ds",
        document_id=uuid4(),
        resolved_backend="basic",
        resolved_chunk_strategy="basic",
        image_ocr_enabled=True,
        image_ocr_max_chars=2000,
    )

    assert out.chunks[0].metadata.get("img_id") == "img-1"
    assert out.chunks[0].metadata.get("image_ocr_text") == "HELLO_OCR"
    assert "HELLO_OCR" in (out.chunks[0].page_content or "")

