
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


def test_parsing_workspace_returns_quality_gate_and_fallback(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.parsing as parsing_module
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%dummy\n")

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = uuid.uuid4()
            self.filename = "demo.pdf"
            self.file_type = "pdf"
            self.file_path = str(pdf_path)
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
    monkeypatch.setattr(parsing_module, "is_object_storage_uri", lambda *_a, **_k: False, raising=True)

    # Relax backend validation for unit test.
    monkeypatch.setattr(parsing_module.parser_factory, "resolve_backend", lambda *_a, **_k: "basic", raising=True)

    async def _fake_run_subprocess_worker(*, tenant_id, payload, disconnect_check, timeout_sec):  # noqa: ANN001, ANN202
        await yield_control()
        backend = str(payload.get("parser_backend") or "")
        if backend == "auto":
            # Simulate low-quality parse that should trigger fallback.
            return {
                "resolved_backend": "docling",
                "pdf_quality": {
                    "score": 0.9,
                    "text_quality_score": 0.9,
                    "format_consistency_score": 0.9,
                    "table_quality_score": 0.9,
                    "is_scanned": False,
                    "page_count": 2.0,
                },
                "documents": [{"page_content": "\ufffd" * 80, "metadata": {"page": 1}}],
            }

        # Fallback backend produces good text.
        return {
            "resolved_backend": "basic",
            "pdf_quality": {
                "score": 0.9,
                "text_quality_score": 0.9,
                "format_consistency_score": 0.9,
                "table_quality_score": 0.9,
                "is_scanned": False,
                "page_count": 2.0,
            },
            "documents": [{"page_content": "Hello world\n" * 50, "metadata": {"page": 1}}],
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

    res = client.post(f"/api/v1/parsing/documents/{doc_id}/parse")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body.get("quality_gate")
    assert body["quality_gate"]["grade"] in {"pass", "warn", "fail"}
    assert body["quality_gate"]["evidence"]["parse_quality_gate"]["schema"] == "mimirq.parse_quality_gate.v1"
    assert body["parser_backend"] == "basic"
    assert isinstance(body.get("elements"), list)
    assert body["elements"][0]["kind"] == "paragraph"
    assert body["elements"][0]["page"] == 1
