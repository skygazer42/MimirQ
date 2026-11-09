import os

import pytest
from pydantic import ValidationError

FIELDS = [
    ("CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", "int"),
    ("DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC", "float"),
    ("FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS", "int"),
    ("GOVERNANCE_REGEX_TIMEOUT_MS", "int"),
    ("IMAGE_OCR_MAX_CHARS", "int"),
    ("IMAGE_OCR_MAX_IMAGES", "int"),
    ("KG_COMMUNITY_GLOBAL_SUMMARY_MAX_CHARS", "int"),
    ("KG_COMMUNITY_MAX_ENTITIES_PER_COMMUNITY", "int"),
    ("KG_COMMUNITY_MAX_ENTITIES_PER_EVENT", "int"),
    ("KG_COMMUNITY_MAX_EVENTS", "int"),
    ("KG_COMMUNITY_MAX_EVENTS_PER_COMMUNITY", "int"),
    ("KG_ENTITY_LINK_MAX_ENTITIES_PER_EVENT", "int"),
    ("KG_EXTRACT_CONTEXT_MAX_CHARS", "int"),
    ("KG_LAZY_COMMUNITY_SUMMARY_CACHE_MAX_ENTRIES", "int"),
    ("KG_RELATION_ALIAS_MAX_CANDIDATES_PER_CHUNK", "int"),
    ("KG_RELATION_MAX_RELATIONS_PER_CHUNK", "int"),
    ("KG_SEARCH_GRAPH_EMBEDDINGS_MAX_ENTITIES", "int"),
    ("KG_SEARCH_GRAPH_EMBEDDINGS_MAX_EVENTS", "int"),
    ("KG_SEARCH_GRAPH_EMBEDDINGS_MAX_RELATIONS", "int"),
    ("LLM_TIMEOUT", "int"),
    ("MAGIC_PDF_REQUEST_TIMEOUT_SEC", "int"),
    ("MAX_FILE_SIZE", "int"),
    ("PASSWORD_MIN_LENGTH", "int"),
    ("PIPELINE_FORM_JSON_MAX_CHARS", "int"),
    ("PRECHECK_NEAR_DUP_MAX_PAIRS", "int"),
    ("RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", "int"),
    ("RAG_CRAG_STREAMING_MAX_RESULTS", "int"),
    ("RAG_TEMPORAL_INTENT_MAX_DOCS", "int"),
    ("RERANKER_API_MAX_CONCURRENCY", "int"),
    ("RERANKER_MAX_CHARS", "int"),
    ("SCIM_PAGE_SIZE_MAX", "int"),
    ("TABLE_LOTUS_MAX_ROWS", "int"),
    ("TABLE_QUERY_MAX_BYTES", "int"),
    ("TABLE_QUERY_MAX_COLS", "int"),
    ("TABLE_QUERY_MAX_ROWS", "int"),
    ("TABLE_SEM_FILTER_MAX_COLS", "int"),
    ("TABLE_SEM_FILTER_MAX_IN_ROWS", "int"),
    ("VISION_LLM_MAX_TOKENS", "int"),
    ("VISION_LLM_TIMEOUT_SEC", "int"),
    ("VISION_RAG_GENERATION_MAX_IMAGES", "int"),
    ("VISION_RAG_READER_MAX_IMAGES", "int"),
    ("VISION_RAG_READER_MAX_OUTPUT_CHARS", "int"),
    ("VLM_CORRECTION_MAX_CHARS", "int"),
    ("VLM_CORRECTION_MAX_PAGES", "int"),
    ("VLM_CORRECTION_TIMEOUT_SEC", "int"),
    ("WEB_SEARCH_TIMEOUT_SEC", "float"),
    ("TOOL_CALL_LOG_MAX_PREVIEW_CHARS", "int"),
    ("AGENT_LOG_MAX_PREVIEW_CHARS", "int"),
    ("BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS", "int"),
]


@pytest.mark.parametrize("field,kind", FIELDS)
def test_resource_configuration_rejects_zero(field, kind, monkeypatch):
    from app.core.config import Settings

    for key in list(os.environ):
        monkeypatch.delenv(key)
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, SECRET_KEY="unit-test-secret-key-with-more-than-32-characters", **{field: 0})


@pytest.mark.parametrize("field", [field for field, kind in FIELDS if kind == "float"])
def test_float_resource_configuration_rejects_negative(field, monkeypatch):
    from app.core.config import Settings

    for key in list(os.environ):
        monkeypatch.delenv(key)
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, SECRET_KEY="unit-test-secret-key-with-more-than-32-characters", **{field: -0.5})
