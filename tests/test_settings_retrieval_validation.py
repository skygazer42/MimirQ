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
