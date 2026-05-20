from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.parsing.enrich.image_caption import add_image_captions
from tests.helpers.async_utils import yield_control


def test_add_image_captions_inserts_caption_for_markdown_image_line() -> None:
    md = "Hello\n\n![Diagram](assets/diagram.png)\n\nBye\n"
    out, added = add_image_captions(md)
    assert added == 1
    assert "Image caption: Diagram" in out


def test_add_image_captions_preserves_blockquote_prefix() -> None:
    md = "> ![](img/logo.png)\n"
    out, added = add_image_captions(md)
    assert added == 1
    assert "> Image caption: logo.png" in out


def test_parsing_workspace_image_caption_toggle(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.parsing as parsing_module
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    src_path = tmp_path / "demo.txt"
    src_path.write_text("dummy", encoding="utf-8")

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = uuid.uuid4()
            self.filename = "demo.txt"
            self.file_type = "txt"
            self.file_path = str(src_path)
            self.status = "pending"
            self.processing_progress = 0
            self.current_stage = "parsing"
            self.error_message = None
            self.total_characters = 0
            self.chunk_count = 0
            self.doc_metadata = {"workspace": "parsing", "parser_backend_requested": "auto"}

    dummy_doc = _DummyDoc()

    monkeypatch.setattr(parsing_module, "_get_workspace_document", lambda *_a, **_k: dummy_doc, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(parsing_module, "_assert_path_under_tenant_root", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(parsing_module, "is_minio_uri", lambda *_a, **_k: False, raising=True)

    # Relax backend validation for unit test.
    monkeypatch.setattr(parsing_module.parser_factory, "resolve_backend", lambda *_a, **_k: "basic", raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await yield_control()
        return {
            "resolved_backend": "basic",
            "pdf_quality": None,
            "documents": [
                {"page_content": "Before\n\n![](img/a.png)\n\nAfter\n", "metadata": {"page": 1}},
            ],
        }

    monkeypatch.setattr(parsing_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)

    class _DummyQuery:
        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            return None

    class _DummyDB:
        def query(self, _model):  # noqa: ANN001
            return _DummyQuery()

        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(parsing_module.router, prefix="/api/v1/parsing")
    client = TestClient(app)

    # Default: captions disabled.
    res = client.post(f"/api/v1/parsing/documents/{doc_id}/parse")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "Image caption:" not in (body.get("markdown_content") or "")

    # Enabled: captions should be injected into markdown_content.
    res2 = client.post(f"/api/v1/parsing/documents/{doc_id}/parse", params={"image_caption_enabled": "true"})
    assert res2.status_code == 200, res2.text
    body2 = res2.json()
    assert "Image caption:" in (body2.get("markdown_content") or "")


def test_parsing_workspace_image_ocr_toggle(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.parsing as parsing_module
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    src_path = tmp_path / "demo.md"
    src_path.write_text("dummy", encoding="utf-8")

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = uuid.uuid4()
            self.filename = "demo.md"
            self.file_type = "md"
            self.file_path = str(src_path)
            self.status = "pending"
            self.processing_progress = 0
            self.current_stage = "parsing"
            self.error_message = None
            self.total_characters = 0
            self.chunk_count = 0
            self.doc_metadata = {"workspace": "parsing", "parser_backend_requested": "auto"}

    dummy_doc = _DummyDoc()

    monkeypatch.setattr(parsing_module, "_get_workspace_document", lambda *_a, **_k: dummy_doc, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(parsing_module, "_assert_path_under_tenant_root", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(parsing_module, "is_minio_uri", lambda *_a, **_k: False, raising=True)
    monkeypatch.setattr(parsing_module.parser_factory, "resolve_backend", lambda *_a, **_k: "basic", raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await yield_control()
        return {
            "resolved_backend": "basic",
            "pdf_quality": None,
            "documents": [
                {"page_content": "Before\n\n![chart](img/a.png)\n\nAfter\n", "metadata": {"page": 1}},
            ],
        }

    monkeypatch.setattr(parsing_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)

    class _Audit:
        def to_dict(self):  # noqa: ANN201
            return {"processed": 1}

    def _fake_add_image_ocr_blocks(markdown, *, origin_path, max_images, max_ocr_chars):  # noqa: ANN001, ANN202
        assert origin_path == src_path
        assert max_images >= 1
        assert max_ocr_chars >= 1
        return f"{markdown}\n\nImage OCR: 设备编号 A-001", 1, _Audit()

    monkeypatch.setattr(parsing_module, "add_image_ocr_blocks", _fake_add_image_ocr_blocks, raising=False)

    class _DummyQuery:
        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            return None

    class _DummyDB:
        def query(self, _model):  # noqa: ANN001
            return _DummyQuery()

        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.include_router(parsing_module.router, prefix="/api/v1/parsing")
    client = TestClient(app)

    res = client.post(f"/api/v1/parsing/documents/{doc_id}/parse", params={"image_ocr_enabled": "true"})
    assert res.status_code == 200, res.text
    assert "Image OCR: 设备编号 A-001" in (res.json().get("markdown_content") or "")
    assert dummy_doc.doc_metadata["image_ocr_enabled"] is True
    assert dummy_doc.doc_metadata["image_ocr_added"] == 1


def test_parsing_workspace_vlm_correction_toggle(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.parsing as parsing_module
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    src_path = tmp_path / "demo.pdf"
    src_path.write_bytes(b"%PDF-1.4")

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = uuid.uuid4()
            self.filename = "demo.pdf"
            self.file_type = "pdf"
            self.file_path = str(src_path)
            self.status = "pending"
            self.processing_progress = 0
            self.current_stage = "parsing"
            self.error_message = None
            self.total_characters = 0
            self.chunk_count = 0
            self.doc_metadata = {"workspace": "parsing", "parser_backend_requested": "auto"}

    dummy_doc = _DummyDoc()

    monkeypatch.setattr(parsing_module, "_get_workspace_document", lambda *_a, **_k: dummy_doc, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(parsing_module, "_assert_path_under_tenant_root", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(parsing_module, "is_minio_uri", lambda *_a, **_k: False, raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await yield_control()
        return {
            "resolved_backend": "basic",
            "pdf_quality": {"score": 0.7, "table_quality_score": 0.2, "is_scanned": False, "page_count": 1},
            "documents": [
                {
                    "page_content": "原始表格内容 " * 20,
                    "metadata": {"page": 1},
                },
            ],
        }

    monkeypatch.setattr(parsing_module, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)

    class _Audit:
        def to_dict(self):  # noqa: ANN201
            return {"corrected_pages": 1}

    def _fake_maybe_correct_markdown_pages(pages, *, enabled, api_url, timeout_sec, max_pages, max_chars, pdf_quality, min_table_quality, meta):  # noqa: ANN001, ANN202
        assert enabled is True
        assert pages
        assert meta["document_id"] == str(doc_id)
        return ["矫正后的表格内容"], _Audit()

    monkeypatch.setattr(parsing_module, "maybe_correct_markdown_pages", _fake_maybe_correct_markdown_pages, raising=True)

    class _DummyQuery:
        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            return None

    class _DummyDB:
        def query(self, _model):  # noqa: ANN001
            return _DummyQuery()

        def add(self, _obj) -> None:  # noqa: ANN001
            return None

        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.include_router(parsing_module.router, prefix="/api/v1/parsing")
    client = TestClient(app)

    res = client.post(f"/api/v1/parsing/documents/{doc_id}/parse", params={"vlm_correction_enabled": "true"})
    assert res.status_code == 200, res.text
    assert "矫正后的表格内容" in (res.json().get("markdown_content") or "")
    assert dummy_doc.doc_metadata["vlm_correction_enabled"] is True
