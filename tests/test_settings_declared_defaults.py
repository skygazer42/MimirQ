import asyncio
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("weight,max_promoted,enabled", [(0.0, 2, True), (0.15, 0, True), (0.15, 2, False)])
def test_kg_boost_uses_actual_settings(weight, max_promoted, enabled, monkeypatch):
    from app.rag.retrieval import orchestrator

    monkeypatch.setattr(orchestrator.settings, "RAG_KG_CHUNK_BOOST_WEIGHT", weight)
    monkeypatch.setattr(orchestrator.settings, "RAG_KG_CHUNK_BOOST_MAX_PROMOTED", max_promoted)
    monkeypatch.setattr(orchestrator.settings, "RAG_KG_CHUNK_BOOST_ENABLED", enabled)
    context = SimpleNamespace(state={}, docs=[])
    orchestrator._run_retrieval_tag_kg_boost_phase(context)
    assert context.kg_chunk_boost_meta["weight"] == weight
    assert context.kg_chunk_boost_meta["max_promoted"] == max_promoted
    assert context.kg_chunk_boost_meta["enabled"] is enabled


def test_post_rerank_zero_calibration_is_preserved(monkeypatch):
    from app.rag.retrieval.stages.post_rerank import _post_rerank_settings as post_rerank_settings
    from app.rag.retrieval.stages.post_rerank import settings

    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA", 0.0)
    result = post_rerank_settings({})
    assert result["score_calibration_alpha"] == 0.0


def test_multi_query_zero_cap_and_false_flags_are_preserved(monkeypatch):
    from app.rag.retrieval.planning.contracts import ModelQueryOverrides
    from app.rag.retrieval.planning.options import resolve_model_query_settings, settings

    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT_CAP", 0)
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT", 3)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False)
    result = resolve_model_query_settings(ModelQueryOverrides())
    assert result.multi_query.count == 0
    assert result.multi_query.enabled is False


def test_preprocess_zero_sample_pages_reaches_scorer(monkeypatch):
    from app.rag.ingestion import pipeline as module
    from app.rag.ingestion.parsing.quality import scorer

    monkeypatch.setattr(module.settings, "PREPROCESS_SAMPLE_PAGES", 0)
    monkeypatch.setattr(module.settings, "IMAGE_PREPROCESS_ENABLED", True)
    score = MagicMock(return_value={})
    monkeypatch.setattr(scorer, "score_pdf_quality", score)
    monkeypatch.setattr(module, "metrics_span", lambda *a, **k: nullcontext())
    monkeypatch.setattr(
        module, "preprocess_image_document", lambda **k: SimpleNamespace(changed=False, to_dict=lambda: {})
    )
    module._apply_image_preprocess(
        db=MagicMock(),
        db_document=SimpleNamespace(doc_metadata={}),
        document_id=uuid4(),
        prepared_state=module.PreparedProcessDocumentState(
            file_path=Path("sample.pdf"),
            dataset_id=str(uuid4()),
            document_img_ids=set(),
            artifact_dirs=set(),
            pipeline_effective=MagicMock(),
            index_options=MagicMock(),
            governance_kwargs={},
        ),
        add_stage_duration=lambda *a: None,
    )
    assert score.call_args.kwargs["sample_pages"] == 0


def test_evaluation_snapshot_uses_declared_values_without_fabricating_zero(monkeypatch):
    from app.api.v1.evaluation import routes as evaluations
    from app.rag.evaluation.benchmarks import kg_search_diagnostics
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

    settings = evaluations.settings
    monkeypatch.setattr(settings, "KG_ENABLED", True)
    for name in ["KG_SEARCH_GRAPH_EMBEDDINGS_DIM", "KG_SEARCH_GRAPH_EMBEDDINGS_SEED", "KG_SEARCH_RELATION_MAX_EDGES"]:
        monkeypatch.setattr(settings, name, 0)
    monkeypatch.setattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY", 0.0)
    monkeypatch.setattr(settings, "KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED", False)
    monkeypatch.setattr(settings, "KG_RELATION_ENABLED", False)
    from app.api.schemas.evaluation.diagnostics import KGSearchDiagnosticsResponse, KGSearchDiagnosticsSummary

    dataset_id = uuid4()
    response = KGSearchDiagnosticsResponse(summary=KGSearchDiagnosticsSummary(dataset_id=dataset_id))
    monkeypatch.setattr(kg_search_diagnostics, "run_kg_search_diagnostics", AsyncMock(return_value=response))
    monkeypatch.setattr(evaluations.dataset_service, "ensure_member", lambda *a: None)
    monkeypatch.setattr(evaluations.dataset_service, "get_dataset", lambda *a: SimpleNamespace())
    monkeypatch.setattr(evaluations.dataset_service, "assert_dataset_readable", lambda *a: None)
    db = MagicMock()
    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", lambda: db)
    payload = evaluations.KGSearchDiagnosticsRequest(dataset_id=dataset_id, persist_run=True)
    asyncio.run(evaluations.run_kg_search_diagnostics(payload, tenant_id=uuid4(), account_id="owner", db=db))
    snapshot = db.add.call_args.args[0].params["settings_snapshot"]
    assert snapshot["KG_SEARCH_GRAPH_EMBEDDINGS_DIM"] == 0
    assert snapshot["KG_SEARCH_GRAPH_EMBEDDINGS_SEED"] == 0
    assert snapshot["KG_SEARCH_RELATION_MAX_EDGES"] == 0
    assert snapshot["KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY"] == 0.0
    assert snapshot["KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED"] is False
    assert snapshot["KG_RELATION_ENABLED"] is False


def test_configuration_rejects_a_missing_required_graph_embedding_dimension() -> None:
    from app.infrastructure.config import Settings

    with pytest.raises(ValidationError, match="KG_SEARCH_GRAPH_EMBEDDINGS_DIM"):
        Settings.model_validate({"KG_SEARCH_GRAPH_EMBEDDINGS_DIM": None})
