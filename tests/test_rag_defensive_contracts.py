import asyncio
import importlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from langchain_core.documents import Document

from app.rag.retrieval.reranking.types import RerankCandidate


class _BrokenString:
    def __str__(self) -> str:
        raise RuntimeError("broken string conversion")


class _BrokenNumber:
    def __int__(self) -> int:
        raise RuntimeError("broken numeric conversion")

    def __float__(self) -> float:
        raise RuntimeError("broken numeric conversion")


@pytest.mark.parametrize(
    ("module_name", "helper_name", "is_list"),
    [
        ("app.rag.evaluation.regression.ragas", "_coerce_uuid", False),
        ("app.rag.evaluation.regression.ragas", "_parse_uuid_list", True),
        ("app.rag.evaluation.benchmarks.kg_search_diagnostics", "_coerce_uuid_list", True),
        ("app.rag.kg.repository", "_as_uuid_list", True),
    ],
)
def test_uuid_metadata_parsers_preserve_conversion_failures(module_name, helper_name, is_list):
    helper = getattr(importlib.import_module(module_name), helper_name)
    value = _BrokenString()
    with pytest.raises(RuntimeError, match="broken string conversion"):
        helper([value] if is_list else value)


@pytest.mark.parametrize(
    ("module_name", "helper_name", "is_list"),
    [
        ("app.rag.evaluation.regression.ragas", "_coerce_uuid", False),
        ("app.rag.evaluation.regression.ragas", "_parse_uuid_list", True),
        ("app.rag.evaluation.benchmarks.kg_search_diagnostics", "_coerce_uuid_list", True),
        ("app.rag.kg.repository", "_as_uuid_list", True),
        ("app.rag.pipeline_plugins.runtime", "_coerce_uuid", False),
    ],
)
def test_uuid_metadata_parsers_keep_malformed_value_policy(module_name, helper_name, is_list):
    helper = getattr(importlib.import_module(module_name), helper_name)
    value = uuid4()
    if is_list:
        assert helper([None, "invalid", str(value)]) == [value]
    else:
        assert helper(None) is None
        assert helper("invalid") is None
        assert helper(str(value)) == value


@pytest.mark.parametrize("helper_name", ["_coerce_int", "_coerce_vector"])
def test_plugin_numbers_preserve_internal_conversion_failures(helper_name):
    runtime = importlib.import_module("app.rag.pipeline_plugins.runtime")
    value = _BrokenNumber()
    with pytest.raises(RuntimeError, match="broken numeric conversion"):
        getattr(runtime, helper_name)([value] if helper_name == "_coerce_vector" else value)


@pytest.mark.parametrize(
    ("module_name", "helper_name"),
    [
        ("app.rag.retrieval.evidence.citations", "_coerce_int"),
        ("app.rag.retrieval.evidence.capsule", "_coerce_float"),
        ("app.rag.policy.intent_router_model", "_coerce_int"),
        ("app.rag.policy.intent_router_model", "_coerce_float"),
        ("app.rag.evaluation.poc_runner.latency_decomposer", "_to_int"),
        ("app.rag.evaluation.poc_runner.latency_decomposer", "_to_float"),
        ("app.rag.evaluation.poc_runner.telemetry", "_coerce_int"),
        ("app.rag.evaluation.poc_runner.telemetry", "_coerce_float"),
        ("app.rag.evaluation.regression.retrieval_evaluator", "_to_float"),
        ("app.rag.policy.recall_obligation", "_to_int"),
    ],
)
def test_numeric_metadata_parsers_keep_internal_errors_visible(module_name, helper_name):
    helper = getattr(importlib.import_module(module_name), helper_name)
    with pytest.raises(RuntimeError, match="broken numeric conversion"):
        helper(_BrokenNumber())


@pytest.mark.parametrize(
    ("module_name", "helper_name"),
    [
        ("app.rag.evaluation.poc_runner.latency_decomposer", "_to_int"),
        ("app.rag.evaluation.poc_runner.latency_decomposer", "_to_float"),
        ("app.rag.evaluation.poc_runner.telemetry", "_coerce_int"),
        ("app.rag.evaluation.poc_runner.telemetry", "_coerce_float"),
        ("app.rag.evaluation.regression.retrieval_evaluator", "_to_float"),
    ],
)
def test_numeric_metadata_parsers_preserve_invalid_value_absence(module_name, helper_name):
    helper = getattr(importlib.import_module(module_name), helper_name)
    assert helper(None) is None
    assert helper("malformed") is None
    assert helper("3") == 3


def test_rerank_cache_distinguishes_malformed_scores_from_internal_failures(monkeypatch):
    module = importlib.import_module("app.rag.retrieval.cache.reranking")
    payload = {
        "ordered_ids": ["chunk-a"],
        "score_map": {"chunk-a": "malformed"},
        "provider": "pc",
        "model_used": None,
    }
    monkeypatch.setattr(module, "get_evidence_post_rerank_cache_backend", lambda: "memory", raising=False)
    monkeypatch.setattr(module, "_CACHE", SimpleNamespace(get=lambda _key: payload))
    result = module.get_cached_evidence_post_rerank_result("cache-key")
    assert result.ordered_ids == ["chunk-a"]
    assert result.score_map == {}
    payload["score_map"]["chunk-a"] = _BrokenNumber()
    with pytest.raises(RuntimeError, match="broken numeric conversion"):
        module.get_cached_evidence_post_rerank_result("cache-key")


def test_citation_snippet_rejects_non_integer_span_coordinates():
    module = importlib.import_module("app.rag.retrieval.evidence.citations")
    assert module._build_snippet_from_span("text", None, span_start=2, span_end=2) == ("", [])
    with pytest.raises(TypeError):
        module._build_snippet_from_span("text", None, span_start="invalid", span_end=2)


def test_kg_initialization_keeps_internal_override_conversion_failure_visible():
    module = importlib.import_module("app.rag.runtime.streaming.retrieval")
    runtime = SimpleNamespace(
        data=SimpleNamespace(
            docs=[], top_k=0, enable_kg_chunk_injection=None, kg_chunk_injection_max_chunks=_BrokenNumber()
        )
    )
    with pytest.raises(RuntimeError, match="broken numeric conversion"):
        asyncio.run(module.initialize_kg_enrichment(runtime))


def test_mcp_page_parser_skips_bad_text_and_exposes_internal_failure():
    module = importlib.import_module("app.rag.agents.tools.mcp_tools")

    class BrokenPageText(str):
        def strip(self):
            raise RuntimeError("page normalization failed")

    assert module._page_number("invalid") is None
    assert module._page_number(" 3 ") == 3
    with pytest.raises(RuntimeError, match="page normalization failed"):
        module._page_number(BrokenPageText("3"))


@pytest.mark.parametrize("kg", [False, True])
@pytest.mark.parametrize("validation", [{}, {"ok": False, "errors": []}])
def test_internal_plugin_validation_result_is_required(monkeypatch, kg, validation):
    runtime = importlib.import_module("app.rag.pipeline_plugins.runtime")
    monkeypatch.setattr(runtime, "is_registered_plugin_ref", lambda _ref: True)
    descriptor = SimpleNamespace(metadata_schema={}, retrieval_text_schema={})
    monkeypatch.setattr(runtime, "resolve_registered_plugin_descriptor", lambda *_args, **_kwargs: descriptor)
    validator_name = "validate_kg_events_metadata" if kg else "validate_documents_metadata"
    monkeypatch.setattr(runtime, validator_name, lambda *_args, **_kwargs: validation)
    with pytest.raises((KeyError, IndexError)):
        if kg:
            runtime._apply_registered_kg_plugin_contracts([], plugin_ref="plugin:test@1:kg", context={})
        else:
            runtime._apply_registered_plugin_contracts(
                [], plugin_ref="plugin:test@1:chunking", stage="chunking", context={}
            )


def test_kg_merge_keeps_document_identity_failures_visible(monkeypatch):
    module = importlib.import_module("app.rag.retrieval.ranking.knowledge_graph")

    def fail_key(_document):
        raise RuntimeError("broken document identity")

    monkeypatch.setattr(module, "document_key", fail_key)
    with pytest.raises(RuntimeError, match="broken document identity"):
        module._merge_kg_docs_preserving_main([Document(page_content="body")], [])


def test_kg_merge_retains_main_text_and_merges_graph_metadata():
    module = importlib.import_module("app.rag.retrieval.ranking.knowledge_graph")
    chunk_id = str(UUID(int=1))
    main = Document(page_content="main", metadata={"chunk_id": chunk_id, "kg_pagerank": 0.2})
    graph = Document(page_content="graph", metadata={"chunk_id": chunk_id, "kg_pagerank": 0.8})
    merged = module._merge_kg_docs_preserving_main([main], [graph])
    assert len(merged) == 1
    assert merged[0].page_content == "main"
    assert merged[0].metadata["kg_pagerank"] == 0.8


def test_optional_kg_phase_records_merge_failure_and_preserves_main_evidence(monkeypatch):
    ranking = importlib.import_module("app.rag.retrieval.ranking.knowledge_graph")
    stage = importlib.import_module("app.rag.retrieval.stages.knowledge_graph")
    failure = RuntimeError("broken document identity")
    main = [Document(page_content="main evidence")]
    ctx = SimpleNamespace(
        state={"tenant_id": str(uuid4()), "enable_kg_chunk_injection": True},
        docs=main,
    )
    recorded = []

    def fail_key(_document):
        raise failure

    monkeypatch.setattr(stage.settings, "KG_ENABLED", True)
    monkeypatch.setattr(stage.settings, "KG_CHAT_ENABLED", True)
    monkeypatch.setattr(stage, "_resolve_kg_scope", lambda _state: ([uuid4()], None, []))
    monkeypatch.setattr(stage, "_run_kg_injection", lambda _ctx: [Document(page_content="graph evidence")])
    monkeypatch.setattr(
        stage, "_log_orchestrator_fallback", lambda operation, error: recorded.append((operation, error))
    )
    monkeypatch.setattr(ranking, "document_key", fail_key)

    assert stage._run_retrieval_kg_injection_phase(ctx) is None
    assert ctx.docs is main
    assert ctx.kg_chunks_injected == 0
    assert ctx.kg_chunk_injection_error == "broken document identity"
    assert recorded == [("kg_chunk_injection", failure)]


@pytest.mark.parametrize("helper_name", ["_merge_contextual_docs", "_merge_hard_fallback_docs"])
def test_retrieval_merges_keep_document_identity_failures_visible(monkeypatch, helper_name):
    module = importlib.import_module("app.rag.retrieval.stages.followup")

    def fail_key(_document):
        raise RuntimeError("broken document identity")

    monkeypatch.setattr(module, "document_key", fail_key)
    with pytest.raises(RuntimeError, match="broken document identity"):
        getattr(module, helper_name)([Document(page_content="body")], [])


class _UnavailableDatabase:
    def query(self, *_args):
        raise RuntimeError("database unavailable")


@pytest.mark.parametrize(
    ("helper_name", "scope_key"),
    [("_load_relation_alias_pairs", "entity_ids"), ("_load_skill_tags", "skill_ids")],
)
def test_kg_diagnostics_preserves_database_failures(helper_name, scope_key):
    module = importlib.import_module("app.rag.evaluation.benchmarks.kg_search_diagnostics")
    with pytest.raises(RuntimeError, match="database unavailable"):
        getattr(module, helper_name)(_UnavailableDatabase(), tenant_id=uuid4(), **{scope_key: [uuid4()]})


def test_kg_rrf_preserves_association_database_failures():
    module = importlib.import_module("app.rag.kg.search.ranking.rrf")

    class UnavailableRepository:
        def get_entities_for_events(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        module._safe_assoc_map(UnavailableRepository(), [str(uuid4())], uuid4(), {str(uuid4())})


def test_kg_rrf_preserves_document_label_database_failures():
    module = importlib.import_module("app.rag.kg.search.ranking.rrf")
    with pytest.raises(RuntimeError, match="database unavailable"):
        module._load_document_labels(_UnavailableDatabase(), [SimpleNamespace(document_id=uuid4())], tenant_id=uuid4())


def test_kg_default_tenant_rejects_invalid_configuration(monkeypatch):
    module = importlib.import_module("app.models.knowledge_graph.entities")
    monkeypatch.setattr(module.settings, "DEFAULT_TENANT_ID", "invalid")
    with pytest.raises(ValueError):
        module._default_tenant()


@pytest.mark.parametrize("helper_name", ["_signing_secret_from_settings", "_resolve_validation_options"])
def test_evidence_security_options_preserve_configuration_failures(monkeypatch, helper_name):
    config = importlib.import_module("app.infrastructure.config")
    module = importlib.import_module("app.rag.retrieval.evidence.capsule")

    class UnavailableSettings:
        def __getattr__(self, _name):
            raise RuntimeError("settings unavailable")

    monkeypatch.setattr(config, "settings", UnavailableSettings())
    with pytest.raises(RuntimeError, match="settings unavailable"):
        if helper_name == "_resolve_validation_options":
            module._resolve_validation_options(None, None)
        else:
            module._signing_secret_from_settings()


@pytest.mark.parametrize(
    ("failure", "error", "message"),
    [
        (RuntimeError("signing failed"), RuntimeError, "signing failed"),
        (None, ValueError, "produced no signature"),
    ],
)
def test_evidence_signing_failure_cannot_return_unsigned_capsule(monkeypatch, failure, error, message):
    config = importlib.import_module("app.infrastructure.config")
    module = importlib.import_module("app.rag.retrieval.evidence.capsule")
    monkeypatch.setattr(
        config,
        "settings",
        SimpleNamespace(
            EVIDENCE_CAPSULE_SIGNING_ENABLED=True,
            EVIDENCE_CAPSULE_SIGNING_SECRET="secret",
            EVIDENCE_CAPSULE_SIGNING_KEY_ID="default",
        ),
    )

    def fail_sign(*_args, **_kwargs):
        if failure is not None:
            raise failure
        return None

    monkeypatch.setattr(module, "sign_evidence_capsule", fail_sign)
    with pytest.raises(error, match=message):
        module.build_evidence_capsule(query_for_retrieval="query", citations=[], metrics={}, retrieval_trace=None)


def test_retrieval_factory_preserves_selected_reranker_failure(monkeypatch):
    provider = importlib.import_module("app.rag.retrieval.reranking.factory")

    def fail_factory(*_args, **_kwargs):
        raise RuntimeError("selected provider failed")

    monkeypatch.setattr(provider, "get_reranker", fail_factory)
    with pytest.raises(RuntimeError, match="selected provider failed"):
        provider.get_reranker_for_retrieval("weighted")


def test_explicitly_disabled_reranker_keeps_identity_mode():
    adapter = importlib.import_module("app.rag.retrieval.reranking.factory")
    reranker = adapter.get_reranker_for_retrieval("none")
    result = reranker.rerank(
        "query",
        [
            RerankCandidate(id="chunk-a", text="first", metadata={"score": 0.8}),
            RerankCandidate(id="chunk-b", text="second", metadata={"retrieval_score": 0.5}),
        ],
    )
    assert reranker.provider == "none"
    assert result.ordered_ids == ["chunk-a", "chunk-b"]
    assert result.score_map == {"chunk-a": 0.8, "chunk-b": 0.5}
