from __future__ import annotations

import importlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest


def _import_bundle_module():
    try:
        return importlib.import_module("app.services.regression_case_bundle")
    except ModuleNotFoundError:
        pytest.fail("Missing module: app.services.regression_case_bundle", pytrace=False)


def test_export_case_bundle_format_and_omits_internal_ids():
    mod = _import_bundle_module()
    assert hasattr(mod, "export_case_bundle"), "export_case_bundle helper must exist"

    dataset_id = uuid4()
    other_dataset_id = uuid4()

    cases = [
        SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            dataset_id=dataset_id,
            question="b",
            expected_answer="a2",
            tags=["t2"],
            reference_sources=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
        ),
        SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            dataset_id=dataset_id,
            question="a",
            expected_answer=None,
            tags=[],
            reference_sources=[{"document_id": str(uuid4()), "chunk_id": str(uuid4()), "quote": "q"}],
        ),
    ]

    bundle = mod.export_case_bundle(cases, dataset_id)

    assert bundle["schema"] == "mimirq.regression_cases.v1"
    assert UUID(bundle["dataset_id"]) == dataset_id
    assert isinstance(bundle["items"], list)
    assert [it["question"] for it in bundle["items"]] == ["a", "b"]

    for item in bundle["items"]:
        assert set(item.keys()) == {"question", "expected_answer", "tags", "reference_sources"}
        assert "id" not in item
        assert "tenant_id" not in item

    # Defensive: ensure helper doesn't silently accept mixed-dataset input.
    cases[0].dataset_id = other_dataset_id
    with pytest.raises(Exception):
        mod.export_case_bundle(cases, dataset_id)


def test_export_endpoint_is_registered():
    # Avoid importing app.api.v1.evaluations (it pulls in heavy ML deps).
    # This is a lightweight contract test: endpoint decorator must exist.
    from pathlib import Path

    text = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")
    assert '@router.get("/ragas/regression/cases/export"' in text


def test_export_case_bundle_includes_multihop_fields_when_present():
    mod = _import_bundle_module()

    dataset_id = uuid4()
    case = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=dataset_id,
        question="multi-hop q",
        expected_answer=None,
        tags=[],
        reference_sources=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
        extra={
            "reasoning_hops": ["h1", "h2"],
            "evidence_chain": [{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
        },
    )

    bundle = mod.export_case_bundle([case], dataset_id)
    item = bundle["items"][0]
    assert item["reasoning_hops"] == ["h1", "h2"]
    assert isinstance(item["evidence_chain"], list) and len(item["evidence_chain"]) == 1


def test_export_case_bundle_includes_plugin_extra_metadata():
    mod = _import_bundle_module()

    dataset_id = uuid4()
    case = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=dataset_id,
        question="plugin q",
        expected_answer=None,
        tags=["plugin:demo"],
        reference_sources=[{"document_id": str(uuid4()), "chunk_id": str(uuid4())}],
        extra={
            "source": "plugin_golden_draft",
            "plugin_id": "demo",
            "expected_metadata": {"source_record_id": "record-1"},
            "reasoning_hops": ["h1"],
        },
    )

    bundle = mod.export_case_bundle([case], dataset_id)
    item = bundle["items"][0]

    assert item["extra"] == {
        "source": "plugin_golden_draft",
        "plugin_id": "demo",
        "expected_metadata": {"source_record_id": "record-1"},
    }
    assert item["reasoning_hops"] == ["h1"]
