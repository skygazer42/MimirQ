from __future__ import annotations

import pytest


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
