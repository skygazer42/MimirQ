
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


def test_parsing_extract_endpoint_returns_json_with_evidence(monkeypatch):  # noqa: ANN001
    import app.api.v1.parsing as parsing_module
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = document_id
            self.tenant_id = tenant_id
            self.dataset_id = uuid.uuid4()
            self.filename = "contract.pdf"
            self.file_type = "pdf"
            self.file_path = "/tmp/contract.pdf"
            self.status = "completed"
            self.processing_progress = 100
            self.current_stage = "completed"
            self.error_message = None
            self.total_characters = 100
            self.chunk_count = 1
            self.doc_metadata = {
                "workspace": "parsing",
                "elements": [
                    {
                        "id": "seal:2:0",
                        "kind": "seal",
                        "page": 2,
                        "pages": [2],
                        "text": "印章识别：杭州测试科技有限公司",
                        "confidence": 0.97,
                        "bbox": {"x0": 10, "y0": 20, "x1": 60, "y1": 70},
                        "attributes": {
                            "seal_text": "杭州测试科技有限公司",
                            "seal_primary": {"text": "杭州测试科技有限公司"},
                            "visual_kind": "stamp",
                        },
                    }
                ],
            }

    class _DummyRow:
        markdown_content = "合同正文"
        original_markdown_content = "合同正文"

    dummy_doc = _DummyDoc()

    monkeypatch.setattr(parsing_module, "_get_workspace_document", lambda *_a, **_k: dummy_doc, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    class _DummyQuery:
        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            return _DummyRow()

    class _DummyDB:
        def query(self, _model):  # noqa: ANN001
            return _DummyQuery()

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.include_router(parsing_module.router, prefix="/api/v1/parsing")
    client = TestClient(app)

    res = client.post(
        f"/api/v1/parsing/documents/{document_id}/extract",
        json={
            "mode": "schema",
            "schema": {
                "company_name": {
                    "type": "string",
                    "source_kind": "seal",
                }
            },
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["document_id"] == str(document_id)
    assert body["mode"] == "schema"
    assert body["result"]["company_name"]["value"] == "杭州测试科技有限公司"
    assert body["result"]["company_name"]["evidence"][0]["page"] == 2
    assert body["result"]["company_name"]["evidence"][0]["pages"] == [2]
    assert body["result"]["company_name"]["evidence"][0]["visual_kind"] == "stamp"
