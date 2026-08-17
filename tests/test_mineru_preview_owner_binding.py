import io
import json
import zipfile
from pathlib import Path
from uuid import uuid4


def _zip_bytes_with_markdown_and_image() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("output.md", "![preview](images/demo.png)\n")
        zf.writestr("images/demo.png", b"\x89PNG\r\n\x1a\npng-data")
    return buf.getvalue()


def test_mineru_preview_image_sidecar_binds_owner_account(monkeypatch, tmp_path) -> None:
    from app.services.mineru_service import MinerUService

    tenant_id = str(uuid4())
    account_id = "preview-owner"
    monkeypatch.setattr("app.services.mineru_service.settings.UPLOAD_DIR", str(tmp_path), raising=False)

    service = MinerUService()
    markdown, images = service._extract_preview_images_from_zip_bytes(
        zip_bytes=_zip_bytes_with_markdown_and_image(),
        markdown="![preview](images/demo.png)\n",
        tenant_id=tenant_id,
        account_id=account_id,
    )

    assert "/api/v1/documents/image/" in markdown
    assert len(images) == 1
    image_id = str(images[0]["id"])
    sidecar_path = Path(tmp_path) / tenant_id / "images" / f"{image_id}.json"
    assert sidecar_path.exists()
    assert json.loads(sidecar_path.read_text(encoding="utf-8")) == {
        "account_id": account_id,
        "tenant_id": tenant_id,
    }


def test_mineru_parser_forwards_account_id_to_preview_service(monkeypatch, tmp_path) -> None:
    from app.parsing.parsers.mineru_parser import MinerUParser

    captured: dict[str, object] = {}
    file_path = tmp_path / "demo.pdf"
    file_path.write_bytes(b"%PDF-1.4\n")

    def _fake_parse_file_local(**kwargs):  # noqa: ANN003, ANN202
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "app.parsing.parsers.mineru_parser.settings.MINERU_LOCAL_SERVER_URL", "http://mineru.local", raising=False
    )
    monkeypatch.setattr(
        "app.parsing.parsers.mineru_parser.mineru_service.parse_file_local", _fake_parse_file_local, raising=True
    )

    parser = MinerUParser()
    parser.parse(
        file_path,
        tenant_id=str(uuid4()),
        account_id="preview-owner",
    )

    assert captured["account_id"] == "preview-owner"


def test_document_parser_preview_forwards_owner_to_parser_factory(monkeypatch, tmp_path) -> None:
    from app.parsing.processors.parser_service import DocumentParserService

    captured: dict[str, object] = {}
    file_path = tmp_path / "demo.txt"
    file_path.write_text("preview", encoding="utf-8")

    def _fake_parse(_file_path, **kwargs):  # noqa: ANN001, ANN003, ANN202
        captured.update(kwargs)
        return [], "basic"

    monkeypatch.setattr("app.parsing.processors.parser_service.parser_factory.parse", _fake_parse)

    DocumentParserService().parse_for_preview(
        file_path=file_path,
        tenant_id=uuid4(),
        account_id="preview-owner",
    )

    assert captured["account_id"] == "preview-owner"
