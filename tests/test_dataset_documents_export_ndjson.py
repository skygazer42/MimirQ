from __future__ import annotations

import gzip
import json
import operator
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.document import Document


class _FakeQuery:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def filter(self, *conds, **_kwargs):  # noqa: ANN001,D401
        try:
            from sqlalchemy.sql import operators as sql_ops
            from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList
            from sqlalchemy.sql.operators import in_op
        except Exception:  # pragma: no cover
            return self

        def _cmp_value(v):  # noqa: ANN001
            if isinstance(v, uuid.UUID):
                return v.int
            return v

        def _matches(item, expr) -> bool:  # noqa: ANN001
            if isinstance(expr, BooleanClauseList):
                if expr.operator is sql_ops.and_:
                    return all(_matches(item, c) for c in expr.clauses)
                if expr.operator is sql_ops.or_:
                    return any(_matches(item, c) for c in expr.clauses)
                return True

            if not isinstance(expr, BinaryExpression):
                return True

            left_key = getattr(getattr(expr, "left", None), "key", None)
            if not left_key:
                return True
            left_val = getattr(item, str(left_key), None)
            right_val = getattr(getattr(expr, "right", None), "value", None)

            op = getattr(expr, "operator", None)
            if op is operator.eq:
                return _cmp_value(left_val) == _cmp_value(right_val)
            if op is operator.ne:
                return _cmp_value(left_val) != _cmp_value(right_val)
            if op is operator.gt:
                return _cmp_value(left_val) > _cmp_value(right_val)
            if op is operator.ge:
                return _cmp_value(left_val) >= _cmp_value(right_val)
            if op is operator.lt:
                return _cmp_value(left_val) < _cmp_value(right_val)
            if op is operator.le:
                return _cmp_value(left_val) <= _cmp_value(right_val)
            if op is in_op:
                if not isinstance(right_val, (list, tuple, set, frozenset)):
                    return False
                return _cmp_value(left_val) in {_cmp_value(v) for v in right_val}
            return True

        items = [it for it in self._items if all(_matches(it, c) for c in conds)]
        self._items = items
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN001,D401
        return self

    def limit(self, n: int):  # noqa: D401
        self._items = self._items[: int(n or 0)]
        return self

    def all(self):  # noqa: D401
        return list(self._items)


class _FakeDB:
    def __init__(self, items):  # noqa: ANN001
        self._items = list(items or [])

    def query(self, _model):  # noqa: ANN001
        return _FakeQuery(self._items)


def _build_client(*, monkeypatch, items, allow: bool):  # noqa: ANN001
    import app.api.v1.datasets as datasets_module
    from app.api.v1.datasets import export_dataset_documents_ndjson

    dataset_id = items[0].dataset_id if items else uuid.uuid4()
    tenant_id = items[0].tenant_id if items else uuid.uuid4()

    class _DummyDataset:
        def __init__(self, did: uuid.UUID) -> None:
            self.id = did
            self.name = "demo"

    monkeypatch.setattr(
        datasets_module.DatasetService,
        "get_dataset",
        lambda *_a, **_k: _DummyDataset(dataset_id),
        raising=True,
    )

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    def _override_get_db():  # noqa: ANN202
        yield _FakeDB(items)

    if allow:
        monkeypatch.setattr(datasets_module, "ensure_tenant_permission", lambda *_a, **_k: None, raising=True)
    else:
        from fastapi import HTTPException

        monkeypatch.setattr(
            datasets_module,
            "ensure_tenant_permission",
            lambda *_a, **_k: (_ for _ in ()).throw(HTTPException(status_code=403, detail="No permission")),
            raising=True,
        )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/datasets/{dataset_id}/documents/export")(export_dataset_documents_ndjson)
    client = TestClient(app)
    return client


def _parse_ndjson(text: str) -> list[dict]:  # noqa: ANN001
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_dataset_documents_export_ndjson_sanitizes_sensitive_fields_by_default(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="secret.pdf",
        file_type="pdf",
        file_size=123,
        file_path="minio://bucket/tenant/dataset/doc.pdf",
        status="completed",
        created_at=now,
        updated_at=now,
        doc_metadata={"pipeline_hash": "ph1"},
    )

    client = _build_client(monkeypatch=monkeypatch, items=[doc], allow=True)

    res = client.get(f"/api/v1/datasets/{dataset_id}/documents/export?limit=10")
    assert res.status_code == 200, res.text
    body = _parse_ndjson(res.text)
    assert len(body) == 1
    assert body[0].get("id") == str(doc.id)
    assert "filename" not in body[0]
    assert "file_path" not in body[0]
    assert body[0].get("filename_hash")
    assert body[0].get("file_path_hash")


def test_dataset_documents_export_ndjson_can_include_sensitive_fields(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="secret.pdf",
        file_type="pdf",
        file_size=123,
        file_path="minio://bucket/tenant/dataset/doc.pdf",
        status="completed",
        created_at=now,
        updated_at=now,
        doc_metadata={"pipeline_hash": "ph1"},
    )

    client = _build_client(monkeypatch=monkeypatch, items=[doc], allow=True)

    res = client.get(f"/api/v1/datasets/{dataset_id}/documents/export?limit=10&include_sensitive=true")
    assert res.status_code == 200, res.text
    body = _parse_ndjson(res.text)
    assert len(body) == 1
    assert body[0].get("filename") == "secret.pdf"
    assert body[0].get("file_path") == "minio://bucket/tenant/dataset/doc.pdf"


def test_dataset_documents_export_ndjson_supports_cursor(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    t0 = datetime.now(timezone.utc)
    t1 = t0 + timedelta(seconds=1)
    t2 = t0 + timedelta(seconds=2)

    docs = [
        Document(
            id=uuid.UUID(int=1),
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="a",
            file_type="txt",
            file_size=1,
            file_path="p1",
            status="completed",
            created_at=t0,
            updated_at=t0,
            doc_metadata={},
        ),
        Document(
            id=uuid.UUID(int=2),
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="b",
            file_type="txt",
            file_size=1,
            file_path="p2",
            status="completed",
            created_at=t1,
            updated_at=t1,
            doc_metadata={},
        ),
        Document(
            id=uuid.UUID(int=3),
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="c",
            file_type="txt",
            file_size=1,
            file_path="p3",
            status="completed",
            created_at=t2,
            updated_at=t2,
            doc_metadata={},
        ),
    ]

    client = _build_client(monkeypatch=monkeypatch, items=docs, allow=True)

    res0 = client.get(f"/api/v1/datasets/{dataset_id}/documents/export?limit=2")
    assert res0.status_code == 200, res0.text
    got0 = _parse_ndjson(res0.text)
    assert [r.get("id") for r in got0] == [str(uuid.UUID(int=1)), str(uuid.UUID(int=2))]

    after_created_at = got0[-1]["created_at"]
    after_id = got0[-1]["id"]
    res1 = client.get(
        f"/api/v1/datasets/{dataset_id}/documents/export?limit=10&after_created_at={after_created_at}&after_id={after_id}"
    )
    assert res1.status_code == 200, res1.text
    got1 = _parse_ndjson(res1.text)
    assert [r.get("id") for r in got1] == [str(uuid.UUID(int=3))]


def test_dataset_documents_export_ndjson_denies_without_lifecycle_permission(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="a",
        file_type="txt",
        file_size=1,
        file_path="p",
        status="completed",
        created_at=now,
        updated_at=now,
        doc_metadata={},
    )
    client = _build_client(monkeypatch=monkeypatch, items=[doc], allow=False)

    res = client.get(f"/api/v1/datasets/{dataset_id}/documents/export?limit=10")
    assert res.status_code == 403, res.text


def test_dataset_documents_export_ndjson_supports_gzip(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="a",
        file_type="txt",
        file_size=1,
        file_path="p",
        status="completed",
        created_at=now,
        updated_at=now,
        doc_metadata={},
    )
    client = _build_client(monkeypatch=monkeypatch, items=[doc], allow=True)

    res = client.get(f"/api/v1/datasets/{dataset_id}/documents/export?limit=10&gzip=true")
    assert res.status_code == 200, res.text
    assert str(res.headers.get("content-encoding") or "").lower() == "gzip"

    raw = res.content
    try:
        text = raw.decode("utf-8")
        if not text.lstrip().startswith("{"):
            text = gzip.decompress(raw).decode("utf-8")
    except UnicodeDecodeError:
        text = gzip.decompress(raw).decode("utf-8")

    got = _parse_ndjson(text)
    assert [r.get("id") for r in got] == [str(doc.id)]


def test_dataset_documents_export_ndjson_includes_source_and_lifecycle_fields_redacted(monkeypatch):  # noqa: ANN001
    from app.rag.core.hashing import stable_hash

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)
    supersedes = uuid.uuid4()
    source_url = "https://example.com/private/doc.txt"

    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="secret.txt",
        file_type="txt",
        file_size=123,
        file_path="minio://bucket/tenant/dataset/doc.txt",
        status="completed",
        created_at=now,
        updated_at=now,
        lifecycle_owner="user-123",
        review_due_at=now,
        authority_level=7,
        supersedes_document_id=supersedes,
        doc_metadata={
            "pipeline_hash": "ph1",
            "file_sha256": "ABC123",
            "source_url": source_url,
            "source_last_modified_at": "2026-03-01T00:00:00Z",
            "source_last_modified_source": "http:last-modified",
            "source_fetched_at": "2026-03-02T00:00:00Z",
            "source_etag": "etag-1",
        },
    )

    client = _build_client(monkeypatch=monkeypatch, items=[doc], allow=True)

    res = client.get(f"/api/v1/datasets/{dataset_id}/documents/export?limit=10")
    assert res.status_code == 200, res.text
    body = _parse_ndjson(res.text)
    assert len(body) == 1
    row = body[0]

    assert row.get("file_sha256") == "abc123"
    assert row.get("source_last_modified_at") == "2026-03-01T00:00:00Z"
    assert row.get("source_last_modified_source") == "http:last-modified"
    assert row.get("source_fetched_at") == "2026-03-02T00:00:00Z"
    assert row.get("source_etag") == "etag-1"
    assert row.get("source_url_hash") == stable_hash(source_url, length=16)

    assert row.get("lifecycle_owner_hash") == stable_hash("user-123", length=16)
    assert "lifecycle_owner" not in row
    assert row.get("review_due_at") and str(row.get("review_due_at")).endswith("Z")
    assert row.get("authority_level") == 7
    assert row.get("supersedes_document_id") == str(supersedes)


def test_dataset_documents_export_json_format_returns_items_and_cursor(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    t0 = datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=1)
    t2 = t0 + timedelta(seconds=2)

    docs = [
        Document(
            id=uuid.UUID(int=1),
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="a",
            file_type="txt",
            file_size=1,
            file_path="p1",
            status="completed",
            created_at=t0,
            updated_at=t0,
            doc_metadata={},
        ),
        Document(
            id=uuid.UUID(int=2),
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="b",
            file_type="txt",
            file_size=1,
            file_path="p2",
            status="completed",
            created_at=t1,
            updated_at=t1,
            doc_metadata={},
        ),
        Document(
            id=uuid.UUID(int=3),
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="c",
            file_type="txt",
            file_size=1,
            file_path="p3",
            status="completed",
            created_at=t2,
            updated_at=t2,
            doc_metadata={},
        ),
    ]

    client = _build_client(monkeypatch=monkeypatch, items=docs, allow=True)

    res0 = client.get(f"/api/v1/datasets/{dataset_id}/documents/export?limit=2&export_format=json")
    assert res0.status_code == 200, res0.text
    page0 = res0.json()
    assert page0.get("returned") == 2
    assert [r.get("id") for r in (page0.get("items") or [])] == [str(uuid.UUID(int=1)), str(uuid.UUID(int=2))]

    cur = page0.get("next_cursor") or {}
    after_created_at = cur.get("after_created_at")
    after_id = cur.get("after_id")
    assert after_created_at and after_id

    res1 = client.get(
        f"/api/v1/datasets/{dataset_id}/documents/export?limit=10&export_format=json&after_created_at={after_created_at}&after_id={after_id}"
    )
    assert res1.status_code == 200, res1.text
    page1 = res1.json()
    assert [r.get("id") for r in (page1.get("items") or [])] == [str(uuid.UUID(int=3))]
