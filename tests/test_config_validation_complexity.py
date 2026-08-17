import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_dify_external_knowledge_keeps_api_key_check_first() -> None:
    with pytest.raises(ValidationError, match="DIFY_EXTERNAL_KNOWLEDGE_API_KEYS required"):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "DIFY_EXTERNAL_KNOWLEDGE_ENABLED": True,
                "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX": 0,
            }
        )


def test_chunk_retrieval_validation_keeps_chunk_overlap_check_first() -> None:
    with pytest.raises(ValidationError, match=r"CHUNK_OVERLAP \(10\) must be less than CHUNK_SIZE \(10\)"):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "CHUNK_SIZE": 10,
                "CHUNK_OVERLAP": 10,
                "LLM_TEMPERATURE": 3,
            }
        )


def test_retrieval_fallback_modes_are_normalized_to_lowercase() -> None:
    configured = Settings.model_validate(
        {
            "SECRET_KEY": "test-only-signing-key-not-for-production",
            "RETRIEVAL_HARD_FALLBACK_MODE": "VECTOR",
            "RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE": "HYBRID",
            "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE": "MMR",
            "RETRIEVAL_HARD_FALLBACK_TOP_K": 2,
            "RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K": 2,
            "RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K": 2,
            "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS": 2,
            "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS": 0,
            "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS": 2,
            "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS": 32,
            "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS": 1,
        }
    )

    assert configured.RETRIEVAL_HARD_FALLBACK_MODE == "vector"
    assert configured.RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE == "hybrid"
    assert configured.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE == "mmr"


def test_parse_risk_auto_enqueue_levels_are_sorted_and_normalized() -> None:
    configured = Settings.model_validate(
        {
            "SECRET_KEY": "test-only-signing-key-not-for-production",
            "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS": " medium,UNKNOWN,High ",
        }
    )

    assert configured.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS == "high,medium,unknown"


def test_parse_risk_empty_auto_enqueue_levels_fall_back_to_default_levels() -> None:
    configured = Settings.model_validate(
        {
            "SECRET_KEY": "test-only-signing-key-not-for-production",
            "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS": " , ",
        }
    )

    assert configured.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS == "high,medium"
