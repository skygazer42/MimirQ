from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.schemas.evaluation.regression import RagasRegressionRunCreateRequest
from app.api.v1.evaluation import routes


def test_ontology_run_records_active_release_for_the_background_worker(monkeypatch):
    tenant_id, dataset_id, version_id = uuid4(), uuid4(), uuid4()
    version = SimpleNamespace(id=version_id, number=4)
    monkeypatch.setattr(routes, "active_version_id", lambda *_args: version_id, raising=False)
    monkeypatch.setattr(routes, "published_version", lambda *_args: version, raising=False)
    background = BackgroundTasks()
    rows = []
    db = SimpleNamespace(add=rows.append, commit=lambda: None, refresh=lambda run: setattr(run, "id", uuid4()))

    run = routes._create_regression_run_and_enqueue(
        request=RagasRegressionRunCreateRequest(dataset_id=dataset_id, answer_mode="ontology"),
        background_tasks=background,
        tenant_id=tenant_id,
        account_id="reader",
        db=db,
    )

    assert rows == [run]
    assert run.params["answer_mode"] == "ontology"
    assert run.params["ontology_version_id"] == str(version_id)
    assert run.params["ontology_version_number"] == 4
    [task] = background.tasks
    assert task.kwargs["run_id"] == run.id


def test_ontology_run_requires_an_active_release_before_creating_a_record(monkeypatch):
    monkeypatch.setattr(routes, "active_version_id", lambda *_args: None, raising=False)
    background = BackgroundTasks()

    with pytest.raises(HTTPException) as exc:
        routes._create_regression_run_and_enqueue(
            request=RagasRegressionRunCreateRequest(dataset_id=uuid4(), answer_mode="ontology"),
            background_tasks=background,
            tenant_id=uuid4(),
            account_id="reader",
            db=SimpleNamespace(),
        )

    assert exc.value.status_code == 409
    assert background.tasks == []
