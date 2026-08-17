import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from scripts import run_nightly_ablations as nightly

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")
DATASET_ID = UUID("22222222-2222-2222-2222-222222222222")
OWNER_ID = UUID("33333333-3333-3333-3333-333333333333")


class _DatasetQuery:
    def __init__(self, dataset: object) -> None:
        self._dataset = dataset

    def filter(self, *conditions: object) -> "_DatasetQuery":
        return self

    def first(self) -> object:
        return self._dataset


class _DatasetIdQuery:
    def __init__(self, dataset_ids: list[UUID]) -> None:
        self._dataset_ids = dataset_ids
        self.limit_value: int | None = None

    def filter(self, *conditions: object) -> "_DatasetIdQuery":
        return self

    def order_by(self, *columns: object) -> "_DatasetIdQuery":
        return self

    def limit(self, value: int) -> "_DatasetIdQuery":
        self.limit_value = value
        return self

    def all(self) -> list[tuple[UUID]]:
        return [(dataset_id,) for dataset_id in self._dataset_ids[: self.limit_value]]


class _CaseQuery:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def filter(self, *conditions: object) -> "_CaseQuery":
        return self

    def all(self) -> list[object]:
        return self._rows


class _Session:
    def __init__(
        self,
        dataset: object,
        *,
        dataset_ids: list[UUID] | None = None,
        case_rows: list[object] | None = None,
    ) -> None:
        self._dataset = dataset
        self._dataset_ids = dataset_ids or []
        self._case_rows = case_rows or []
        self.added: list[object] = []
        self.commit_count = 0
        self.closed = False

    def query(self, model: object) -> object:
        if getattr(model, "key", "") == "id":
            return _DatasetIdQuery(self._dataset_ids)
        if getattr(model, "__name__", "") == "RagasRegressionCase":
            return _CaseQuery(self._case_rows)
        return _DatasetQuery(self._dataset)

    def add(self, value: object) -> None:
        self.added.append(value)

    def commit(self) -> None:
        self.commit_count += 1

    def refresh(self, value: object) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def _patch_runtime(monkeypatch, session_or_factory: object, *, run_model: object, evaluator: object) -> None:
    from app.core import config, database
    from app.models import evaluation
    from app.rag.evaluation import ragas

    monkeypatch.setattr(config.settings, "DEFAULT_TENANT_ID", str(TENANT_ID))
    monkeypatch.setattr(config.settings, "RERANKER_TOP_N", 20)
    session_factory = session_or_factory if callable(session_or_factory) else lambda: session_or_factory
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr(evaluation, "RagasRegressionRun", run_model)
    monkeypatch.setattr(ragas, "run_regression_ragas_evaluation", evaluator)


def test_main_dry_run_plans_each_default_ablation(monkeypatch, capsys) -> None:
    session = _Session(SimpleNamespace(owner_id=OWNER_ID))
    _patch_runtime(monkeypatch, session, run_model=object, evaluator=lambda **kwargs: None)

    result = nightly.main(["--dataset-id", str(DATASET_ID), "--dry-run"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["executed"] == []
    assert [item["ablation_key"] for item in payload["planned"]] == [
        "baseline",
        "topk50",
        "keyword_only",
        "vector_only",
        "profile_recall50",
        "fusion_linear",
        "sparse_budgeted_rrf",
        "sparse_bounded_slice",
        "hybrid_rerank",
    ]
    assert {item["dataset_id"] for item in payload["planned"]} == {str(DATASET_ID)}
    assert {item["account_id"] for item in payload["planned"]} == {str(OWNER_ID)}
    assert session.added == []
    assert session.closed is True


def test_main_execute_persists_and_evaluates_each_ablation(monkeypatch, capsys) -> None:
    created_runs: list[object] = []
    evaluation_calls: list[dict[str, object]] = []

    class _Run:
        def __init__(self, **values: object) -> None:
            self.id = uuid4()
            self.values = values
            created_runs.append(self)

    session = _Session(SimpleNamespace(owner_id=OWNER_ID))
    _patch_runtime(
        monkeypatch,
        session,
        run_model=_Run,
        evaluator=lambda **kwargs: evaluation_calls.append(kwargs),
    )

    result = nightly.main(["--dataset-id", str(DATASET_ID), "--execute", "--metrics", "recall, precision"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["dry_run"] is False
    assert payload["planned"] == []
    assert len(created_runs) == len(session.added) == len(evaluation_calls) == len(payload["executed"]) == 9
    assert session.commit_count == 9
    assert all(run.values["params"]["nightly"] is True for run in created_runs)
    assert all(run.values["metrics"] == ["recall", "precision"] for run in created_runs)
    assert all(call["dataset_id"] == DATASET_ID for call in evaluation_calls)
    assert all(call["account_id"] == str(OWNER_ID) for call in evaluation_calls)
    assert session.closed is True


def test_main_rejects_cases_bundle_for_another_dataset(monkeypatch, tmp_path, capsys) -> None:
    cases_path = tmp_path / "cases.json"
    foreign_dataset_id = uuid4()
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": str(foreign_dataset_id),
                "items": [{"question": "Which dataset?"}],
            }
        ),
        encoding="utf-8",
    )

    result = nightly.main(
        [
            "--dataset-id",
            str(DATASET_ID),
            "--cases",
            str(cases_path),
            "--dry-run",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload == {
        "ok": False,
        "error": "cases dataset_id mismatch",
        "expected": str(DATASET_ID),
        "got": str(foreign_dataset_id),
    }


def test_main_all_datasets_uses_bounded_catalog_and_closes_every_session(monkeypatch, capsys) -> None:
    second_dataset_id = UUID("44444444-4444-4444-4444-444444444444")
    catalog_session = _Session(None, dataset_ids=[DATASET_ID, second_dataset_id])
    first_session = _Session(SimpleNamespace(owner_id=OWNER_ID))
    second_session = _Session(SimpleNamespace(owner_id=OWNER_ID))
    sessions = iter([catalog_session, first_session, second_session])
    _patch_runtime(monkeypatch, sessions.__next__, run_model=object, evaluator=lambda **kwargs: None)

    result = nightly.main(["--all-datasets", "--max-datasets", "2", "--dry-run"])

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert len(payload["planned"]) == 18
    assert {item["dataset_id"] for item in payload["planned"]} == {
        str(DATASET_ID),
        str(second_dataset_id),
    }
    assert payload["executed"] == []
    assert catalog_session.closed is True
    assert first_session.closed is True
    assert second_session.closed is True


def test_main_cases_truncation_warns_before_final_payload(monkeypatch, tmp_path, capsys) -> None:
    questions = ["Question one", "Question two", "Question three"]
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": str(DATASET_ID),
                "items": [{"question": question} for question in questions],
            }
        ),
        encoding="utf-8",
    )
    rows = [SimpleNamespace(id=uuid4(), question=question) for question in questions]
    session = _Session(SimpleNamespace(owner_id=OWNER_ID), case_rows=rows)
    _patch_runtime(monkeypatch, session, run_model=object, evaluator=lambda **kwargs: None)

    result = nightly.main(
        ["--dataset-id", str(DATASET_ID), "--cases", str(cases_path), "--max-cases", "2", "--dry-run"]
    )

    output_lines = capsys.readouterr().out.splitlines()
    warning, payload = [json.loads(line) for line in output_lines]
    assert result == 0
    assert warning == {
        "warn": "cases bundle truncated by --max-cases",
        "dataset_id": str(DATASET_ID),
        "cases_total": 3,
        "cases_used": 2,
        "cases_file": "cases.json",
    }
    assert payload["ok"] is True
    assert {item["cases_count"] for item in payload["planned"]} == {2}
    assert session.closed is True


def test_main_rejects_cases_with_all_datasets_without_opening_session(monkeypatch, tmp_path, capsys) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text("{}", encoding="utf-8")

    def fail_if_opened() -> None:
        raise AssertionError("database session must not open")

    _patch_runtime(monkeypatch, fail_if_opened, run_model=object, evaluator=lambda **kwargs: None)

    result = nightly.main(["--all-datasets", "--cases", str(cases_path), "--dry-run"])

    assert result == 2
    assert json.loads(capsys.readouterr().out) == {
        "ok": False,
        "error": "--cases is only supported with --dataset-id",
    }


def test_main_missing_dataset_skips_without_cases_but_fails_with_cases(monkeypatch, tmp_path, capsys) -> None:
    sessions: list[_Session] = []

    def new_missing_session() -> _Session:
        session = _Session(None)
        sessions.append(session)
        return session

    _patch_runtime(monkeypatch, new_missing_session, run_model=object, evaluator=lambda **kwargs: None)

    result = nightly.main(["--dataset-id", str(DATASET_ID), "--dry-run"])
    skipped_payload = json.loads(capsys.readouterr().out)

    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps({"dataset_id": str(DATASET_ID), "items": [{"question": "Question"}]}),
        encoding="utf-8",
    )
    failed_result = nightly.main(["--dataset-id", str(DATASET_ID), "--cases", str(cases_path), "--dry-run"])
    error_payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert skipped_payload["planned"] == [
        {"dataset_id": str(DATASET_ID), "skipped": True, "reason": "dataset_not_found"}
    ]
    assert failed_result == 2
    assert error_payload == {"ok": False, "error": "dataset_not_found", "dataset_id": str(DATASET_ID)}
    assert all(session.closed for session in sessions)


def test_main_propagates_evaluator_failure_after_committing_run(monkeypatch) -> None:
    class _Run:
        def __init__(self, **values: object) -> None:
            self.id = uuid4()

    def fail_evaluation(**kwargs: object) -> None:
        raise RuntimeError("evaluation failed")

    session = _Session(SimpleNamespace(owner_id=OWNER_ID))
    _patch_runtime(monkeypatch, session, run_model=_Run, evaluator=fail_evaluation)

    with pytest.raises(RuntimeError, match="evaluation failed"):
        nightly.main(["--dataset-id", str(DATASET_ID), "--execute"])

    assert len(session.added) == 1
    assert session.commit_count == 1
    assert session.closed is True
