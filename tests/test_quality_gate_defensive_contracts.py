import importlib

import pytest


@pytest.mark.parametrize("script_name", ["answer_quality_gate", "parsing_retrieval_proof_gate"])
@pytest.mark.parametrize("bound", ["min", "max"])
@pytest.mark.parametrize("invalid", ["not-a-number", None])
def test_quality_gate_rejects_malformed_configured_threshold(script_name, bound, invalid):
    module = importlib.import_module(f"scripts.{script_name}")
    with pytest.raises((TypeError, ValueError)):
        module.normalize_thresholds({"metrics": {"mrr": {bound: invalid}}})


@pytest.mark.parametrize("script_name", ["answer_quality_gate", "parsing_retrieval_proof_gate"])
@pytest.mark.parametrize("bound", ["min", "max"])
def test_quality_gate_preserves_explicit_zero_threshold(script_name, bound):
    module = importlib.import_module(f"scripts.{script_name}")
    thresholds = module.normalize_thresholds({"metrics": {"mrr": {bound: 0}}})
    assert thresholds["mrr"][bound] == 0.0
    evaluate = module.evaluate_answer_quality if script_name == "answer_quality_gate" else module.evaluate_parsing_proof
    assert evaluate(summary={"mrr": 0.0}, thresholds=thresholds)["passed"] is True


@pytest.mark.parametrize("bound", ["min", "max"])
@pytest.mark.parametrize("invalid", ["not-a-number", None, float("nan"), float("inf")])
def test_release_gate_rejects_malformed_configured_threshold(bound, invalid):
    module = importlib.import_module("scripts.release_gate")
    with pytest.raises((TypeError, ValueError)):
        module.normalize_thresholds({"mrr": {bound: invalid}})


def test_release_gate_preserves_zero_and_optional_metric_absence():
    module = importlib.import_module("scripts.release_gate")
    assert module.normalize_thresholds({"mrr": {"min": 0}}) == {"mrr": {"min": 0.0}}
    assert module._safe_float(None) is None
    assert module._safe_float("not-a-number") is None


def _zero_load_report():
    return {
        "ingest": {"requested": 0, "completed": 0, "errors": 0},
        "retrieve": {"requested": 0, "ok": 0, "errors": 0},
        "chat": {"requested": 0, "ok": 0, "errors": 0},
    }


@pytest.mark.parametrize(
    ("phase", "field"),
    [
        ("ingest", "requested"),
        ("ingest", "completed"),
        ("ingest", "errors"),
        ("retrieve", "requested"),
        ("retrieve", "ok"),
        ("retrieve", "errors"),
        ("chat", "requested"),
        ("chat", "ok"),
        ("chat", "errors"),
    ],
)
@pytest.mark.parametrize("invalid", ["not-a-number", None, -1, 0.5, False])
def test_load_gate_rejects_malformed_required_counter(phase, field, invalid):
    module = importlib.import_module("scripts.rag_e2e_load_test")
    report = _zero_load_report()
    report[phase][field] = invalid
    with pytest.raises(ValueError, match=f"{phase}.{field}"):
        module.evaluate_load_gate(report)


def test_load_gate_requires_counter_and_preserves_zero_report():
    module = importlib.import_module("scripts.rag_e2e_load_test")
    report = _zero_load_report()
    assert module.evaluate_load_gate(report)["passed"] is True
    del report["ingest"]["errors"]
    with pytest.raises(KeyError):
        module.evaluate_load_gate(report)
