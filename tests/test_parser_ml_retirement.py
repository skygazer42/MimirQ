import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("provider", ["ltr", "xgboost_ltr", "xgboost-ltr"])
def test_retired_ltr_is_rejected_before_model_load_or_registry_lookup(provider):
    from app.infrastructure.model_policy import RetiredModelProviderError
    from app.rag.retrieval.reranking.factory import get_reranker

    with pytest.raises(RetiredModelProviderError, match="retired"):
        get_reranker(provider, model_path="historical-model.json")


@pytest.mark.parametrize("field", ["RERANKER_PROVIDER", "EVIDENCE_POST_RERANK_PROVIDER"])
def test_startup_rejects_retired_ltr_configuration(field):
    from app.infrastructure.config import Settings

    with pytest.raises(ValidationError, match="retired"):
        Settings.model_validate({"SECRET_KEY": "parser-retirement-test-key-not-used-by-services", field: "ltr"})


def test_tcadp_is_removed_from_parser_discovery_and_export_contract():
    from app.rag.ingestion.parsing.parsers.registry import iter_parser_backend_families, iter_parser_exports

    assert "tcadp" not in {family.canonical_name for family in iter_parser_backend_families()}
    assert "TCADPParser" not in {export.export_name for export in iter_parser_exports()}


@pytest.mark.parametrize("extension,backend", [(".pdf", "tcadp"), (".csv", "TCADP Parser"), (".txt", "tcadp")])
def test_actual_factory_does_not_fall_back_when_saved_backend_is_tcadp(extension, backend):
    from app.infrastructure.model_policy import RetiredModelProviderError
    from app.rag.ingestion.parsing.factory import ParserFactory

    with pytest.raises(RetiredModelProviderError, match="retired"):
        ParserFactory().resolve_backend(extension, backend)


def test_retrieval_reranker_rejects_ltr_before_provider_dispatch(monkeypatch):
    from app.infrastructure.model_policy import RetiredModelProviderError
    from app.rag.retrieval.reranking import factory

    calls = []
    monkeypatch.setitem(factory._PROVIDER_BUILDERS, "ltr", lambda *_args, **_kwargs: calls.append("ltr"))
    with pytest.raises(RetiredModelProviderError, match="retired"):
        factory.get_reranker_for_retrieval("ltr")
    assert calls == []


def test_dataset_write_guard_rejects_tcadp_before_persistence():
    from app.api.schemas.datasets.dataset import DatasetUpdate

    with pytest.raises(ValidationError, match="retired"):
        DatasetUpdate(default_parser_backend="tcadp")


def test_shared_dataset_dto_still_reads_historical_tcadp():
    from app.api.schemas.datasets.dataset import DatasetBase

    assert DatasetBase(name="history", default_parser_backend="tcadp").default_parser_backend == "tcadp"


def test_post_rerank_runtime_rejects_retired_ltr_before_the_best_effort_path(monkeypatch):
    from app.infrastructure.config import settings
    from app.infrastructure.model_policy import RetiredModelProviderError
    from app.rag.retrieval.stages.post_rerank import _post_rerank_settings as post_rerank_settings

    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "ltr")
    with pytest.raises(RetiredModelProviderError, match="retired"):
        post_rerank_settings({})


def test_post_rerank_pipeline_rejects_retired_stage_before_execution():
    from app.infrastructure.config import Settings

    with pytest.raises(ValidationError, match="retired"):
        Settings.model_validate(
            {
                "SECRET_KEY": "parser-retirement-test-key-not-used-by-services",
                "EVIDENCE_POST_RERANK_PROVIDER": "none",
                "EVIDENCE_POST_RERANK_PIPELINE_ENABLED": True,
                "EVIDENCE_POST_RERANK_PIPELINE": '[{"provider":"ltr","top_n":5}]',
            }
        )


def test_explicit_supported_pipeline_runs_without_an_implicit_single_provider(monkeypatch):
    from langchain_core.documents import Document

    from app.infrastructure.config import settings
    from app.infrastructure.model_policy import PostRerankStageConfig
    from app.rag.retrieval.stages import post_rerank

    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "none")
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", [PostRerankStageConfig(provider="pc", top_n=5)])
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", False)
    document = Document(page_content="evidence", id="chunk")
    calls = []

    def pipeline(**kwargs):
        calls.append([stage.model_dump() for stage in kwargs["pipeline"]])
        return {"docs": [document], "post_rerank_used": True, "post_rerank_score_calibration_used": False}

    def single(**_kwargs):
        pytest.fail("No unconfigured single-model fallback should execute")

    monkeypatch.setattr(post_rerank, "_run_post_rerank_pipeline_mode", pipeline)
    monkeypatch.setattr(post_rerank, "_run_post_rerank_single_mode", single)
    result = post_rerank._run_post_rerank_stage(
        state={},
        docs=[document],
        query_for_retrieval="q",
        top_k=1,
    )
    assert calls == [[{"provider": "pc", "top_n": 5}]]
    assert result["post_rerank_used"] is True


def test_pdf_initialization_and_existing_merge_rules_need_no_xgboost(monkeypatch):
    import builtins

    layout = ModuleType("app.rag.ingestion.parsing.models.layout")
    layout.LayoutRecognizer4YOLOv10 = lambda *_args: object()
    ocr = ModuleType("app.rag.ingestion.parsing.models.ocr")
    ocr.OCR = lambda: object()
    table_structure = ModuleType("app.rag.ingestion.parsing.models.table_structure")
    table_structure.TableStructureRecognizer = lambda: object()
    recognizer = ModuleType("app.rag.ingestion.parsing.models.recognizer")
    recognizer.Recognizer = object
    monkeypatch.setitem(sys.modules, layout.__name__, layout)
    monkeypatch.setitem(sys.modules, ocr.__name__, ocr)
    monkeypatch.setitem(sys.modules, table_structure.__name__, table_structure)
    monkeypatch.setitem(sys.modules, "app.rag.ingestion.parsing.models.recognizer", recognizer)
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
    path = Path(__file__).resolve().parents[1] / "app/rag/ingestion/parsing/parsers/pdf_layout.py"
    spec = importlib.util.spec_from_file_location("app.rag.ingestion.parsing.parsers.retirement_pdf_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.LayoutPdfParser()
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
