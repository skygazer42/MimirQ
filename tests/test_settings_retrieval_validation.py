from __future__ import annotations

import pytest


def test_settings_uses_shared_openai_base_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.constants import DEFAULT_OPENAI_API_BASE
    from app.core.config import Settings

    monkeypatch.delenv("LLM_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    cfg = Settings()
    assert cfg.LLM_API_BASE == DEFAULT_OPENAI_API_BASE


def test_settings_rejects_non_positive_retrieval_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_TOP_K", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_non_positive_rrf_k(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_RRF_K", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_dedup_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_DEDUP_JACCARD_THRESHOLD", "1.5")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_negative_diversity_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_MAX_CHUNKS_PER_DOC", "-1")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_negative_page_diversity_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_MAX_CHUNKS_PER_PAGE", "-1")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_retrieval_contract_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_CONTRACT_MODE", "unknown_mode")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_claim_verifier_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RAG_CLAIM_VERIFIER_MODE", "invalid")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_claim_nli_verifier_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RAG_CLAIM_NLI_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("RAG_CLAIM_NLI_VERIFIER_PROVIDER", "invalid_provider")
    with pytest.raises(ValueError):
        Settings()


def test_settings_accepts_claim_nli_verifier_openai_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RAG_CLAIM_NLI_VERIFIER_ENABLED", "true")
    monkeypatch.setenv("RAG_CLAIM_NLI_VERIFIER_PROVIDER", "openai_compatible")
    monkeypatch.setenv("RAG_CLAIM_NLI_VERIFIER_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", "8")

    cfg = Settings()
    assert cfg.RAG_CLAIM_NLI_VERIFIER_ENABLED is True
    assert cfg.RAG_CLAIM_NLI_VERIFIER_PROVIDER == "openai_compatible"
    assert cfg.RAG_CLAIM_NLI_VERIFIER_MODEL == "gpt-4o-mini"
    assert int(cfg.RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC) == 8


def test_settings_accepts_grounded_strict_chat_default_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("CHAT_DEFAULT_RETRIEVAL_PROFILE", "grounded_strict")
    cfg = Settings()
    assert cfg.CHAT_DEFAULT_RETRIEVAL_PROFILE == "grounded_strict"


def test_settings_accepts_hierarchy_hybrid_ce_chat_default_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("CHAT_DEFAULT_RETRIEVAL_PROFILE", "hierarchy_hybrid_ce")
    cfg = Settings()
    assert cfg.CHAT_DEFAULT_RETRIEVAL_PROFILE == "hierarchy_hybrid_ce"


def test_settings_exposes_safe_off_hierarchy_recall_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    for key in (
        "HIERARCHY_RECALL_ENABLED",
        "HIERARCHY_RECALL_FAMILY_COLLAPSE",
        "HIERARCHY_RECALL_FAMILY_AGGREGATION",
        "HIERARCHY_RECALL_TREE_DEDUP",
        "HIERARCHY_RECALL_PARENT_DEPTH",
        "HIERARCHY_RECALL_SIBLING_WINDOW",
        "HIERARCHY_RECALL_OVERFETCH_FACTOR",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = Settings()
    assert cfg.HIERARCHY_RECALL_ENABLED is False
    assert cfg.HIERARCHY_RECALL_FAMILY_COLLAPSE is False
    assert cfg.HIERARCHY_RECALL_FAMILY_AGGREGATION == "combined"
    assert cfg.HIERARCHY_RECALL_TREE_DEDUP is False
    assert int(cfg.HIERARCHY_RECALL_PARENT_DEPTH) == 0
    assert int(cfg.HIERARCHY_RECALL_SIBLING_WINDOW) == 0
    assert int(cfg.HIERARCHY_RECALL_OVERFETCH_FACTOR) == 4


def test_settings_accepts_hierarchy_recall_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HIERARCHY_RECALL_ENABLED", "true")
    monkeypatch.setenv("HIERARCHY_RECALL_FAMILY_COLLAPSE", "true")
    monkeypatch.setenv("HIERARCHY_RECALL_FAMILY_AGGREGATION", "score")
    monkeypatch.setenv("HIERARCHY_RECALL_TREE_DEDUP", "true")
    monkeypatch.setenv("HIERARCHY_RECALL_PARENT_DEPTH", "2")
    monkeypatch.setenv("HIERARCHY_RECALL_SIBLING_WINDOW", "3")
    monkeypatch.setenv("HIERARCHY_RECALL_OVERFETCH_FACTOR", "5")

    cfg = Settings()
    assert cfg.HIERARCHY_RECALL_ENABLED is True
    assert cfg.HIERARCHY_RECALL_FAMILY_COLLAPSE is True
    assert cfg.HIERARCHY_RECALL_FAMILY_AGGREGATION == "score"
    assert cfg.HIERARCHY_RECALL_TREE_DEDUP is True
    assert int(cfg.HIERARCHY_RECALL_PARENT_DEPTH) == 2
    assert int(cfg.HIERARCHY_RECALL_SIBLING_WINDOW) == 3
    assert int(cfg.HIERARCHY_RECALL_OVERFETCH_FACTOR) == 5


def test_settings_rejects_invalid_hierarchy_family_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HIERARCHY_RECALL_FAMILY_AGGREGATION", "votes")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_negative_hierarchy_parent_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HIERARCHY_RECALL_PARENT_DEPTH", "-1")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_too_large_hierarchy_parent_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HIERARCHY_RECALL_PARENT_DEPTH", "9")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_negative_hierarchy_sibling_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HIERARCHY_RECALL_SIBLING_WINDOW", "-1")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_too_large_hierarchy_sibling_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HIERARCHY_RECALL_SIBLING_WINDOW", "17")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_non_positive_hierarchy_overfetch_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HIERARCHY_RECALL_OVERFETCH_FACTOR", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_too_large_hierarchy_overfetch_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("HIERARCHY_RECALL_OVERFETCH_FACTOR", "33")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_parse_risk_hardcase_min_low_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO", "1.2")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_non_positive_parse_risk_hardcase_min_considered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_accepts_parse_risk_remediation_policy_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO", "0.45")
    monkeypatch.setenv("RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED", "5")
    monkeypatch.setenv("RETRIEVAL_PARSE_RISK_REPARSE_MAX_DOCS", "120")

    cfg = Settings()
    assert cfg.RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED is True
    assert abs(float(cfg.RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO) - 0.45) <= 1e-9
    assert int(cfg.RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED) == 5
    assert int(cfg.RETRIEVAL_PARSE_RISK_REPARSE_MAX_DOCS) == 120


def test_settings_accepts_table_sidecar_exclusive_routing_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("TABLE_STORE_SIDECAR_EXCLUSIVE_ROUTING", "true")
    cfg = Settings()
    assert cfg.TABLE_STORE_SIDECAR_EXCLUSIVE_ROUTING is True


def test_settings_rejects_invalid_sparse_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("SPARSE_RETRIEVAL_PROVIDER", "invalid_provider")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_splade_provider_without_model_when_sparse_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("SPARSE_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("SPARSE_RETRIEVAL_PROVIDER", "splade")
    monkeypatch.setenv("SPARSE_SPLADE_MODEL_NAME", "")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_non_positive_db_catalog_row_sync_max_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("DB_CATALOG_ROW_SYNC_MAX_TABLES", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_non_positive_db_catalog_row_sync_max_rows_per_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_non_positive_db_catalog_row_sync_max_cols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("DB_CATALOG_ROW_SYNC_MAX_COLS", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_accepts_db_catalog_row_sync_toggles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("DB_CATALOG_ROW_SYNC_ENABLED", "true")
    monkeypatch.setenv("DB_CATALOG_ROW_SYNC_MAX_TABLES", "25")
    monkeypatch.setenv("DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE", "40")
    monkeypatch.setenv("DB_CATALOG_ROW_SYNC_MAX_COLS", "30")

    cfg = Settings()
    assert cfg.DB_CATALOG_ROW_SYNC_ENABLED is True
    assert int(cfg.DB_CATALOG_ROW_SYNC_MAX_TABLES) == 25
    assert int(cfg.DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE) == 40
    assert int(cfg.DB_CATALOG_ROW_SYNC_MAX_COLS) == 30


def test_settings_rejects_non_positive_table_query_max_join_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("TABLE_QUERY_MAX_JOIN_TABLES", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_index_consistency_strictness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("INDEX_CONSISTENCY_STRICTNESS", "invalid")
    with pytest.raises(ValueError):
        Settings()


def test_settings_accepts_index_consistency_toggles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("INDEX_CONSISTENCY_ENABLED", "true")
    monkeypatch.setenv("INDEX_CONSISTENCY_STRICTNESS", "strict")
    monkeypatch.setenv("INDEX_CONSISTENCY_PATCH_CHUNK_STRICT", "true")
    monkeypatch.setenv("INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS", "true")

    cfg = Settings()
    assert cfg.INDEX_CONSISTENCY_ENABLED is True
    assert cfg.INDEX_CONSISTENCY_STRICTNESS == "strict"
    assert cfg.INDEX_CONSISTENCY_PATCH_CHUNK_STRICT is True
    assert cfg.INDEX_CONSISTENCY_EMIT_DRIFT_MARKERS is True


def test_settings_rejects_capsule_signing_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("EVIDENCE_CAPSULE_SIGNING_ENABLED", "true")
    monkeypatch.setenv("EVIDENCE_CAPSULE_SIGNING_SECRET", "")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_non_positive_must_recall_auto_source_keys_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_table_tag_cost_fanout_penalty_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT", "1.2")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_table_tag_low_confidence_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD", "-0.1")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_retrieval_contextual_followup_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE", "invalid")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_non_positive_retrieval_contextual_followup_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_accepts_retrieval_contextual_followup_toggles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE", "hybrid")
    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K", "18")
    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS", "5")
    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS", "6")
    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS", "3")
    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS", "420")

    cfg = Settings()
    assert cfg.RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED is True
    assert cfg.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE == "hybrid"
    assert int(cfg.RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K) == 18
    assert int(cfg.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS) == 5
    assert int(cfg.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS) == 6
    assert int(cfg.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS) == 3
    assert int(cfg.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS) == 420


def test_settings_rejects_invalid_intent_router_model_confidence_min(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN", "1.2")
    with pytest.raises(ValueError):
        Settings()


def test_settings_accepts_intent_router_model_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RAG_INTENT_ROUTER_MODEL_PATH", "artifacts/intent_router_model.v1.json")
    monkeypatch.setenv("RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN", "0.66")
    cfg = Settings()
    assert cfg.RAG_INTENT_ROUTER_MODEL_PATH == "artifacts/intent_router_model.v1.json"
    assert abs(float(cfg.RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN) - 0.66) <= 1e-9


def test_settings_rejects_non_positive_retrieval_contextual_followup_max_hops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_accepts_retrieval_contextual_followup_iterative_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS", "3")
    monkeypatch.setenv("RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS", "1800")
    cfg = Settings()
    assert int(cfg.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS) == 3
    assert abs(float(cfg.RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS) - 1800.0) <= 1e-9
