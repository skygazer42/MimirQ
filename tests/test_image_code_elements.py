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


def test_image_code_collects_pixel_visual_kind_without_name_heuristics(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/parsing_golden/table_scan/input/chart.png")
    neutral_asset = tmp_path / "asset.png"
    neutral_asset.write_bytes(fixture.read_bytes())

    out, added, audit = add_image_code_blocks(
        "![asset](asset.png)\n",
        origin_path=tmp_path,
    )

    assert added == 0
    assert "Image code:" not in out
    assert audit.code_elements[0]["kind"] == "image"
    assert audit.code_elements[0]["visual_kind"] == "chart"
    assert audit.code_elements[0]["text"] == "asset"
    assert audit.code_elements[0]["attributes"]["source_content_type"] == "image_understanding"


def test_inline_asset_stage_surfaces_pixel_visual_kind_sidecar_elements(tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/parsing_golden/diagram_page/input/diagram.png")
    neutral_asset = tmp_path / "asset.png"
    neutral_asset.write_bytes(fixture.read_bytes())

    stage = InlineAssetStage(service=object())
    result = stage.run(
        documents=[Document(page_content="![asset](asset.png)\n", metadata={"page": 2})],
        tenant_id=uuid4(),
        dataset_id="ds2",
        document_id=uuid4(),
        origin_path=tmp_path,
    )

    derived = result.documents[0].metadata["derived_elements"]
    assert derived[0]["kind"] == "image"
    assert derived[0]["visual_kind"] == "diagram"
    assert derived[0]["attributes"]["image_visual_kind_source"] == "pixel"

    elements = normalize_document_elements(result.documents)
    assert [item["kind"] for item in elements] == ["paragraph", "image"]
    assert elements[1]["visual_kind"] == "diagram"
    assert elements[1]["text"] == "asset"
