import queue
from pathlib import Path
from uuid import uuid4

import pytest

from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.expand import ExpandResult
from app.rag.kg.search.searcher import _event_response
from app.services import online_eval_service
from app.services.evidence_drift_audit import classify_reference_source_drift
from scripts.parser_benchmark import BenchmarkCase, CaseGoldenData, _build_case_row


@pytest.mark.parametrize("assets", [[], ["missing.png"]])
def test_benchmark_report_keeps_the_actual_missing_asset_collections(assets: list[str]) -> None:
    case = BenchmarkCase(case_id="sample", path=Path("sample.md"))
    golden = CaseGoldenData(
        markdown="sample",
        structure={"headings": 1},
        plain_chars=6,
        image_refs=0,
        specialty=None,
        image_visual_kinds=None,
        image_code_values=None,
        table_continuity=None,
        missing_input_assets=assets,
        missing_local_assets=assets,
    )

    report = _build_case_row(case, golden)

    assert report["input_missing_local_assets"] == assets
    assert report["golden"]["missing_local_assets"] == assets


@pytest.mark.parametrize("observed", ["", 0, False, None])
def test_evidence_drift_diagnostics_keep_the_actual_mismatching_value(observed) -> None:
    document_id, dataset_id = uuid4(), uuid4()

    ok, reason, _expected, diagnostics = classify_reference_source_drift(
        reference_source={"document_id": str(document_id), "pipeline_hash": "pipeline-1"},
        document_row={"dataset_id": str(dataset_id)},
        chunk_row={"document_id": str(document_id), "metadata": {"pipeline_hash": observed}},
        suite_dataset_id=dataset_id,
    )

    assert ok is False
    assert reason == "pipeline_hash_mismatch"
    assert diagnostics["pipeline_hash"] == observed


@pytest.mark.parametrize("confidence", ["", None])
def test_kg_event_response_preserves_supplied_confidence(confidence: str | None) -> None:
    response = _event_response(
        config=SearchConfig(query="policy", query_mode_confidence=confidence),
        query_mode="local",
        rendered_events=[],
        expand_result=ExpandResult(key_final=[], event_ids=[], clues=[], event_scores={}, event_hops={}),
        combined_clues=[],
        stats={},
        community_reports=[],
        global_summary="",
    )

    assert response["query"]["mode_confidence"] == confidence


@pytest.fixture
def sampled_items(monkeypatch: pytest.MonkeyPatch):
    items = queue.Queue(maxsize=200)
    monkeypatch.setattr(online_eval_service, "_eval_queue", items)
    monkeypatch.setattr(online_eval_service, "_ensure_worker_started", lambda: None)
    monkeypatch.setattr(online_eval_service.settings, "ONLINE_EVAL_ENABLED", True)
    monkeypatch.setattr(online_eval_service.settings, "ENABLE_METRICS_LOG", True)
    monkeypatch.setattr(online_eval_service.settings, "ONLINE_EVAL_SAMPLE_RATE", 1.0)
    return items


@pytest.mark.parametrize("mode", ["", None])
def test_online_eval_item_preserves_the_actual_retrieval_mode(sampled_items, mode: str | None) -> None:
    result = online_eval_service.maybe_enqueue_online_eval(
        tenant_id="tenant-1",
        dataset_id=None,
        request_id="request-1",
        answer="answer",
        contexts=["context"],
        retrieval_mode=mode,
        citations_count=0,
    )

    assert result["enqueued"] is True
    item = sampled_items.get_nowait()
    assert item["retrieval_mode"] == mode
    assert item["citations_count"] == 0


def test_zero_online_eval_sample_rate_never_enqueues_work(sampled_items, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(online_eval_service.settings, "ONLINE_EVAL_SAMPLE_RATE", 0.0)

    results = [
        online_eval_service.maybe_enqueue_online_eval(
            tenant_id="tenant-1",
            dataset_id=None,
            request_id=f"request-{index}",
            answer="answer",
            contexts=["context"],
        )
        for index in range(100)
    ]

    assert all(result["enqueued"] is False for result in results)
    assert sampled_items.empty()
