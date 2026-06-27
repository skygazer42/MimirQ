from __future__ import annotations

import asyncio
import importlib
from uuid import UUID, uuid4

import pytest


def _import_bundle_module():
    try:
        return importlib.import_module("app.services.regression_case_bundle")
    except ModuleNotFoundError:
        pytest.fail("Missing module: app.services.regression_case_bundle", pytrace=False)

def _import_schema_import_request():
    try:
        from app.api.schemas.regression import RagasRegressionCaseImportRequest  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"Missing schema: RagasRegressionCaseImportRequest ({exc})", pytrace=False)
    return RagasRegressionCaseImportRequest


def test_import_endpoint_is_registered():
    # Keep this test lightweight: do not import FastAPI modules that pull heavy ML deps.
    from pathlib import Path

    text = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")
    assert '"/ragas/regression/cases/import"' in text
    assert "response_model=RagasRegressionCaseImportResponse" in text


def test_import_schema_requires_dataset_id_and_items_and_evidence():
    import_req = _import_schema_import_request()

    with pytest.raises(Exception):
        import_req(items=[])

    with pytest.raises(Exception):
        import_req(dataset_id=uuid4(), items=[])

    with pytest.raises(Exception):
        import_req(
            dataset_id=uuid4(),
            items=[{"question": "q", "reference_sources": []}],
        )


def test_plan_case_import_counts_created_updated_skipped_and_errors():
    mod = _import_bundle_module()
    assert hasattr(mod, "plan_case_import"), "plan_case_import helper must exist"

    dataset_id = uuid4()
    existing_questions = {"exists"}

    items = [
        {"question": "  new  "},
        {"question": "exists"},
        {"question": "exists"},  # duplicate in same import batch
        {"question": "   "},  # invalid
    ]

    out = mod.plan_case_import(
        dataset_id=dataset_id,
        existing_questions=existing_questions,
        items=items,
        overwrite=False,
        max_items=100,
    )

    assert out["created"] == 1
    assert out["updated"] == 0
    assert out["skipped"] >= 1
    assert isinstance(out["errors"], list)
    assert out["errors"], "expected validation errors for duplicates/empty questions"

    out_overwrite = mod.plan_case_import(
        dataset_id=dataset_id,
        existing_questions=existing_questions,
        items=items,
        overwrite=True,
        max_items=100,
    )
    assert out_overwrite["created"] == 1
    assert out_overwrite["updated"] == 1


def test_plan_case_import_preserves_plugin_extra_metadata():
    mod = _import_bundle_module()
    import_req = _import_schema_import_request()

    dataset_id = uuid4()
    item = import_req(
        dataset_id=dataset_id,
        items=[
            {
                "question": "测试事项需要什么材料？",
                "reference_sources": [{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
                "extra": {
                    "source": "plugin_golden_draft",
                    "plugin_id": "demo-runtime-plugin",
                    "expected_metadata": {"source_record_id": "record-1"},
                },
            }
        ],
    ).items[0]

    out = mod.plan_case_import(
        dataset_id=dataset_id,
        existing_questions=set(),
        items=[item],
        overwrite=False,
        max_items=100,
    )

    assert out["created"] == 1
    assert out["create_items"][0]["extra"]["expected_metadata"] == {"source_record_id": "record-1"}


def test_plan_case_import_rejects_review_only_local_sample_items():
    mod = _import_bundle_module()
    import_req = _import_schema_import_request()

    dataset_id = uuid4()
    item = import_req(
        dataset_id=dataset_id,
        items=[
            {
                "question": "本地样例问题？",
                "reference_sources": [{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
                "extra": {
                    "source": "plugin_golden_draft",
                    "review_only": True,
                    "reference_source_mode": "local_sample_synthetic",
                    "expected_metadata": {"source_record_id": "record-1"},
                },
            }
        ],
    ).items[0]

    out = mod.plan_case_import(
        dataset_id=dataset_id,
        existing_questions=set(),
        items=[item],
        overwrite=False,
        max_items=100,
    )

    assert out["created"] == 0
    assert out["skipped"] == 1
    assert out["create_items"] == []
    assert "review_only" in out["errors"][0]["error"]


def test_import_regression_cases_returns_created_updated_and_all_case_ids(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1 import evaluations as eval_api
    from app.models.evaluation import RagasRegressionCase

    import_req = _import_schema_import_request()

    tenant_id = uuid4()
    dataset_id = uuid4()
    existing_id = uuid4()
    created_doc_id = uuid4()
    created_chunk_id = uuid4()
    updated_doc_id = uuid4()
    updated_chunk_id = uuid4()

    existing = RagasRegressionCase(
        id=existing_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        question="exists",
        reference_sources=[{"document_id": str(updated_doc_id), "chunk_id": str(updated_chunk_id)}],
    )

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeDb:
        def __init__(self):
            self.added = []
            self.flushed = False
            self.committed = False

        def query(self, *_args, **_kwargs):
            return _FakeQuery([existing])

        def add(self, row):
            self.added.append(row)

        def flush(self):
            self.flushed = True

        def commit(self):
            self.committed = True

    fake_db = _FakeDb()

    monkeypatch.setattr(eval_api.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(eval_api.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(eval_api.DatasetService, "assert_dataset_writable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        eval_api,
        "_finalize_reference_sources",
        lambda _db, **kwargs: [dict(x) for x in kwargs.get("reference_sources") or []],
        raising=True,
    )

    result = asyncio.run(
        eval_api.import_ragas_regression_cases(
            import_req(
                dataset_id=dataset_id,
                overwrite=True,
                items=[
                    {
                        "question": "new",
                        "reference_sources": [{"document_id": str(created_doc_id), "chunk_id": str(created_chunk_id)}],
                    },
                    {
                        "question": "exists",
                        "reference_sources": [{"document_id": str(updated_doc_id), "chunk_id": str(updated_chunk_id)}],
                    },
                ],
            ),
            tenant_id=tenant_id,
            account_id="tester",
            db=fake_db,
        )
    )

    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["updated_case_ids"] == [existing_id]
    assert len(result["created_case_ids"]) == 1
    assert UUID(str(result["created_case_ids"][0]))
    assert result["case_ids"] == [result["created_case_ids"][0], existing_id]
    assert fake_db.flushed is True
    assert fake_db.committed is True


def test_import_regression_cases_returns_skipped_existing_case_ids(monkeypatch: pytest.MonkeyPatch):
    from app.api.v1 import evaluations as eval_api
    from app.models.evaluation import RagasRegressionCase

    import_req = _import_schema_import_request()

    tenant_id = uuid4()
    dataset_id = uuid4()
    existing_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    existing = RagasRegressionCase(
        id=existing_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        question="exists",
        reference_sources=[],
    )

    class _FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return list(self._rows)

    class _FakeDb:
        def __init__(self):
            self.flushed = False
            self.committed = False

        def query(self, *_args, **_kwargs):
            return _FakeQuery([existing])

        def add(self, _row):
            raise AssertionError("no rows should be added when existing case is skipped")

        def flush(self):
            self.flushed = True

        def commit(self):
            self.committed = True

    fake_db = _FakeDb()

    monkeypatch.setattr(eval_api.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(eval_api.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(eval_api.DatasetService, "assert_dataset_writable", lambda *_args, **_kwargs: None, raising=True)

    result = asyncio.run(
        eval_api.import_ragas_regression_cases(
            import_req(
                dataset_id=dataset_id,
                overwrite=False,
                items=[
                    {
                        "question": "exists",
                        "reference_sources": [{"document_id": str(document_id), "chunk_id": str(chunk_id)}],
                    }
                ],
            ),
            tenant_id=tenant_id,
            account_id="tester",
            db=fake_db,
        )
    )

    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["skipped"] == 1
    assert result["skipped_case_ids"] == [existing_id]
    assert result["case_ids"] == [existing_id]
    assert fake_db.flushed is True
    assert fake_db.committed is True
