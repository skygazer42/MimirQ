from __future__ import annotations

import io
import json
import operator
import uuid
import zipfile
from datetime import UTC, datetime

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
    from app.api.v1.datasets import export_dataset_bundle_zip

    dataset_id = items[0].dataset_id if items else uuid.uuid4()
    tenant_id = items[0].tenant_id if items else uuid.uuid4()

    class _DummyDataset:
        def __init__(self, did: uuid.UUID) -> None:
            self.id = did
            self.tenant_id = tenant_id
            self.name = "demo"
            self.description = "d"
            self.permission = "all_team_members"
            self.owner_id = "o1"
            self.dataset_metadata = {}
            self.created_at = datetime.now(UTC)
            self.updated_at = datetime.now(UTC)

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
    app.get("/api/v1/datasets/{dataset_id}/export")(export_dataset_bundle_zip)
    client = TestClient(app)
    return client, dataset_id


def _read_zip(res_content: bytes) -> dict[str, bytes]:
    z = zipfile.ZipFile(io.BytesIO(res_content))
    out: dict[str, bytes] = {}
    for name in z.namelist():
        out[name] = z.read(name)
    return out


def _parse_ndjson(raw: bytes) -> list[dict]:  # noqa: ANN001
    text = raw.decode("utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_dataset_export_bundle_zip_includes_expected_files_and_redacts_by_default(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(UTC)

    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="secret.pdf",
        file_type="pdf",
        file_size=1,
        file_path="minio://bucket/x",
        status="completed",
        created_at=now,
        updated_at=now,
        doc_metadata={"pipeline_hash": "ph1"},
    )

    client, dsid = _build_client(monkeypatch=monkeypatch, items=[doc], allow=True)
    res = client.get(f"/api/v1/datasets/{dsid}/export?limit=10")
    assert res.status_code == 200, res.text

    files = _read_zip(res.content)
    assert "dataset.json" in files
    assert "config.json" in files
    assert "documents.ndjson" in files
    assert "artifacts.json" in files

    docs = _parse_ndjson(files["documents.ndjson"])
    assert len(docs) == 1
    assert "filename" not in docs[0]
    assert "file_path" not in docs[0]
    assert docs[0].get("filename_hash")

    artifacts = json.loads(files["artifacts.json"].decode("utf-8"))
    assert isinstance(artifacts.get("documents"), list)
    assert len(artifacts["documents"]) == 1
    storage = (artifacts["documents"][0].get("storage") or {}) if isinstance(artifacts["documents"][0], dict) else {}
    assert "uri" not in storage
    assert storage.get("uri_hash")


def test_dataset_export_bundle_zip_can_include_sensitive(monkeypatch):  # noqa: ANN001
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(UTC)

    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="secret.pdf",
        file_type="pdf",
        file_size=1,
        file_path="minio://bucket/x",
        status="completed",
        created_at=now,
        updated_at=now,
        doc_metadata={"pipeline_hash": "ph1"},
    )

    client, dsid = _build_client(monkeypatch=monkeypatch, items=[doc], allow=True)
    res = client.get(f"/api/v1/datasets/{dsid}/export?limit=10&include_sensitive=true")
    assert res.status_code == 200, res.text

    files = _read_zip(res.content)
    docs = _parse_ndjson(files["documents.ndjson"])
    assert docs[0].get("filename") == "secret.pdf"
    assert docs[0].get("file_path") == "minio://bucket/x"

    artifacts = json.loads(files["artifacts.json"].decode("utf-8"))
    storage = (artifacts["documents"][0].get("storage") or {}) if isinstance(artifacts["documents"][0], dict) else {}
    assert storage.get("uri") == "minio://bucket/x"
