# Positive resource contracts

54 numeric fields: int ge=1 / float gt=0. Two required roots: UPLOAD_DIR and TABLE_STORE_DIR use _require_nonempty. Zero/negative deployments now fail startup. Declared defaults unchanged.

| Field | Type |
|---|---|
| `CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES` | int |
| `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC` | float |
| `FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS` | int |
| `GOVERNANCE_REGEX_TIMEOUT_MS` | int |
| `IMAGE_OCR_MAX_CHARS` | int |
| `IMAGE_OCR_MAX_IMAGES` | int |
| `KG_COMMUNITY_GLOBAL_SUMMARY_MAX_CHARS` | int |
| `KG_COMMUNITY_MAX_ENTITIES_PER_COMMUNITY` | int |
| `KG_COMMUNITY_MAX_ENTITIES_PER_EVENT` | int |
| `KG_COMMUNITY_MAX_EVENTS` | int |
| `KG_COMMUNITY_MAX_EVENTS_PER_COMMUNITY` | int |
| `KG_ENTITY_LINK_MAX_ENTITIES_PER_EVENT` | int |
| `KG_EXTRACT_CONTEXT_MAX_CHARS` | int |
| `KG_LAZY_COMMUNITY_SUMMARY_CACHE_MAX_ENTRIES` | int |
| `KG_RELATION_ALIAS_MAX_CANDIDATES_PER_CHUNK` | int |
| `KG_RELATION_MAX_RELATIONS_PER_CHUNK` | int |
| `KG_SEARCH_GRAPH_EMBEDDINGS_MAX_ENTITIES` | int |
| `KG_SEARCH_GRAPH_EMBEDDINGS_MAX_EVENTS` | int |
| `KG_SEARCH_GRAPH_EMBEDDINGS_MAX_RELATIONS` | int |
| `LLM_TIMEOUT` | int |
| `MAGIC_PDF_REQUEST_TIMEOUT_SEC` | int |
| `MAX_FILE_SIZE` | int |
| `PASSWORD_MIN_LENGTH` | int |
| `PIPELINE_FORM_JSON_MAX_CHARS` | int |
| `PRECHECK_NEAR_DUP_MAX_PAIRS` | int |
| `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | int |
| `RAG_CRAG_STREAMING_MAX_RESULTS` | int |
| `RAG_TEMPORAL_INTENT_MAX_DOCS` | int |
| `RERANKER_API_MAX_CONCURRENCY` | int |
| `RERANKER_MAX_CHARS` | int |
| `SCIM_PAGE_SIZE_MAX` | int |
| `TABLE_LOTUS_MAX_ROWS` | int |
| `TABLE_QUERY_MAX_BYTES` | int |
| `TABLE_QUERY_MAX_COLS` | int |
| `TABLE_QUERY_MAX_ROWS` | int |
| `TABLE_SEM_FILTER_MAX_COLS` | int |
| `TABLE_SEM_FILTER_MAX_IN_ROWS` | int |
| `VISION_LLM_MAX_TOKENS` | int |
| `VISION_LLM_TIMEOUT_SEC` | int |
| `VISION_RAG_GENERATION_MAX_IMAGES` | int |
| `VISION_RAG_READER_MAX_IMAGES` | int |
| `VISION_RAG_READER_MAX_OUTPUT_CHARS` | int |
| `VLM_CORRECTION_MAX_CHARS` | int |
| `VLM_CORRECTION_MAX_PAGES` | int |
| `VLM_CORRECTION_TIMEOUT_SEC` | int |
| `WEB_SEARCH_TIMEOUT_SEC` | float |
| `TOOL_CALL_LOG_MAX_PREVIEW_CHARS` | int |
| `AGENT_LOG_MAX_PREVIEW_CHARS` | int |
| `BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS` | int |
| `TASK_JOB_TIMEOUT_SEC` | int |
| `TASK_SEMAPHORE_LEASE_TTL_SEC` | int |
| `SECURITY_HEADERS_HSTS_MAX_AGE_SEC` | int |
| `TENANT_QPS_QUOTA_REDIS_KEY_TTL_SEC` | int |
| `TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS` | int |

## Deferred for concurrent writer

- `app/rag/pipelines/langgraph.py:740` `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC`: static avoidance; declarations validated, consumers untouched.
- `app/rag/pipelines/langgraph.py:987` `FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS`: static avoidance; declarations validated, consumers untouched.
- `app/rag/pipelines/langgraph.py:1018` `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC`: static avoidance; declarations validated, consumers untouched.

## R4: commander decision

RERANKER_API_TIMEOUT_SEC remains unchanged. base.py:162 stores the meaningful constructor timeout; factory.py:98/141 accepts an instance override; async base.py:243 uses self.timeout. Sync base.py:696 gives the global setting precedence. Commander must choose consistency/precedence before removing that chain.

## R2/R3/R5

VLM_CORRECTION_MAX_PAGES uses declared 2 instead of consumer 3. RERANKER_API_MAX_CONCURRENCY uses declared 4 instead of consumer 1. Preview zero returns unlimited text, not disabled preview; now rejected. BM25 zero can still append a whole term; now rejected. No zero-unlimited contract retained for the 54 numeric fields. URL_INGEST_MAX_REDIRECTS=0 continues to forbid all redirect hops (test_settings_api_defaults.py).

Searched 813 tracked deployment/docs/test files. No zero/negative deployment values found for the initial49 fields. Historical zero tests: SCIM cap monkeypatch and password model_copy; replaced with positive17 consumption and length1/7 support. Root/lifetime additional fields have no known invalid deployment assignments. Existing .env zero settings outside these fields remain untouched.

## Evidence

Declaration red47failed/1passed; extra3fields red3failed/48passed; runtime/roots red6failed/2passed. New declaration tests and affected existing modules are verified together. Backups and previews under %TEMP%/mimirq-resource-* and %TEMP%/mimirq-runtime-*.
