from __future__ import annotations

import importlib
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest


def _import_bundle_module():
    try:
        return importlib.import_module("app.services.regression_run_bundle")
    except ModuleNotFoundError:
        pytest.fail("Missing module: app.services.regression_run_bundle", pytrace=False)


def test_export_regression_run_bundle_is_pii_safe_by_default():
    mod = _import_bundle_module()
    assert hasattr(mod, "export_regression_run_bundle"), "export_regression_run_bundle helper must exist"

    run_id = uuid4()
    tenant_id = uuid4()
    dataset_id = uuid4()
    case_id = uuid4()

    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="completed",
        metrics=["retrieval_mrr"],
        params={"rag_params": {"top_k": 20}},
        summary={"retrieval_mrr": 0.5},
        error_message=None,
        created_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        started_at=None,
        finished_at=None,
    )

    items = [
        SimpleNamespace(
            case_id=case_id,
            question="What is Alice's SSN?",
            response="Alice SSN is 123-45-6789",
            retrieved_contexts=["Sensitive chunk text..."],
            citations=[
                {
                    "chunk_id": str(uuid4()),
                    "document_id": str(uuid4()),
                    "chunk_content": "LEAK",
                    "document_name": "LEAK",
                    "relevance_score": 0.9,
                }
            ],
            scores={"retrieval_mrr": 0.5},
            meta={"slice_file_type": "pdf"},
            created_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        )
    ]

    bundle = mod.export_regression_run_bundle(run, items)

    assert bundle["schema"] == "mimirq.ragas_regression_run_bundle.v1"
    assert bundle["run"]["id_hash"]
    assert bundle["run"]["tenant_id_hash"]
    assert bundle["run"]["dataset_id_hash"]

    assert isinstance(bundle["items"], list)
    assert len(bundle["items"]) == 1
    it = bundle["items"][0]

    # PII-safe defaults: no raw question/response/contexts
    assert "question" not in it
    assert "response" not in it
    assert "retrieved_contexts" not in it
    assert "case_id" not in it
    assert it.get("case_id_hash")

    # But hashes exist.
    assert it["question_hash"]
    assert it["question_chars"] > 0
    assert it["response_hash"]
    assert it["response_chars"] > 0

    # Citations are allowlisted (no chunk_content leakage)
    assert isinstance(it["citations"], list)
    assert it["citations"], "expected citations to be present (sanitized)"
    safe_c0 = it["citations"][0]
    assert "chunk_content" not in safe_c0
    assert "document_name" not in safe_c0
    assert safe_c0.get("chunk_id")


def test_export_regression_run_bundle_can_include_text_and_contexts():
    mod = _import_bundle_module()

    run = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), dataset_id=uuid4(), status="completed")
    item = SimpleNamespace(
        case_id=uuid4(),
        question="Q1",
        response="A1",
        retrieved_contexts=["c1"],
        citations=[],
        scores={},
        meta={},
    )

    bundle = mod.export_regression_run_bundle(run, [item], include_text=True, include_contexts=True, redact_ids=False)
    it = bundle["items"][0]
    assert it["question"] == "Q1"
    assert it["response"] == "A1"
    assert it["retrieved_contexts"] == ["c1"]
    assert it.get("case_id")


def test_export_regression_run_bundle_rejects_contexts_without_text_flag():
    mod = _import_bundle_module()

    run = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), dataset_id=uuid4(), status="completed")
    item = SimpleNamespace(case_id=uuid4(), question="Q1", response="A1", retrieved_contexts=["c1"], citations=[])

    with pytest.raises(Exception):
        mod.export_regression_run_bundle(run, [item], include_text=False, include_contexts=True)


def test_export_bundle_endpoint_is_registered():
    # Avoid importing app.api.v1.evaluations (it pulls in heavy ML deps).
    from pathlib import Path

    text = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")
    assert '@router.get("/ragas/regression/runs/{run_id}/export-bundle"' in text
