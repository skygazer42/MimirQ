import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("provider", ["ltr", "xgboost_ltr", "xgboost-ltr"])
def test_retired_ltr_is_rejected_before_model_load_or_registry_lookup(provider):
    from app.core.model_execution import RetiredModelProviderError
    from app.rag.reranker.factory import get_reranker

    with pytest.raises(RetiredModelProviderError, match="retired"):
        get_reranker(provider, model_path="historical-model.json")


@pytest.mark.parametrize("field", ["RERANKER_PROVIDER", "EVIDENCE_POST_RERANK_PROVIDER"])
def test_startup_rejects_retired_ltr_configuration(field):
    from app.core.config import Settings

    with pytest.raises(ValidationError, match="retired"):
        Settings.model_validate({"SECRET_KEY": "parser-retirement-test-key-not-used-by-services", field: "ltr"})


def test_tcadp_is_removed_from_parser_discovery_and_export_contract():
    from app.parsing.parsers.registry import iter_parser_backend_families, iter_parser_exports

    assert "tcadp" not in {family.canonical_name for family in iter_parser_backend_families()}
    assert "TCADPParser" not in {export.export_name for export in iter_parser_exports()}


@pytest.mark.parametrize("extension,backend", [(".pdf", "tcadp"), (".csv", "TCADP Parser"), (".txt", "tcadp")])
def test_actual_factory_does_not_fall_back_when_saved_backend_is_tcadp(extension, backend):
    from app.core.model_execution import RetiredModelProviderError
    from app.parsing.factory import ParserFactory

    with pytest.raises(RetiredModelProviderError, match="retired"):
        ParserFactory().resolve_backend(extension, backend)


def test_legacy_reranker_wrapper_cannot_replace_ltr_with_another_provider(monkeypatch):
    from app.core.model_execution import RetiredModelProviderError
    from app.rag.reranker import factory

    calls = []
    monkeypatch.setattr(factory, "get_reranker", lambda provider: calls.append(provider))
    with pytest.raises(RetiredModelProviderError, match="retired"):
        factory.get_rag_reranker("ltr")
    assert calls == []


def test_dataset_write_guard_rejects_tcadp_before_persistence():
    from app.api.schemas.dataset import DatasetUpdate

    with pytest.raises(ValidationError, match="retired"):
        DatasetUpdate(default_parser_backend="tcadp")


def test_shared_dataset_dto_still_reads_historical_tcadp():
    from app.api.schemas.dataset import DatasetBase

    assert DatasetBase(name="history", default_parser_backend="tcadp").default_parser_backend == "tcadp"


def test_post_rerank_runtime_rejects_retired_ltr_before_the_best_effort_path(monkeypatch):
    from app.core.config import settings
    from app.core.model_execution import RetiredModelProviderError
    from app.rag.retrieval.orchestrator_support_post_rerank import post_rerank_settings

    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "ltr")
    with pytest.raises(RetiredModelProviderError, match="retired"):
        post_rerank_settings({}, cache_backend_fn=lambda: "memory", corpus_cache_token_fn=lambda _state: None)


def test_post_rerank_pipeline_rejects_retired_stage_before_execution(monkeypatch):
    from app.core.config import settings
    from app.core.model_execution import RetiredModelProviderError
    from app.rag.retrieval.orchestrator_support_post_rerank import post_rerank_settings

    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "none")
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", '[{"provider":"ltr","top_n":5}]')
    with pytest.raises(RetiredModelProviderError, match="retired"):
        post_rerank_settings({}, cache_backend_fn=lambda: "memory", corpus_cache_token_fn=lambda _state: None)


def test_explicit_supported_pipeline_runs_without_an_implicit_single_provider(monkeypatch):
    from langchain_core.documents import Document

    from app.core.config import settings
    from app.rag.retrieval.orchestrator_support_post_rerank import post_rerank_settings, run_post_rerank_stage

    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "none")
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", '[{"provider":"pc","top_n":5}]')
    meta = post_rerank_settings({}, cache_backend_fn=lambda: "memory", corpus_cache_token_fn=lambda _state: None)
    document = Document(page_content="evidence", id="chunk")
    calls = []

    def pipeline(**kwargs):
        calls.append(kwargs["pipeline"])
        return {"docs": [document], "post_rerank_used": True}

    def single(**_kwargs):
        pytest.fail("No unconfigured single-model fallback should execute")

    result = run_post_rerank_stage(
        state={},
        docs=[document],
        query_for_retrieval="q",
        top_k=1,
        settings_meta=meta,
        pipeline_summary_fn=lambda _raw: [{"provider": "pc", "top_n": 5}],
        pipeline_mode_fn=pipeline,
        single_mode_fn=single,
        fallback_logger_fn=lambda *_args: None,
    )
    assert calls == [[{"provider": "pc", "top_n": 5}]]
    assert result["post_rerank_used"] is True


def test_pdf_initialization_and_existing_merge_rules_need_no_xgboost(monkeypatch):
    import builtins

    model = ModuleType("app.deepdoc.src.model")
    model.rag_tokenizer = SimpleNamespace()
    vision = ModuleType("app.deepdoc.vision")
    vision.OCR = lambda: object()
    vision.LayoutRecognizer = lambda *_args: object()
    vision.TableStructureRecognizer = lambda: object()
    recognizer = ModuleType("app.deepdoc.vision.recognizer")
    recognizer.Recognizer = object
    monkeypatch.setitem(sys.modules, "app.deepdoc.src.model", model)
    monkeypatch.setitem(sys.modules, "app.deepdoc.vision", vision)
    monkeypatch.setitem(sys.modules, "app.deepdoc.vision.recognizer", recognizer)
    monkeypatch.setitem(
        sys.modules, "trio", SimpleNamespace(CapacityLimiter=lambda capacity: SimpleNamespace(capacity=capacity))
    )
    real_import = builtins.__import__
    attempts = []

    def guard(name, *args, **kwargs):
        if name == "xgboost":
            attempts.append(name)
            raise AssertionError("PDF parsing must not import a retired prediction model")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    path = Path(__file__).resolve().parents[1] / "app/deepdoc/parser/pdf_parser.py"
    spec = importlib.util.spec_from_file_location("app.deepdoc.parser.retirement_pdf_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.IntegratedPipelinePdfParser()
    parser.mean_height, parser.mean_width = [10.0], [5.0]
    up = {
        "page_number": 1,
        "top": 0,
        "bottom": 10,
        "x0": 0,
        "x1": 100,
        "text": "first line",
        "layout_type": "text",
        "layoutno": "1",
    }
    close = {**up, "top": 12, "bottom": 22, "text": "second line"}
    far = {**close, "top": 1000, "bottom": 1010}
    other_layout = {**close, "layoutno": "2"}
    assert parser._downward_concat_action(up, close, 0, True) == "concat"
    assert parser._downward_concat_action(up, far, 0, True) == "break"
    assert parser._downward_concat_action(up, other_layout, 0, True) == "skip"
    assert parser._downward_concat_action(up, close, 6, True) == "concat"
    assert attempts == []
