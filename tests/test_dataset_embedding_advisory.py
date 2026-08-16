from app.api.schemas.dataset_precheck import DatasetPrecheckEmbeddingAdvisory
from app.services.dataset_embedding_advisory import build_embedding_language_advisories


def _set_generic_defaults(monkeypatch) -> None:  # noqa: ANN001
    from app.services import dataset_embedding_advisory as advisory

    monkeypatch.setattr(advisory.settings, "EMBEDDING_PROVIDER", "openai_compatible", raising=False)
    monkeypatch.setattr(advisory.settings, "EMBEDDING_MODEL", "text-embedding-3-small", raising=False)
    monkeypatch.setattr(advisory.settings, "EMBEDDING_LANGUAGE_ROUTING_ENABLED", False, raising=False)
    monkeypatch.setattr(advisory.settings, "EMBEDDING_MODEL_ZH", "", raising=False)
    monkeypatch.setattr(advisory.settings, "EMBEDDING_MODEL_MIXED", "", raising=False)


def test_no_advisory_without_chinese_or_mixed_evidence(monkeypatch) -> None:  # noqa: ANN001
    _set_generic_defaults(monkeypatch)

    assert build_embedding_language_advisories(language_mix={"en": 4, "unknown": 1}) == []


def test_generic_embedding_warns_without_mutating_existing_dataset(monkeypatch) -> None:  # noqa: ANN001
    _set_generic_defaults(monkeypatch)

    rows = build_embedding_language_advisories(language_mix={"zh": 3, "mixed": 1, "en": 2})

    assert len(rows) == 1
    row = rows[0]
    assert row["code"] == "zh_or_mixed_corpus_uses_generic_embedding"
    assert row["effective_embedding"]["source"] == "global"
    assert row["recommended_action"] == "pin_dataset_embedding_defaults_before_first_index"
    assert row["migration_action_for_indexed_dataset"] == "use_embedding_blue_green_migration"
    assert row["mutates_existing_dataset"] is False
    assert any("bge-m3" in model_id.casefold() for model_id in row["recommended_model_ids"])
    assert DatasetPrecheckEmbeddingAdvisory.model_validate(row).code == row["code"]


def test_explicit_dataset_multilingual_embedding_does_not_warn(monkeypatch) -> None:  # noqa: ANN001
    _set_generic_defaults(monkeypatch)

    rows = build_embedding_language_advisories(
        language_mix={"zh": 5},
        dataset_metadata={
            "embedding_defaults": {
                "provider": "siliconflow",
                "model": "BAAI/bge-m3",
            }
        },
    )

    assert rows == []


def test_configured_language_route_suppresses_generic_default_warning(monkeypatch) -> None:  # noqa: ANN001
    _set_generic_defaults(monkeypatch)
    from app.services import dataset_embedding_advisory as advisory

    monkeypatch.setattr(advisory.settings, "EMBEDDING_LANGUAGE_ROUTING_ENABLED", True, raising=False)
    monkeypatch.setattr(advisory.settings, "EMBEDDING_MODEL_ZH", "siliconflow/BAAI/bge-m3", raising=False)

    assert build_embedding_language_advisories(language_mix={"zh": 2}) == []


def test_explicit_generic_dataset_embedding_is_identified_as_dataset_source(monkeypatch) -> None:  # noqa: ANN001
    _set_generic_defaults(monkeypatch)

    rows = build_embedding_language_advisories(
        language_mix={"mixed": 2},
        dataset_metadata={
            "embedding_defaults": {
                "provider": "openai_compatible",
                "model": "text-embedding-3-small",
            }
        },
    )

    assert rows[0]["effective_embedding"]["source"] == "dataset"
