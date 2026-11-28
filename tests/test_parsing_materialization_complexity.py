import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.documents import Document
from PIL import Image

import app.rag.ingestion.parsing.subprocess_worker as worker
from app.rag.ingestion.parsing.enrich.image_ocr import add_image_ocr_blocks
from app.rag.ingestion.parsing.processors import parser_service
from app.rag.ingestion.parsing.utils import zip_processor


def _write_png(path: Path, *, color: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (2, 2), color=color)
    image.save(path, format="PNG")
    return path.read_bytes()


def _write_zip(path: Path, members: dict[str, bytes | str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def test_preview_local_materialization_rewrites_refs_deduplicates_bytes_and_persists_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_id = uuid4()
    asset_dir = tmp_path / "assets"
    upload_dir = tmp_path / "uploads"
    first = asset_dir / "images" / "one.png"
    second = asset_dir / "nested" / "two.png"
    image_bytes = _write_png(first)
    second.parent.mkdir(parents=True, exist_ok=True)
    second.write_bytes(image_bytes)
    monkeypatch.setattr(
        "app.rag.ingestion.parsing.processors.parser_service.settings.UPLOAD_DIR", str(upload_dir), raising=False
    )

    document = Document(
        page_content='![one](images/one.png)\n<img src="nested/two.png">',
        metadata={"asset_base_dir": str(asset_dir)},
    )

    images = parser_service._materialize_local_images_for_preview(
        [document],
        tenant_id,
        owner_binding={"tenant_id": str(tenant_id), "account_id": "preview-owner"},
    )

    assert len(images) == 1
    saved = images[0]
    assert set(saved) == {"id", "filename", "path", "url"}
    assert saved["url"] == f"/api/v1/documents/image/{saved['id']}"
    assert Path(saved["path"]).read_bytes() == image_bytes
    assert (Path(saved["path"]).with_suffix(".json")).read_text(encoding="utf-8") == (
        f'{{"account_id":"preview-owner","tenant_id":"{tenant_id}"}}'
    )
    assert document.page_content == (f'![one]({saved["url"]})\n<img src="{saved["url"]}">')


def test_preview_local_materialization_keeps_refs_without_owner_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_id = uuid4()
    asset_dir = tmp_path / "assets"
    image_path = asset_dir / "scan.png"
    _write_png(image_path, color=(0, 0, 0))
    monkeypatch.setattr(
        "app.rag.ingestion.parsing.processors.parser_service.settings.UPLOAD_DIR",
        str(tmp_path / "uploads"),
        raising=False,
    )

    document = Document(page_content="![scan](scan.png)", metadata={"asset_base_dir": str(asset_dir)})

    images = parser_service._materialize_local_images_for_preview(
        [document],
        tenant_id,
        owner_binding=None,
    )

    assert images == []
    assert document.page_content == "![scan](scan.png)"
    assert list((tmp_path / "uploads").rglob("*.png")) == []


def test_ingest_materialization_sets_artifact_paths_and_drops_non_image_payloads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_id = uuid4()
    upload_dir = tmp_path / "uploads"
    artifact_root = upload_dir / "artifacts"
    monkeypatch.setattr(
        "app.rag.ingestion.parsing.subprocess_worker.settings.UPLOAD_DIR", str(upload_dir), raising=False
    )
    image_doc = Document(
        page_content="caption",
        metadata={"doc_type_kwd": "image", "image": _write_png(tmp_path / "raw.png")},
    )
    non_image_doc = Document(page_content="body", metadata={"doc_type_kwd": "text", "image": b"unused"})

    materialized = worker._materialize_images_for_ingest(
        [image_doc, non_image_doc],
        tenant_id=tenant_id,
        artifact_root=artifact_root,
    )

    image_meta = materialized[0].metadata
    assert image_meta["artifact_dir"] == str(artifact_root)
    assert image_meta["image_path"].startswith(str((artifact_root / "images").resolve(strict=False)))
    assert "image" not in image_meta
    assert Path(image_meta["image_path"]).exists()

    assert materialized[1].metadata == {"doc_type_kwd": "text"}


def test_ingest_materialization_propagates_write_failure_and_closes_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_id = uuid4()
    upload_dir = tmp_path / "uploads"
    artifact_root = upload_dir / "artifacts"
    monkeypatch.setattr(
        "app.rag.ingestion.parsing.subprocess_worker.settings.UPLOAD_DIR", str(upload_dir), raising=False
    )

    class _BrokenImage:
        def __init__(self) -> None:
            self.mode = "RGB"
            self.closed = False

        def save(self, *_args, **_kwargs) -> None:
            raise OSError("cannot persist")

        def close(self) -> None:
            self.closed = True

    broken = _BrokenImage()
    monkeypatch.setattr(worker, "_get_pil_image", lambda: object())

    document = Document(page_content="caption", metadata={"doc_type_kwd": "image", "image": broken})

    with pytest.raises(OSError, match="cannot persist"):
        worker._materialize_images_for_ingest(
            [document],
            tenant_id=tenant_id,
            artifact_root=artifact_root,
        )

    assert document.metadata["image"] is broken
    assert list(artifact_root.rglob("*.jpg")) == []
    assert broken.closed is True


def test_add_image_ocr_blocks_inserts_after_matching_lines_and_skips_existing_or_fenced(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "scan.png"
    _write_png(image_path)
    responses = iter(["first text", "second text"])

    monkeypatch.setattr(
        "app.rag.ingestion.parsing.enrich.image_ocr.ocr_image", lambda *_args, **_kwargs: next(responses)
    )

    markdown = "\n".join(
        [
            "Start",
            "![one](scan.png)",
            "Paragraph",
            "![skip](scan.png)",
            "Image OCR:",
            "already there",
            "```md",
            "![fenced](scan.png)",
            "```",
            '<img src="scan.png" alt="two">',
            "Done",
        ]
    )

    rewritten, added, audit = add_image_ocr_blocks(markdown, origin_path=tmp_path)

    assert added == 2
    assert audit.ocr_blocks_added == 2
    assert audit.images_attempted == 2
    assert audit.images_succeeded == 2
    assert rewritten.splitlines() == [
        "Start",
        "![one](scan.png)",
        "Image OCR:",
        "first text",
        "Paragraph",
        "![skip](scan.png)",
        "Image OCR:",
        "already there",
        "```md",
        "![fenced](scan.png)",
        "```",
        '<img src="scan.png" alt="two">',
        "Image OCR:",
        "second text",
        "Done",
    ]


def test_safe_extract_rejects_zip_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    _write_zip(archive_path, {"../escape.md": "bad"})

    with zipfile.ZipFile(archive_path, "r") as archive, pytest.raises(ValueError, match="Path traversal"):
        zip_processor.safe_extract_zip(archive, tmp_path / "out")


def test_process_zip_with_images_returns_local_fallback_schema_when_minio_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "bundle.zip"
    image_bytes = _write_png(tmp_path / "chart.png")
    _write_zip(
        archive_path,
        {
            "result.md": "![chart](chart.png)\n",
            "chart.png": image_bytes,
        },
    )
    monkeypatch.setattr("app.rag.ingestion.parsing.utils.zip_processor.settings.MINIO_ENABLED", False, raising=False)

    result = zip_processor.process_zip_with_images(
        archive_path,
        dataset_id="dataset-1",
        document_id="document-1",
        tenant_id="tenant-1",
    )

    assert result == {
        "markdown": "![chart](chart.png)\n",
        "images": [],
        "image_count": 0,
    }


def test_process_zip_with_images_uploads_images_and_rewrites_markdown_when_minio_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "bundle.zip"
    image_bytes = _write_png(tmp_path / "figure.png", color=(0, 128, 255))
    _write_zip(
        archive_path,
        {
            "docs/result.md": '![chart](figure.png)\n<img src="figure.png">',
            "docs/figure.png": image_bytes,
        },
    )
    monkeypatch.setattr("app.rag.ingestion.parsing.utils.zip_processor.settings.MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "app.rag.ingestion.parsing.utils.zip_processor.minio_service.upload_image",
        lambda **_kwargs: "img-123",
        raising=True,
    )

    result = zip_processor.process_zip_with_images(
        archive_path,
        dataset_id="dataset-1",
        document_id="document-1",
        tenant_id="tenant-1",
    )

    assert result == {
        "markdown": '![chart](/api/v1/documents/image-url/img-123)\n<img src="/api/v1/documents/image-url/img-123">',
        "images": [
            {
                "img_id": "img-123",
                "original_path": "docs/figure.png",
                "url": "/api/v1/documents/image-url/img-123",
            }
        ],
        "image_count": 1,
    }
