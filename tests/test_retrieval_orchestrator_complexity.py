import uuid
from time import sleep
from typing import Any

import pytest
from langchain_core.documents import Document


def _mk_doc(*, chunk_id: str, score: float) -> Document:
    return Document(
        page_content=f"doc:{chunk_id}",
        id=chunk_id,
        metadata={
            "document_id": f"doc-{chunk_id}",
            "chunk_id": chunk_id,
            "score": score,
            "retrieval_score": score,
        },
    )


class _EmptyModeRetriever:
    def __init__(self, *, docs_by_mode: dict[str, list[Document]], mode: str = "vector") -> None:
        self._docs_by_mode = {str(kind): list(documents or []) for kind, documents in (docs_by_mode or {}).items()}
        self._mode = str(mode or "vector")
        self._last_debug_metrics: dict[str, Any] = {
            "channels": {
                "retrieval_degraded": False,
                "degraded_reasons": [],
                "attempted_channels": [self._mode],
                "successful_channels": [],
                "all_retrieval_channels_failed": True,
            }
        }

    def model_copy(self, **kwargs: Any) -> "_EmptyModeRetriever":
        update = kwargs.get("update")
        update = update if isinstance(update, dict) else {}
        mode = str(update.get("retrieval_mode") or self._mode or "vector")
        return _EmptyModeRetriever(docs_by_mode=self._docs_by_mode, mode=mode)

    def invoke(self, _query: str) -> list[Document]:
        return list(self._docs_by_mode.get(self._mode, []))


class _QueryDrivenRetriever:
    def __init__(self, *, delays_by_query: dict[str, float] | None = None) -> None:
        self._delays_by_query = {str(query): float(delay) for query, delay in (delays_by_query or {}).items()}
        self._last_debug_metrics: dict[str, Any] = {}

    def model_copy(self, **_kwargs: Any) -> "_QueryDrivenRetriever":
        return self

    def invoke(self, query: str) -> list[Document]:
        sleep(self._delays_by_query.get(query, 0.0))
        chunk_id = f"chunk-{query.replace(' ', '-')}"
        return [
            Document(
                page_content=query,
                id=chunk_id,
                metadata={
                    "document_id": f"doc-{chunk_id}",
                    "chunk_id": chunk_id,
                    "source": f"{chunk_id}.md",
                    "score": 0.8,
                    "retrieval_score": 0.8,
                },
            )
        ]


def test_run_post_rerank_stage_falls_back_to_single_mode_after_pipeline_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    docs = [
        _mk_doc(chunk_id="a", score=0.9),
        _mk_doc(chunk_id="b", score=0.8),
    ]

    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "ltr", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 2, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", "ignored", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(
        settings,
        "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        settings,
        "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA",
        0.25,
        raising=False,
    )
    monkeypatch.setattr(
        orch_mod,
        "_safe_post_rerank_pipeline_summary",
        lambda _raw: [{"provider": "stage1", "top_n": 1}],
        raising=True,
    )

    def _pipeline_mode(**_kwargs: Any) -> dict[str, Any]:
        return {
            "docs": list(docs),
            "post_rerank_pipeline_stages": [],
            "post_rerank_used": False,
            "post_rerank_provider": None,
            "post_rerank_model_used": None,
            "post_rerank_candidates_n": 0,
            "post_rerank_elapsed": 0.0,
            "post_rerank_cache_hits": 1,
            "post_rerank_cache_misses": 2,
            "post_rerank_score_calibration_used": False,
        }

    def _single_mode(**_kwargs: Any) -> dict[str, Any]:
        return {
            "docs": [docs[1], docs[0]],
            "post_rerank_used": True,
            "post_rerank_provider": "ltr",
            "post_rerank_model_used": "single-model",
            "post_rerank_candidates_n": 2,
            "post_rerank_elapsed": 0.75,
            "post_rerank_cache_hits": 3,
            "post_rerank_cache_misses": 4,
            "post_rerank_score_calibration_used": True,
        }

    monkeypatch.setattr(orch_mod, "_run_post_rerank_pipeline_mode", _pipeline_mode, raising=False)
    monkeypatch.setattr(orch_mod, "_run_post_rerank_single_mode", _single_mode, raising=False)

    result = orch_mod._run_post_rerank_stage(
        state={"tenant_id": "tenant"},
        docs=docs,
        query_for_retrieval="q",
        top_k=2,
    )

    assert [doc.id for doc in result["docs"]] == ["b", "a"]
    assert result["post_rerank_pipeline"] == [{"provider": "stage1", "top_n": 1}]
    assert result["post_rerank_pipeline_used"] is True
    assert result["post_rerank_used"] is True
    assert result["post_rerank_provider"] == "ltr"
    assert result["post_rerank_model_used"] == "single-model"
    assert result["post_rerank_candidates_n"] == 2
    assert result["post_rerank_elapsed"] == 0.75
    assert result["post_rerank_cache_hits"] == 4
    assert result["post_rerank_cache_misses"] == 6
    assert result["post_rerank_score_calibration_used"] is True
    assert result["post_rerank_skip_reason"] == "pipeline_noop"


def test_run_retrieval_empty_hard_fallback_records_empty_diagnostics_and_config_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_HARDCASE_EMIT_ENABLED", True, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_kwargs: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    retriever = _EmptyModeRetriever(
        docs_by_mode={
            "vector": [],
            "keyword": [],
        }
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "find evidence",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 3,
            "retrieval_mode": "vector",
            "retrieval_contract_mode": "deterministic_recall",
            "rag_config_template": {
                "template_key": "baseline",
                "version": "2",
                "patch_hash": "patch-01",
            },
            "metrics": {},
        }
    )

    metrics = out.get("metrics") or {}
    empty_retrieval = metrics.get("empty_retrieval") or {}
    assert "hard_fallback_no_hit" in list(empty_retrieval.get("reasons") or [])
    assert (empty_retrieval.get("signals") or {}).get("hard_fallback_attempted") == 1
    assert (empty_retrieval.get("hard_fallback") or {}).get("mode") == "keyword"

    query_debug = out.get("query_debug") or {}
    assert (query_debug.get("empty_retrieval") or {}).get("hard_fallback") == {
        "mode": "keyword",
        "top_k": 30,
        "error": None,
    }

    retrieval_trace = out.get("retrieval_trace") or {}
    retrieval_config = retrieval_trace.get("retrieval_config") or {}
    assert retrieval_trace.get("schema") == "mimirq.retrieval_trace_pass.v1"
    assert retrieval_config.get("hash") == metrics.get("retrieval_config_hash")

    hardcase_candidate = metrics.get("hardcase_candidate") or {}
    assert hardcase_candidate.get("retrieval_config_hash") == retrieval_config.get("hash")
    assert hardcase_candidate.get("reason") == "abstain"


def test_run_retrieval_no_retrieval_intent_bypasses_retrieval_with_stable_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod,
        "route_intent",
        lambda _question: {"skip_retrieval": True, "intent": "chitchat"},
        raising=True,
    )
    monkeypatch.setattr(
        orch_mod,
        "get_rag_engine",
        lambda: pytest.fail("no-retrieval bypass must not initialize the engine"),
        raising=True,
    )

    out = orch_mod.run_retrieval(
        {
            "question": "hello there",
            "history": [],
            "retrieval_mode": "auto",
            "retrieval_profile": " Grounded_Strict ",
            "metrics": {},
        }
    )

    assert out["query_for_retrieval"] == "hello there"
    assert out["docs"] == []
    assert out["citations"] == []

    metrics = out.get("metrics") or {}
    assert metrics.get("retrieval_elapsed_sec") == 0.0
    assert metrics.get("retrieval_mode") == "auto"
    assert metrics.get("retrieval_mode_requested") == "auto"
    assert metrics.get("retrieval_mode_auto_routed") is False
    assert metrics.get("retrieval_profile") == "grounded_strict"
    assert metrics.get("retrieval_profile_requested") == "grounded_strict"
    assert metrics.get("retrieval_bypassed") is True
    assert metrics.get("retrieval_bypass_reason") == "no_retrieval_intent"
    assert metrics.get("retrieval_bypass_intent") == "chitchat"

    query_debug = out.get("query_debug") or {}
    assert query_debug.get("query_for_retrieval") == "hello there"
    assert query_debug.get("rewrite_used") is False
    assert query_debug.get("no_retrieval_intent") == {
        "skip_retrieval": True,
        "intent": "chitchat",
    }
    assert (query_debug.get("router_layers") or {}).get("schema") == "mimirq.router_layers.v1"

    retrieval_trace = out.get("retrieval_trace") or {}
    assert retrieval_trace.get("schema") == "mimirq.retrieval_trace_pass.v1"
    assert retrieval_trace.get("requested_retrieval_mode") == "auto"
    assert retrieval_trace.get("retrieval_mode") == "auto"
    assert retrieval_trace.get("retrieval_profile") == "grounded_strict"
    assert retrieval_trace.get("retrieval_profile_requested") == "grounded_strict"
    assert retrieval_trace.get("no_retrieval_intent") == {
        "skip_retrieval": True,
        "intent": "chitchat",
    }


def test_run_retrieval_parallel_variant_execution_preserves_public_query_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 3, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_kwargs: (
            [{"expanded_text": "dict evidence"}],
            {"enabled": True, "used": True},
        ),
        raising=True,
    )
    monkeypatch.setattr(
        orch_mod,
        "generate_alias_queries",
        lambda **_kwargs: (["alias evidence"], {"enabled": True, "used": True}),
        raising=True,
    )
    monkeypatch.setattr(
        orch_mod,
        "hybrid_retriever",
        _QueryDrivenRetriever(
            delays_by_query={
                "q": 0.03,
                "alias evidence": 0.02,
                "dict evidence": 0.0,
            }
        ),
        raising=True,
    )

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "retrieval_mode": "vector",
            "enable_query_alias_expansion": True,
            "query_aliases": ["alias evidence"],
            "metrics": {},
        }
    )

    metrics = out.get("metrics") or {}
    per_query = metrics.get("retrieval_per_query") or []
    assert [item.get("kind") for item in per_query] == ["main", "alias", "dict"]
    assert [item.get("query_chars") for item in per_query] == [1, 14, 13]

    trace = out.get("retrieval_trace") or {}
    trace_per_query = (trace.get("retrieval") or {}).get("per_query") or []
    assert [item.get("kind") for item in trace_per_query] == ["main", "alias", "dict"]


def test_routing_phase_resolves_orchestrator_module_monkeypatch_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    calls: dict[str, dict[str, Any]] = {}

    def _route_preset(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        calls["preset"] = dict(kwargs)
        return {"retrieval_mode": "keyword"}, {
            "enabled": True,
            "used": True,
            "seam": "preset",
        }

    def _route_adaptive(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        calls["adaptive"] = dict(kwargs)
        return {"top_k": 9}, {
            "enabled": True,
            "used": True,
            "seam": "adaptive",
        }

    monkeypatch.setattr(orch_mod, "route_retrieval_preset", _route_preset, raising=True)
    monkeypatch.setattr(
        orch_mod,
        "route_adaptive_retrieval_overrides",
        _route_adaptive,
        raising=True,
    )
    monkeypatch.setattr(
        orch_mod,
        "hybrid_retriever",
        _QueryDrivenRetriever(),
        raising=True,
    )

    state = {
        "retrieval_mode": "vector",
        "intent_router": True,
        "adaptive_router": True,
        "top_k": 3,
    }
    result = orch_mod._apply_routing_phase(
        state,
        query_for_retrieval="patched routing",
        requested_retrieval_mode="vector",
        requested_retrieval_profile=None,
        sparse_enabled=False,
        sparse_provider="deterministic",
        hierarchy_recall_enabled=False,
        hierarchy_family_collapse=False,
        hierarchy_family_aggregation="combined",
        hierarchy_tree_dedup=False,
        hierarchy_parent_depth=0,
        hierarchy_sibling_window=0,
        hierarchy_overfetch_factor=1,
    )

    assert calls["preset"]["query"] == "patched routing"
    assert calls["preset"]["retrieval_mode"] == "vector"
    assert calls["adaptive"]["retrieval_mode"] == "keyword"
    assert calls["adaptive"]["intent_meta"]["seam"] == "preset"
    assert result["intent_router_meta"]["seam"] == "preset"
    assert result["adaptive_router_meta"]["seam"] == "adaptive"
    assert result["retriever_update"]["k"] == 9


def test_contract_phase_resolves_orchestrator_module_monkeypatch_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    calls: dict[str, dict[str, Any]] = {}

    def _resolve_policy(**kwargs: Any) -> dict[str, Any]:
        calls["policy"] = dict(kwargs)
        return {
            "mode": "patched_contract",
            "deterministic_recall": True,
            "must_recall_strict": True,
            "enable_partial_miss_second_pass": True,
        }

    def _infer_sources(**kwargs: Any) -> dict[str, Any]:
        calls["sources"] = dict(kwargs)
        return {
            "expected_source_keys": ["patched-source"],
            "reason_codes": ["patched-source-reason"],
            "confidence": "high",
        }

    def _infer_anchors(**kwargs: Any) -> dict[str, Any]:
        calls["anchors"] = dict(kwargs)
        return {
            "required_anchor_fields": ["patched_anchor"],
            "reason_codes": ["patched-anchor-reason"],
            "applied": True,
        }

    monkeypatch.setattr(
        orch_mod,
        "resolve_retrieval_contract_policy",
        _resolve_policy,
        raising=True,
    )
    monkeypatch.setattr(
        orch_mod,
        "infer_expected_source_keys",
        _infer_sources,
        raising=True,
    )
    monkeypatch.setattr(
        orch_mod,
        "infer_required_anchor_fields",
        _infer_anchors,
        raising=True,
    )

    result = orch_mod._resolve_contract_phase(
        {
            "retrieval_contract_mode": "ignored-by-seam",
            "top_k": 4,
            "must_recall_auto_expected_source_keys_enabled": True,
            "must_recall_auto_required_anchor_fields_enabled": True,
            "metadata_filter": {"source": "scope"},
            "dataset_id": "dataset-scope",
        },
        query_for_retrieval="patched contract",
    )

    assert calls["policy"]["mode"] == "ignored-by-seam"
    assert calls["policy"]["requested_top_k"] == 4
    assert calls["sources"]["query"] == "patched contract"
    assert calls["sources"]["metadata_filter"] == {"source": "scope"}
    assert calls["sources"]["scope"] == {"dataset_id": "dataset-scope"}
    assert calls["anchors"]["query"] == "patched contract"
    assert result["retrieval_contract_mode"] == "patched_contract"
    assert result["contract_deterministic_recall"] is True
    assert result["contract_must_recall_strict"] is True
    assert result["must_recall_enabled"] is True
    assert result["must_recall_expected_source_keys"] == ["patched-source"]
    assert result["must_recall_auto_expected_source_keys_reason_codes"] == ["patched-source-reason"]
    assert result["must_recall_required_anchor_fields"] == ["patched_anchor"]
    assert result["must_recall_auto_required_anchor_fields_reason_codes"] == ["patched-anchor-reason"]
    assert result["must_recall_second_pass_enabled"] is True


def test_retrieval_runtime_registry_has_stable_semantic_phase_order() -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    expected_phase_names = (
        "_run_retrieval_bootstrap_phase",
        "_run_retrieval_alias_dictionary_phase",
        "_run_retrieval_kg_query_expansion_phase",
        "_run_retrieval_multi_query_phase",
        "_run_retrieval_hyde_phase",
        "_run_retrieval_step_back_phase",
        "_run_retrieval_decomposition_variants_phase",
        "_run_retrieval_retrieval_execution_phase",
        "_run_retrieval_fusion_phase",
        "_run_retrieval_kg_injection_phase",
        "_run_retrieval_tag_kg_boost_phase",
        "_run_retrieval_post_rerank_hierarchy_setup_phase",
        "_run_retrieval_contextual_followup_phase",
        "_run_retrieval_citations_hard_fallback_phase",
        "_run_retrieval_must_recall_phase",
        "_run_retrieval_parse_quality_phase",
        "_run_retrieval_metrics_core_phase",
        "_run_retrieval_channel_health_phase",
        "_run_retrieval_metrics_features_phase",
        "_run_retrieval_abstain_hardcase_phase",
        "_run_retrieval_query_debug_phase",
        "_run_retrieval_retrieval_trace_phase",
        "_run_retrieval_config_and_result_phase",
    )

    phase_names = tuple(phase.__name__ for phase in orch_mod._RETRIEVAL_RUNTIME_PHASES)
    assert len(phase_names) == 23
    assert phase_names == expected_phase_names
