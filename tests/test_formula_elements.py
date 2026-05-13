from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.enrich.formula_ocr import add_formula_latex_blocks
from app.parsing.processors.processor import InlineAssetStage
from app.parsing.utils.document_elements import normalize_document_elements


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, headers: dict[str, str] | None = None, json_body: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/json"}
        self._json_body = json_body or {"latex": "a^2 + b^2 = c^2"}
        self.text = ""
        self.content = b"unused"

    def json(self):  # noqa: ANN201
        return self._json_body


def test_formula_ocr_collects_structured_equation_elements(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "eq.png"
    img.write_bytes(b"fake-bytes")

    async def _fake_backend_async(**_kwargs):  # noqa: ANN001
        return ("a^2 + b^2 = c^2", "ok_json")

    monkeypatch.setattr(
        "app.parsing.enrich.formula_ocr._call_formula_backend_async",
        _fake_backend_async,
    )

    out, added, audit = add_formula_latex_blocks(
        "![formula](eq.png)\n",
        origin_path=tmp_path,
        api_url="http://example/formula",
    )

    assert added == 1
    assert "$$ a^2 + b^2 = c^2 $$" in out
    assert audit.formula_elements[0]["kind"] == "equation"
    assert audit.formula_elements[0]["text"] == "a^2 + b^2 = c^2"
    assert audit.formula_elements[0]["attributes"]["formula_image_src"] == "eq.png"
    assert audit.formula_elements[0]["attributes"]["source_content_type"] == "formula_ocr"


def test_inline_asset_stage_surfaces_formula_sidecar_elements(monkeypatch, tmp_path: Path) -> None:
    img = tmp_path / "eq.png"
    img.write_bytes(b"fake-bytes")

    async def _fake_backend_async(**_kwargs):  # noqa: ANN001
        return ("E = mc^2", "ok_json")

    monkeypatch.setattr(
        "app.parsing.enrich.formula_ocr._call_formula_backend_async",
        _fake_backend_async,
    )
    monkeypatch.setattr(settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "FORMULA_OCR_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "FORMULA_OCR_API_URL", "http://example/formula", raising=False)

    stage = InlineAssetStage(service=object())
    result = stage.run(
        documents=[Document(page_content="![formula](eq.png)\n", metadata={"page": 3})],
        tenant_id=uuid4(),
        dataset_id="ds1",
        document_id=uuid4(),
        origin_path=tmp_path,
    )

    assert result.formulas_added == 1
    derived = result.documents[0].metadata["derived_elements"]
    assert derived[0]["kind"] == "equation"
    assert derived[0]["page"] == 3
    assert derived[0]["attributes"]["formula_image_src"] == "eq.png"

    elements = normalize_document_elements(result.documents)
    assert [item["kind"] for item in elements] == ["paragraph", "equation"]
    assert elements[1]["page"] == 3
    assert elements[1]["text"] == "E = mc^2"
    assert elements[1]["attributes"]["source_doc_type"] == "formula_ocr"
