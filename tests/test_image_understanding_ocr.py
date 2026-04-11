from pathlib import Path
from uuid import uuid4

import cv2
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


def test_chunk_asset_stage_adds_decoded_image_code_text_for_image_chunk(monkeypatch):  # noqa: ANN001
    import app.parsing.enrich.image_understanding as iu_mod
    import app.parsing.processors.processor as processor_mod

    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIO_IMAGE_MAX_BYTES", 0, raising=False)

    monkeypatch.setattr(
        iu_mod,
        "ocr_image",
        lambda *_a, **_k: "",
        raising=True,
    )
    monkeypatch.setattr(
        iu_mod,
        "decode_image_codes",
        lambda *_a, **_k: {"visual_kind": "qr", "text": "HELLO-QR", "values": ["HELLO-QR"]},
        raising=True,
    )
    monkeypatch.setattr(
        processor_mod.minio_service,
        "upload_image",
        lambda *_a, **_k: "img-qr",
        raising=True,
    )

    tenant_id = uuid4()
    image = PILImage.new("RGB", (2, 2), color=(255, 255, 255))
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

    assert out.chunks[0].metadata.get("img_id") == "img-qr"
    assert out.chunks[0].metadata.get("visual_kind") == "qr"
    assert out.chunks[0].metadata.get("image_code_text") == "HELLO-QR"
    assert "HELLO-QR" in (out.chunks[0].page_content or "")


def test_decode_image_codes_decodes_real_qr_generated_by_opencv() -> None:
    from app.parsing.enrich.image_understanding import decode_image_codes  # noqa: WPS433

    encoder = cv2.QRCodeEncoder_create()
    qr = encoder.encode("HELLO-QR")
    qr = cv2.copyMakeBorder(qr.astype("uint8"), 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    qr = cv2.resize(qr, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    image = PILImage.fromarray(qr, mode="L")

    out = decode_image_codes(image)

    assert out["visual_kind"] == "qr"
    assert out["text"] == "HELLO-QR"
    assert out["values"] == ["HELLO-QR"]


def test_decode_image_codes_decodes_committed_qr_fixture() -> None:
    from app.parsing.enrich.image_understanding import decode_image_codes  # noqa: WPS433

    fixture = Path("tests/fixtures/parsing_golden/qr_sheet/input/qr.png")
    image = PILImage.open(fixture)
    try:
        out = decode_image_codes(image)
    finally:
        image.close()

    assert out["visual_kind"] == "qr"
    assert out["text"] == "HELLO-QR"
