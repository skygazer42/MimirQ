
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas.regression import RagasRegressionCasePatchRequest
from app.api.v1 import evaluations


class _DumpableEvidence:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return dict(self.payload)


class _ReferenceQuery:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def join(self, *_args: object, **_kwargs: object) -> "_ReferenceQuery":
        return self

    def filter(self, *_args: object, **_kwargs: object) -> "_ReferenceQuery":
        return self

    def all(self) -> list[tuple[object, ...]]:
        return self._rows


class _ReferenceDB:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def query(self, *_args: object) -> _ReferenceQuery:
        return _ReferenceQuery(self._rows)


class _SingleRowQuery:
    def __init__(self, row: object) -> None:
        self._row = row

    def filter(self, *_args: object, **_kwargs: object) -> "_SingleRowQuery":
        return self

    def first(self) -> object:
        return self._row


class _PatchDB:
    def __init__(self, row: object) -> None:
        self._row = row
        self.events: list[str] = []

    def query(self, *_args: object) -> _SingleRowQuery:
        return _SingleRowQuery(self._row)

    def add(self, row: object) -> None:
        assert row is self._row
        self.events.append("add")

    def commit(self) -> None:
        self.events.append("commit")

    def refresh(self, row: object) -> None:
        assert row is self._row
        self.events.append("refresh")


class _ImportDB:
    def __init__(self, existing_rows: list[object]) -> None:
        self._existing_rows = existing_rows
        self.added: list[object] = []
        self.events: list[str] = []

    def query(self, *_args: object) -> _ReferenceQuery:
        return _ReferenceQuery(self._existing_rows)  # type: ignore[arg-type]

    def add(self, row: object) -> None:
        self.added.append(row)

    def flush(self) -> None:
        self.events.append("flush")

    def commit(self) -> None:
        self.events.append("commit")


class _SyntheticQuery:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def filter(self, *_args: object, **_kwargs: object) -> "_SyntheticQuery":
        return self

    def order_by(self, *_args: object, **_kwargs: object) -> "_SyntheticQuery":
        return self

    def limit(self, _limit: int) -> "_SyntheticQuery":
        return self

    def count(self) -> int:
        return len(self._rows)

    def all(self) -> list[object]:
        return self._rows


class _SyntheticDB:
    def __init__(self, base_cases: list[object], existing_questions: list[tuple[str]]) -> None:
        self._queries = [base_cases, existing_questions]
        self._query_index = 0

    def query(self, *_args: object) -> _SyntheticQuery:
        rows = self._queries[self._query_index]
        self._query_index += 1
        return _SyntheticQuery(rows)


class _AutoSaveDB:
    def __init__(self, document_rows: list[tuple[object, object]]) -> None:
        self._document_rows = document_rows
        self.added: list[object] = []
        self.events: list[str] = []

    def query(self, *_args: object) -> _SyntheticQuery:
        return _SyntheticQuery(self._document_rows)  # type: ignore[arg-type]

    def add(self, row: object) -> None:
        self.added.append(row)
        self.events.append("add")

    def flush(self) -> None:
        row = self.added[-1]
        if getattr(row, "id", None) is None:
            row.id = uuid4()
        self.events.append("flush")

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


def test_normalize_evidence_chain_keeps_valid_fields_and_caps_items() -> None:
    raw: list[object] = [None, "invalid", {"document_id": "", "chunk_id": "missing"}]
    raw.append(
        _DumpableEvidence(
            {
                "document_id": " doc-1 ",
                "chunk_id": " chunk-1 ",
                "chunk_index": "7",
                "label": "x" * 120,
            }
        )
    )
    raw.append({"document_id": "doc-2", "chunk_id": "chunk-2", "chunk_index": "bad"})
    raw.extend({"document_id": f"doc-{index}", "chunk_id": f"chunk-{index}"} for index in range(3, 30))

    normalized = evaluations._normalize_evidence_chain(raw)

    assert len(normalized) == 20
    assert normalized[0] == {
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "chunk_index": 7,
        "label": "x" * 100,
    }
    assert normalized[1] == {"document_id": "doc-2", "chunk_id": "chunk-2"}


def test_merge_regression_case_extra_preserves_unknown_keys_and_removes_empty_reasoning() -> None:
    merged = evaluations._merge_regression_case_extra(
        base_extra={"keep": True, "reasoning_hops": ["stale"], "evidence_chain": [{"stale": True}]},
        reasoning_hops=["  first hop  ", "", None],
        evidence_chain=[],
    )

    assert merged == {"keep": True, "reasoning_hops": ["first hop"]}


def test_finalize_reference_sources_enforces_acl_and_enriches_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    content = "q" * 2001
    rows = [(chunk_id, document_id, dataset_id, content, None, 4, {"pipeline_hash": " hash "})]
    db = _ReferenceDB(rows)

    monkeypatch.setattr(
        "app.services.document_access.filter_allowed_document_ids",
        lambda _db, _tenant_id, _account_id, document_ids: list(document_ids),
    )

    result = evaluations._finalize_reference_sources(
        db,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        account_id="account-1",
        dataset_id=dataset_id,
        reference_sources=[
            _DumpableEvidence(
                {
                    "document_id": str(document_id),
                    "chunk_id": str(chunk_id),
                }
            )
        ],
    )

    assert result == [
        {
            "document_id": str(document_id),
            "chunk_id": str(chunk_id),
            "chunk_index": 4,
            "pipeline_hash": "hash",
            "quote": f"{'q' * 2000}...",
        }
    ]


def test_finalize_reference_sources_rejects_inaccessible_document(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    db = _ReferenceDB([])

    monkeypatch.setattr(
        "app.services.document_access.filter_allowed_document_ids",
        lambda *_args, **_kwargs: [],
    )

    with pytest.raises(HTTPException) as exc_info:
        evaluations._finalize_reference_sources(
            db,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            account_id="account-1",
            dataset_id=dataset_id,
            reference_sources=[
                {
                    "document_id": str(document_id),
                    "chunk_id": str(chunk_id),
                }
            ],
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Evidence documents not accessible"


def test_patch_regression_case_applies_explicit_scalars_and_preserves_write_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        dataset_id=dataset_id,
        question="before",
        expected_answer="answer",
        tags=["old"],
        extra={"keep": True},
    )
    db = _PatchDB(row)
    request = RagasRegressionCasePatchRequest(
        question="after",
        expected_answer=None,
        tags=[],
    )
    monkeypatch.setattr(evaluations.DatasetService, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(evaluations.DatasetService, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(evaluations.DatasetService, "assert_dataset_writable", lambda *_args: None)

    result = evaluations.patch_ragas_regression_case(
        row.id,
        request,
        tenant_id=tenant_id,
        account_id="account-1",
        db=db,  # type: ignore[arg-type]
    )

    assert result is row
    assert row.question == "after"
    assert row.expected_answer is None
    assert row.tags == []
    assert row.extra == {"keep": True}
    assert db.events == ["add", "commit", "refresh"]


def test_import_regression_cases_creates_updates_and_commits_once(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    existing = SimpleNamespace(
        id=uuid4(),
        question="existing",
        expected_answer="before",
        tags=["old"],
        reference_sources=[],
        extra={"keep": True},
    )
    db = _ImportDB([existing])
    create_item = {
        "question": "new",
        "expected_answer": "new-answer",
        "reference_sources": [{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
        "tags": ["created"],
        "extra": {"new": True},
    }
    update_item = {
        "question": "existing",
        "expected_answer": "after",
        "reference_sources": [{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
        "tags": ["updated"],
        "extra": {"incoming": True},
    }
    payload = SimpleNamespace(
        dataset_id=dataset_id,
        overwrite=True,
        max_items=10,
        items=[create_item, update_item],
    )
    monkeypatch.setattr(evaluations.DatasetService, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(evaluations.DatasetService, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(evaluations.DatasetService, "assert_dataset_writable", lambda *_args: None)
    monkeypatch.setattr(
        evaluations,
        "plan_case_import",
        lambda **_kwargs: {
            "skipped": 0,
            "errors": [],
            "skipped_existing_questions": [],
            "create_items": [create_item],
            "update_items": [update_item],
        },
    )
    monkeypatch.setattr(
        evaluations,
        "_finalize_reference_sources",
        lambda _db, **kwargs: list(kwargs["reference_sources"]),
    )

    result = evaluations.import_ragas_regression_cases(
        payload,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        account_id="account-1",
        db=db,  # type: ignore[arg-type]
    )

    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 0
    assert existing.expected_answer == "after"
    assert existing.tags == ["updated"]
    assert existing.extra == {"keep": True, "incoming": True}
    assert db.events == ["flush", "commit"]


def test_generate_synthetic_hardcases_dry_run_deduplicates_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    chunk_id = uuid4()
    base_case = SimpleNamespace(
        id=uuid4(),
        question="Original question",
        reference_sources=[{"chunk_id": str(chunk_id)}],
        tags=["base"],
        extra={},
    )
    db = _SyntheticDB([base_case], [("Existing Question",)])
    payload = SimpleNamespace(
        dataset_id=dataset_id,
        dry_run=True,
        case_ids=[],
        max_cases=50,
        hardcases_per_case=4,
        max_created=500,
        tag="synthetic_hardcase",
    )
    monkeypatch.setattr(evaluations.settings, "KG_ENABLED", True)
    monkeypatch.setattr(evaluations.DatasetService, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(evaluations.DatasetService, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(evaluations.DatasetService, "assert_dataset_readable", lambda *_args: None)
    monkeypatch.setattr(
        "app.rag.evaluation.kg_search_diagnostics._resolve_ground_truth_event_ids",
        lambda *_args, **_kwargs: ["event-1"],
    )
    monkeypatch.setattr(
        "app.rag.evaluation.kg_search_diagnostics._deterministic_hardcase_candidates",
        lambda *_args, **_kwargs: ([], [], []),
    )
    monkeypatch.setattr(
        "app.rag.evaluation.kg_hardcase_deterministic.generate_hardcases_deterministic",
        lambda **_kwargs: [
            SimpleNamespace(question=" Existing   Question ", kind="alias", rationale=None),
            SimpleNamespace(question="Novel question", kind="skill", rationale="because"),
        ],
    )

    result = evaluations.generate_synthetic_hardcases(
        payload,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        account_id="account-1",
        db=db,  # type: ignore[arg-type]
    )

    assert result.base_cases_total == 1
    assert result.base_cases_evaluated == 1
    assert result.hardcases_generated == 2
    assert result.created == 0
    assert result.skipped_duplicates == 1
    assert result.created_case_ids == []
    assert result.errors == []


def test_generate_test_cases_from_documents_auto_saves_grounded_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    db = _AutoSaveDB([(document_id, dataset_id)])
    question = SimpleNamespace(
        question="What is grounded?",
        expected_answer="This answer.",
        context="Context",
        metadata={"source_id": str(document_id), "reference_chunk_ids": [str(chunk_id)]},
    )
    request = SimpleNamespace(
        dataset_id=dataset_id,
        document_ids=[document_id],
        num_questions=1,
        question_types=["factual"],
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        auto_save_as_cases=True,
    )
    monkeypatch.setattr(evaluations.DatasetService, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(evaluations.DatasetService, "get_dataset", lambda *_args: object())
    monkeypatch.setattr(evaluations.DatasetService, "assert_dataset_writable", lambda *_args: None)
    monkeypatch.setattr(evaluations, "generate_questions_from_documents", lambda **_kwargs: [question])
    monkeypatch.setattr(
        evaluations,
        "_finalize_reference_sources",
        lambda _db, **kwargs: list(kwargs["reference_sources"]),
    )

    result = evaluations.generate_test_cases_from_documents(
        request,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        account_id="account-1",
        db=db,  # type: ignore[arg-type]
    )

    assert result.status == "completed"
    assert len(result.generated_questions) == 1
    assert len(result.saved_case_ids) == 1
    assert question.metadata["auto_save"] == {
        "saved": True,
        "case_id": str(result.saved_case_ids[0]),
    }
    assert db.events == ["add", "flush", "commit"]
