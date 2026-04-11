from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from langchain_core.documents import Document

from app.parsing.enrich.image_code import add_image_code_blocks
from app.parsing.processors.processor import InlineAssetStage
from app.parsing.utils.document_elements import normalize_document_elements


def test_image_code_collects_structured_elements_from_local_qr_asset() -> None:
    fixture_root = Path("tests/fixtures/parsing_golden/qr_sheet/input")

    out, added, audit = add_image_code_blocks(
        "![qrcode](qr.png)\n",
        origin_path=fixture_root,
    )

    assert added == 1
    assert "Image code: HELLO-QR" in out
    assert audit.code_elements[0]["kind"] == "image"
    assert audit.code_elements[0]["visual_kind"] == "qr"
    assert audit.code_elements[0]["text"] == "HELLO-QR"


def test_inline_asset_stage_surfaces_image_code_sidecar_elements() -> None:
    fixture_root = Path("tests/fixtures/parsing_golden/barcode_label/input")

    stage = InlineAssetStage(service=object())
    result = stage.run(
        documents=[Document(page_content="![barcode](barcode.png)\n", metadata={"page": 4})],
        tenant_id=uuid4(),
        dataset_id="ds1",
        document_id=uuid4(),
        origin_path=fixture_root,
    )

    derived = result.documents[0].metadata["derived_elements"]
    assert derived[0]["kind"] == "image"
    assert derived[0]["visual_kind"] == "barcode"
    assert derived[0]["text"] == "5901234123457"

    elements = normalize_document_elements(result.documents)
    assert [item["kind"] for item in elements] == ["paragraph", "image"]
    assert elements[1]["visual_kind"] == "barcode"
    assert elements[1]["text"] == "5901234123457"
