from pathlib import Path
from uuid import uuid4

import cv2
from langchain_core.documents import Document
from PIL import Image as PILImage
from PIL import ImageDraw

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


def _build_ean13_image(data12: str) -> PILImage.Image:
    l_codes = {"0": "0001101", "1": "0011001", "2": "0010011", "3": "0111101", "4": "0100011", "5": "0110001", "6": "0101111", "7": "0111011", "8": "0110111", "9": "0001011"}
    g_codes = {"0": "0100111", "1": "0110011", "2": "0011011", "3": "0100001", "4": "0011101", "5": "0111001", "6": "0000101", "7": "0010001", "8": "0001001", "9": "0010111"}
    r_codes = {"0": "1110010", "1": "1100110", "2": "1101100", "3": "1000010", "4": "1011100", "5": "1001110", "6": "1010000", "7": "1000100", "8": "1001000", "9": "1110100"}
    parity_patterns = {"0": "LLLLLL", "1": "LLGLGG", "2": "LLGGLG", "3": "LLGGGL", "4": "LGLLGG", "5": "LGGLLG", "6": "LGGGLL", "7": "LGLGLG", "8": "LGLGGL", "9": "LGGLGL"}

    def checksum12(value: str) -> str:
        total = 0
        for index, ch in enumerate(value, start=1):
            digit = int(ch)
            total += digit if index % 2 == 1 else 3 * digit
        return str((10 - (total % 10)) % 10)

    full = data12 + checksum12(data12)
    bits = "101"
    for digit, parity in zip(full[1:7], parity_patterns[full[0]], strict=True):
        bits += l_codes[digit] if parity == "L" else g_codes[digit]
    bits += "01010"
    for digit in full[7:]:
        bits += r_codes[digit]
    bits += "101"

    module = 4
    quiet_zone = 12
    width = (len(bits) + quiet_zone * 2) * module
    height = 160
    image = PILImage.new("L", (width, height), color=255)
    draw = ImageDraw.Draw(image)
    cursor = quiet_zone * module
    for bit in bits:
        if bit == "1":
            draw.rectangle([cursor, 0, cursor + module - 1, height - 1], fill=0)
        cursor += module
    return image


def test_decode_image_codes_decodes_real_ean13_barcode() -> None:
    from app.parsing.enrich.image_understanding import decode_image_codes  # noqa: WPS433

    image = _build_ean13_image("590123412345")

    out = decode_image_codes(image)

    assert out["visual_kind"] == "barcode"
    assert out["text"] == "5901234123457"
    assert out["values"] == ["5901234123457"]


def test_decode_image_codes_decodes_committed_barcode_fixture() -> None:
    from app.parsing.enrich.image_understanding import decode_image_codes  # noqa: WPS433

    fixture = Path("tests/fixtures/parsing_golden/barcode_label/input/barcode.png")
    image = PILImage.open(fixture)
    try:
        out = decode_image_codes(image)
    finally:
        image.close()

    assert out["visual_kind"] == "barcode"
    assert out["text"] == "5901234123457"


def test_infer_visual_kind_from_pixels_detects_committed_chart_fixture() -> None:
    from app.parsing.enrich.image_understanding import infer_visual_kind_from_pixels  # noqa: WPS433

    fixture = Path("tests/fixtures/parsing_golden/table_scan/input/chart.png")
    image = PILImage.open(fixture)
    try:
        out = infer_visual_kind_from_pixels(image)
    finally:
        image.close()

    assert out == "chart"


def test_infer_visual_kind_from_pixels_detects_synthetic_line_chart() -> None:
    from app.parsing.enrich.image_understanding import infer_visual_kind_from_pixels  # noqa: WPS433

    image = PILImage.new("RGB", (320, 220), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.line((32, 24, 32, 186), fill=(0, 0, 0), width=4)
    draw.line((32, 186, 286, 186), fill=(0, 0, 0), width=4)
    points = [(48, 162), (92, 142), (138, 150), (184, 112), (232, 94), (272, 68)]
    draw.line(points, fill=(33, 102, 172), width=6)
    for x, y in points:
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(33, 102, 172))

    out = infer_visual_kind_from_pixels(image)

    assert out == "chart"


def test_infer_visual_kind_from_pixels_detects_committed_line_chart_fixture() -> None:
    from app.parsing.enrich.image_understanding import infer_visual_kind_from_pixels  # noqa: WPS433

    fixture = Path("tests/fixtures/parsing_golden_broader/line_chart_pdf/input/line_chart.png")
    image = PILImage.open(fixture)
    try:
        out = infer_visual_kind_from_pixels(image)
    finally:
        image.close()

    assert out == "chart"


def test_infer_visual_kind_from_pixels_detects_committed_diagram_fixture() -> None:
    from app.parsing.enrich.image_understanding import infer_visual_kind_from_pixels  # noqa: WPS433

    fixture = Path("tests/fixtures/parsing_golden/diagram_page/input/diagram.png")
    image = PILImage.open(fixture)
    try:
        out = infer_visual_kind_from_pixels(image)
    finally:
        image.close()

    assert out == "diagram"


def test_infer_visual_kind_from_pixels_detects_committed_broader_diagram_fixture() -> None:
    from app.parsing.enrich.image_understanding import infer_visual_kind_from_pixels  # noqa: WPS433

    fixture = Path("tests/fixtures/parsing_golden_broader/diagram_pdf/input/diagram.png")
    image = PILImage.open(fixture)
    try:
        out = infer_visual_kind_from_pixels(image)
    finally:
        image.close()

    assert out == "diagram"


def test_chunk_asset_stage_falls_back_to_pixel_visual_kind_for_image_chunk(monkeypatch):  # noqa: ANN001
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
        lambda *_a, **_k: {},
        raising=True,
    )
    monkeypatch.setattr(
        iu_mod,
        "infer_visual_kind_from_pixels",
        lambda *_a, **_k: "chart",
        raising=True,
    )
    monkeypatch.setattr(
        processor_mod.minio_service,
        "upload_image",
        lambda *_a, **_k: "img-chart",
        raising=True,
    )

    tenant_id = uuid4()
    image = PILImage.new("RGB", (32, 32), color=(255, 255, 255))
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

    assert out.chunks[0].metadata.get("img_id") == "img-chart"
    assert out.chunks[0].metadata.get("visual_kind") == "chart"


def test_chunk_asset_stage_infers_pixel_visual_kind_without_image_ocr(monkeypatch):  # noqa: ANN001
    import app.parsing.enrich.image_understanding as iu_mod
    import app.parsing.processors.processor as processor_mod

    monkeypatch.setattr(settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINIO_IMAGE_MAX_BYTES", 0, raising=False)

    monkeypatch.setattr(
        iu_mod,
        "decode_image_codes",
        lambda *_a, **_k: {},
        raising=True,
    )
    monkeypatch.setattr(
        iu_mod,
        "infer_visual_kind_from_pixels",
        lambda *_a, **_k: "diagram",
        raising=True,
    )
    monkeypatch.setattr(
        iu_mod,
        "ocr_image",
        lambda *_a, **_k: "UNUSED",
        raising=True,
    )
    monkeypatch.setattr(
        processor_mod.minio_service,
        "upload_image",
        lambda *_a, **_k: "img-diagram",
        raising=True,
    )

    tenant_id = uuid4()
    image = PILImage.new("RGB", (32, 32), color=(255, 255, 255))
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
        image_ocr_enabled=False,
        image_ocr_max_chars=2000,
    )

    assert out.chunks[0].metadata.get("img_id") == "img-diagram"
    assert out.chunks[0].metadata.get("visual_kind") == "diagram"
    assert out.chunks[0].metadata.get("image_ocr_text") is None
