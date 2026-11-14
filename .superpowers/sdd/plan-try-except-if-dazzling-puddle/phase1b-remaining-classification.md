# Phase1B 后续逐批定性

原始定位、hash、AST对比及测试输出在仓库外证据目录；这里仅记录裁决。

## api

| 原位置 | 字段 | 类型 | 裁决 | 理由 |
|---|---|---|---|---|
| `app/api/dependencies/auth.py:86` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/schemas/chat.py:80` | `RETRIEVAL_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/api/schemas/chat.py:81` | `SIMILARITY_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/api/schemas/chat.py:89` | `RERANKER_TOP_N` | `int` | direct | declared non-Optional default owns the value |
| `app/api/schemas/chat.py:82` | `RERANKER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/api/schemas/chat.py:97` | `CHAT_DEFAULT_RETRIEVAL_PROFILE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/utils/document_pipeline_input.py:21` | `PIPELINE_FORM_JSON_MAX_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/utils/pipeline_options.py:40` | `PIPELINE_FORM_JSON_MAX_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/utils/url_ingest.py:171` | `URL_INGEST_ALLOWED_PORTS` | `str` | direct | declared non-Optional default owns the value |
| `app/api/utils/url_ingest.py:340` | `URL_INGEST_MAX_REDIRECTS` | `int` | direct | zero means no redirect hops; existing [0,20] clamp retained |
| `app/api/utils/url_ingest.py:165` | `URL_INGEST_ALLOWED_HOSTS` | `str` | direct | declared non-Optional default owns the value |
| `app/api/utils/url_ingest.py:325` | `URL_INGEST_MAX_BYTES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/utils/url_ingest.py:327` | `MAX_FILE_SIZE` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:107` | `GOVERNANCE_SECRETS_MASK` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/dataset_tables.py:109` | `GOVERNANCE_PII_MASK` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/dataset_tables.py:474` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/dataset_tables.py:561` | `TABLE_SEM_FILTER_MAX_COLS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1019` | `TABLE_QUERY_MAX_ROWS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1020` | `TABLE_QUERY_MAX_COLS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1101` | `TABLE_QUERY_MAX_ROWS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1231` | `TABLE_QUERY_MAX_ROWS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:557` | `TABLE_LOTUS_MAX_ROWS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:558` | `TABLE_SEM_FILTER_MAX_IN_ROWS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1102` | `TABLE_QUERY_MAX_ROWS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1232` | `TABLE_QUERY_MAX_ROWS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:709` | `TABLE_QUERY_MAX_COLS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:710` | `TABLE_QUERY_MAX_BYTES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:968` | `TABLE_QUERY_MAX_COLS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:969` | `TABLE_QUERY_MAX_BYTES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1029` | `TABLE_QUERY_MAX_BYTES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1128` | `TABLE_QUERY_MAX_COLS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1129` | `TABLE_QUERY_MAX_BYTES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:473` | `LLM_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/dataset_tables.py:551` | `LLM_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/dataset_tables.py:967` | `TABLE_QUERY_MAX_ROWS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1027` | `TABLE_QUERY_MAX_ROWS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:1028` | `TABLE_QUERY_MAX_COLS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/dataset_tables.py:106` | `GOVERNANCE_SECRETS_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/dataset_tables.py:108` | `GOVERNANCE_PII_MODE` | `Literal['mask', 'token']` | direct | declared non-Optional default owns the value |
| `app/api/v1/datasets.py:1881` | `UPLOAD_DIR` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/datasets.py:3211` | `VECTOR_BACKEND` | `Literal['milvus', 'memory', 'qdrant', 'pgvector']` | direct | declared non-Optional default owns the value |
| `app/api/v1/datasets.py:1868` | `TABLE_STORE_DIR` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/dify_support/external_api.py:924` | `DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/dify_support/external_api.py:935` | `DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/dify_support/external_api.py:932` | `TENANT_HEADER` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_assets.py:162` | `ASSET_CACHE_MAX_AGE_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_chunk_preview.py:1031` | `PREVIEW_PARSE_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_chunk_preview.py:1032` | `PREVIEW_PARSE_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_chunk_preview.py:1033` | `PREVIEW_PARSE_CACHE_MAX_DOC_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_chunk_preview.py:1625` | `PREVIEW_PARSE_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_chunk_preview.py:1626` | `PREVIEW_PARSE_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_chunk_preview.py:572` | `CHUNK_MIN_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_chunk_preview.py:1034` | `PREVIEW_PARSE_CACHE_VERSION` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_chunk_preview.py:1627` | `PREVIEW_PARSE_CACHE_VERSION` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_chunk_preview.py:1010` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/document_chunk_preview.py:1140` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/document_content.py:75` | `UPLOAD_DIR` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/document_preview.py:146` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/evidence.py:952` | `METRICS_LOG_PATH` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/evidence_capsules.py:59` | `EVIDENCE_CAPSULE_STORE_DIR` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:42` | `READY_CACHE_TTL_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:144` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/health.py:73` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/health.py:115` | `REDIS_URL` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:116` | `MILVUS_HOST` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:117` | `MILVUS_PORT` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:118` | `MINIO_ENDPOINT` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:119` | `OBJECT_STORAGE_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:120` | `OBJECT_STORAGE_ENDPOINT` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:121` | `OBJECT_STORAGE_BUCKET_NAME` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:122` | `DATA_REGION` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:123` | `OBJECT_STORAGE_REGION_PROFILES` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:148` | `VECTOR_BACKEND` | `Literal['milvus', 'memory', 'qdrant', 'pgvector']` | direct | declared non-Optional default owns the value |
| `app/api/v1/health.py:103` | `VECTOR_BACKEND` | `Literal['milvus', 'memory', 'qdrant', 'pgvector']` | direct | declared non-Optional default owns the value |
| `app/api/v1/industry_rules.py:50` | `DEFAULT_TENANT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1582` | `DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:4370` | `DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6658` | `DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:742` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/integrations_dify.py:859` | `DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:913` | `CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1042` | `RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1148` | `DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1149` | `DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1150` | `DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1152` | `DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1153` | `DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1155` | `DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1156` | `DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1157` | `DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1158` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1159` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1160` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/integrations_dify.py:1161` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/integrations_dify.py:1164` | `RERANKER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1165` | `RERANKER_MODEL` | `str | None` | optional | Optional: only None chooses the fallback; explicit false/empty values preserved |
| `app/api/v1/integrations_dify.py:1166` | `RERANKER_TOP_N` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1169` | `DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_SCAN` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1170` | `DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1181` | `DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1182` | `DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUBQUERY_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1187` | `DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1190` | `DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1191` | `DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1413` | `DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1558` | `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:3328` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/integrations_dify.py:4367` | `DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6025` | `DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6029` | `DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6037` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/integrations_dify.py:6126` | `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6130` | `DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6138` | `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC` | `float` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/integrations_dify.py:6146` | `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6638` | `DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6639` | `DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:7503` | `DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:1542` | `DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:2240` | `DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_MAX_SUBQUERIES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:3075` | `DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:3076` | `DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:3077` | `DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:4986` | `DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_RECORDS` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/api/v1/integrations_dify.py:5832` | `DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_MAX_SCAN` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6109` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/integrations_dify.py:6120` | `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_QUERY` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6204` | `DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:6047` | `RERANKER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:3322` | `RERANKER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:7136` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/integrations_dify.py:7141` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/lineage.py:84` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/metrics.py:45` | `METRICS_BEARER_TOKEN` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/observability.py:124` | `QUERYSET_HEALTH_HISTORY_PATH` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/observability.py:790` | `QUERYSET_HEALTH_HISTORY_PATH` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:1135` | `PARSE_FALLBACK_MIN_CONTENT_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:1136` | `PARSE_FALLBACK_MIN_PARSE_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:1137` | `PARSE_FALLBACK_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:491` | `PARSE_COMPETITION_MATRIX_WEIGHTS_JSON` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:514` | `MAGIC_PDF_CLI` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:530` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/parsing.py:887` | `MAX_FILE_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:981` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/parsing.py:1288` | `VLM_CORRECTION_API_URL` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:1289` | `VLM_CORRECTION_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/parsing.py:1290` | `VLM_CORRECTION_MAX_PAGES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/parsing.py:1291` | `VLM_CORRECTION_MAX_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/parsing.py:1293` | `VLM_CORRECTION_MIN_TABLE_QUALITY` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:1494` | `PARSE_FALLBACK_MIN_CONTENT_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:1498` | `PARSE_FALLBACK_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:1796` | `PARSE_FALLBACK_MIN_CONTENT_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:1081` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/parsing.py:1314` | `PARSE_FALLBACK_MIN_CONTENT_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:535` | `SILICONFLOW_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:540` | `QIANFAN_OCR_API_URL` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:545` | `ETL4LLM_API_URL` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:555` | `DOCLING_API_URL` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/parsing.py:1363` | `IMAGE_OCR_MAX_IMAGES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/parsing.py:1364` | `IMAGE_OCR_MAX_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/pipeline.py:601` | `DEFAULT_PARSER_BACKEND` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline.py:602` | `DEFAULT_CHUNK_STRATEGY` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline.py:1293` | `GOVERNANCE_REGEX_TIMEOUT_MS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/pipeline.py:1054` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/pipeline.py:1202` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/pipeline_support/capabilities.py:54` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/pipeline_support/capabilities.py:298` | `VISION_LLM_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline_support/capabilities.py:62` | `SILICONFLOW_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline_support/capabilities.py:81` | `TEXTIN_API_URL` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline_support/capabilities.py:82` | `TEXTIN_APP_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline_support/capabilities.py:83` | `TEXTIN_SECRET_CODE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline_support/capabilities.py:145` | `MAGIC_PDF_CLI` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline_support/capabilities.py:297` | `LLM_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline_support/ingestion_preview.py:39` | `DEFAULT_CHUNK_STRATEGY` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/pipeline_support/ingestion_preview.py:38` | `DEFAULT_PARSER_BACKEND` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/rag.py:547` | `RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/api/v1/rag.py:426` | `EVIDENCE_ITERATIVE_RETRIEVE_MAX_PASSES` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/rag.py:449` | `EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_PROFILE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/rag.py:453` | `EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:53` | `VECTOR_BACKEND` | `Literal['milvus', 'memory', 'qdrant', 'pgvector']` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:54` | `RETRIEVAL_FUSION_STRATEGY` | `Literal['linear', 'rrf', 'budgeted_rrf']` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:55` | `RERANKER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:63` | `HIERARCHY_RECALL_FAMILY_AGGREGATION` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:65` | `HIERARCHY_RECALL_PARENT_DEPTH` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:66` | `HIERARCHY_RECALL_SIBLING_WINDOW` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:67` | `HIERARCHY_RECALL_OVERFETCH_FACTOR` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:93` | `HIERARCHY_RECALL_PARENT_DEPTH` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:98` | `HIERARCHY_RECALL_SIBLING_WINDOW` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:103` | `HIERARCHY_RECALL_OVERFETCH_FACTOR` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/retrieval_config_hash.py:83` | `HIERARCHY_RECALL_FAMILY_AGGREGATION` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/scim.py:200` | `SCIM_PAGE_SIZE_MAX` | `int` | decision | 审查恢复：0会取消分页上限，原有200上限暂保留，等待总指挥裁决 |
| `app/api/v1/scim.py:297` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/settings.py:1703` | `MAGIC_PDF_CLI` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:1733` | `PANDOC_CLI` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:1734` | `LIBREOFFICE_CLI` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:1877` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/settings.py:843` | `MINIO_BUCKET_NAME` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:858` | `RERANKER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:859` | `RERANKER_TOP_N` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:889` | `ETL4LLM_TIMEOUT_SEC` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/settings.py:890` | `ETL4LLM_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:898` | `MARKER_TIMEOUT_SEC` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/settings.py:903` | `DOCLING_REQUEST_TIMEOUT_SEC` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/settings.py:904` | `DOCLING_HEALTH_TIMEOUT_SEC` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/settings.py:910` | `PADDLE_VL_TIMEOUT_SEC` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/settings.py:911` | `PADDLE_VL_PIPELINE_VERSION` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:912` | `PADDLE_VL_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:915` | `TEXTIN_API_URL` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:918` | `TEXTIN_TIMEOUT_SEC` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/settings.py:919` | `TEXTIN_PARSE_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:920` | `TEXTIN_TABLE_FLAVOR` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:923` | `TEXTIN_GET_IMAGE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:924` | `TEXTIN_DPI` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:929` | `MAGIC_PDF_REQUEST_TIMEOUT_SEC` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/settings.py:930` | `MAGIC_PDF_MAX_CONCURRENT_JOBS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:931` | `MAGIC_PDF_CLI` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:932` | `MAGIC_PDF_METHOD` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:935` | `MAGIC_PDF_TIMEOUT_SEC` | `int` | direct | observation/signature only; enforcement policy unchanged here |
| `app/api/v1/settings.py:937` | `MAGIC_PDF_DEVICE_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:971` | `DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:1841` | `VECTOR_BACKEND` | `Literal['milvus', 'memory', 'qdrant', 'pgvector']` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:969` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/api/v1/settings.py:452` | `IMAGE_APPEND_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:477` | `CHAT_RESPONSE_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:483` | `CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/settings.py:588` | `MAGIC_PDF_REQUEST_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/api/v1/settings.py:592` | `MAGIC_PDF_MAX_CONCURRENT_JOBS` | `int` | direct | declared non-Optional default owns the value |
| `app/api/v1/settings.py:675` | `DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |

## config_validation

| 原位置 | 字段 | 类型 | 裁决 | 理由 |
|---|---|---|---|---|
| `app/core/config_validation.py:268` | `PASSWORD_MIN_LENGTH` | `int` | decision | authentication lifetime/minimum may weaken; commander review required |
| `app/core/config_validation.py:432` | `INITIAL_ADMIN_PASSWORD` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:501` | `DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:503` | `DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:510` | `DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:517` | `DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:532` | `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:539` | `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:546` | `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:553` | `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:560` | `DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:567` | `DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:574` | `DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:581` | `DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:588` | `DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:590` | `DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:596` | `DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:603` | `DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:610` | `DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:617` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:624` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:631` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:638` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:646` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:655` | `DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:663` | `DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:670` | `DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:677` | `DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:684` | `DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:831` | `RETRIEVAL_DEDUP_JACCARD_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:849` | `RETRIEVAL_COMPACT_MIN_TOP_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:856` | `RETRIEVAL_COMPACT_RELATIVE_SCORE_FLOOR` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:866` | `RETRIEVAL_FIELD_AWARE_TITLE_BOOST` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:867` | `RETRIEVAL_FIELD_AWARE_HEADING_BOOST` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:868` | `RETRIEVAL_FIELD_AWARE_MAX_BOOST` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:880` | `RETRIEVAL_CHUNK_TYPE_MATCH_BOOST` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:908` | `RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:915` | `RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:927` | `RETRIEVAL_REBUILD_MAX_CHUNKS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1052` | `SEMANTIC_CACHE_SCORE_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1080` | `EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1117` | `RAG_KG_CHUNK_BOOST_WEIGHT` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1132` | `KG_SEARCH_EXPAND_BUDGET_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1136` | `KG_QUALITY_LOW_CONFIDENCE_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1160` | `KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1184` | `KG_SEARCH_SERVING_MIN_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1203` | `TABLE_TAG_AMBIGUITY_SCORE_GAP` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1206` | `TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1214` | `TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1222` | `TABLE_TAG_COST_FANOUT_RATIO_ALERT` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1225` | `TABLE_TAG_COST_SELECTIVITY_MIN` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1228` | `TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1418` | `RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1442` | `RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1455` | `RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1457` | `RETRIEVAL_PARSE_QUALITY_ALERT_RATIO` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1466` | `RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1494` | `RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1564` | `RAG_EVAL_GATE_FAITHFULNESS_MIN` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1570` | `RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1576` | `RAG_EVAL_GATE_CONTEXT_PRECISION_MIN` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:367` | `source chain` | `—` | retain | Pydantic introspection property, not a declared configuration field |
| `app/core/config_validation.py:393` | `CORS_ORIGINS` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:821` | `RETRIEVAL_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:830` | `RETRIEVAL_RRF_K` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:838` | `RETRIEVAL_DEDUP_MAX_COMPARE` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:840` | `RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:842` | `RETRIEVAL_NEAR_DEDUP_MAX_COMPARE` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:843` | `RETRIEVAL_MAX_CHUNKS_PER_DOC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:845` | `RETRIEVAL_MAX_CHUNKS_PER_RECORD_IDENTITY` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:863` | `RETRIEVAL_COMPACT_MIN_RECORDS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:864` | `RETRIEVAL_MAX_CHUNKS_PER_PAGE` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:865` | `RETRIEVAL_MIN_DISTINCT_DOCS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:883` | `RETRIEVAL_QUERY_PARALLELISM` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:887` | `RETRIEVAL_OVERFETCH_MULTIPLIER` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:896` | `HIERARCHY_RECALL_PARENT_DEPTH` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:899` | `HIERARCHY_RECALL_SIBLING_WINDOW` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:902` | `HIERARCHY_RECALL_OVERFETCH_FACTOR` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:907` | `RETRIEVAL_OVERFETCH_MAX_K` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:923` | `RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:925` | `MILVUS_EXPR_MAX_DOC_IDS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:931` | `BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:934` | `BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:954` | `EMBEDDING_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:961` | `EMBEDDING_API_TIMEOUT_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:962` | `EMBEDDING_API_BATCH_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:963` | `EMBEDDING_API_MAX_CONCURRENCY` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:964` | `EMBEDDING_API_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:966` | `EMBEDDING_API_RETRY_BACKOFF_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:969` | `EMBEDDING_API_RETRY_JITTER_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1018` | `EMBEDDING_MIGRATION_PROGRESS_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1023` | `CHAT_RESPONSE_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1025` | `CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1028` | `CHAT_RESPONSE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1033` | `RETRIEVAL_CANDIDATE_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1036` | `RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1040` | `RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1050` | `SEMANTIC_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1051` | `SEMANTIC_CACHE_MAX_VALUE_BYTES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1055` | `DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1059` | `RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1062` | `SEMANTIC_CACHE_SEARCH_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1075` | `EVIDENCE_POST_RERANK_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1078` | `EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1100` | `RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1103` | `RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1106` | `RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1115` | `RAG_KG_CHUNK_INJECTION_MAX_CHUNKS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1120` | `RAG_KG_CHUNK_BOOST_MAX_PROMOTED` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1124` | `KG_SEARCH_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1125` | `KG_SEARCH_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1127` | `KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1135` | `KG_SEARCH_LATENCY_SLO_MS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1139` | `KG_QUALITY_RELATION_EDGES_LIMIT` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1147` | `KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1150` | `KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1153` | `KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1158` | `KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1169` | `KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1172` | `KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1177` | `KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1183` | `KG_EXTRACT_LONG_DOC_MIN_CHUNKS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1188` | `KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1193` | `VECTOR_WRITE_BATCH_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1194` | `VECTOR_WRITE_BATCH_MAX_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1196` | `DB_CATALOG_ROW_SYNC_MAX_TABLES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1198` | `DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1200` | `DB_CATALOG_ROW_SYNC_MAX_COLS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1201` | `TABLE_QUERY_MAX_JOIN_TABLES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1202` | `TABLE_TAG_PLAN_CANDIDATES_TOP_N` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1232` | `RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1258` | `CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1260` | `CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1270` | `TENANT_DOC_QUOTA_LIMIT` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1271` | `TENANT_STORAGE_QUOTA_LIMIT_BYTES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1272` | `TENANT_EMBED_CHAR_QUOTA_LIMIT` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1274` | `TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1285` | `PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1290` | `PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1325` | `RETRIEVAL_CONTRACT_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1360` | `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1378` | `RETRIEVAL_HARD_FALLBACK_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1388` | `RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1397` | `RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1400` | `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1403` | `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1406` | `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1411` | `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1416` | `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1430` | `RAG_CONTEXT_DENOISE_MAX_TOTAL_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1433` | `CONTEXTUAL_RETRIEVAL_LLM_MAX_INPUT_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1438` | `CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1514` | `SPARSE_RETRIEVAL_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:193` | `INITIAL_REGISTRATION_TOKEN` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:203` | `JWT_TENANT_CLAIM` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:216` | `JWT_TENANT_CLAIM` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:224` | `JWT_ISSUER` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:228` | `JWT_JWKS_URLS` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:277` | `SCIM_IP_ALLOWLIST_CIDRS` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:390` | `source chain` | `—` | retain | Pydantic introspection property, not a declared configuration field |
| `app/core/config_validation.py:430` | `INITIAL_ADMIN_EMAIL` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:431` | `INITIAL_ADMIN_USERNAME` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:433` | `INITIAL_ADMIN_PASSWORD_FILE` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:450` | `SCIM_BEARER_TOKEN` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:456` | `SCIM_TENANT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:486` | `DIFY_EXTERNAL_KNOWLEDGE_API_KEYS` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:493` | `DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:694` | `AUTH_MODE` | `Literal['jwt', 'header']` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:695` | `JWT_ISSUER` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:696` | `JWT_JWKS_URLS` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:956` | `EMBEDDING_CACHE_PREFIX` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1013` | `EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1045` | `RETRIEVAL_CANDIDATE_CACHE_PREFIX` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1064` | `SEMANTIC_CACHE_REDIS_PREFIX` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1069` | `SEMANTIC_CACHE_COLLECTION_NAME` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1094` | `EVIDENCE_POST_RERANK_CACHE_PREFIX` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1110` | `RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1239` | `EVIDENCE_CAPSULE_SIGNING_KEY_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1450` | `RAG_INTENT_ROUTER_MODEL_PATH` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:344` | `SAML_PROVIDERS_JSON` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:355` | `ALLOWED_HOSTS` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:729` | `MINIO_ACCESS_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:730` | `MINIO_SECRET_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:779` | `OBJECT_STORAGE_ENDPOINT` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:780` | `OBJECT_STORAGE_ACCESS_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:781` | `OBJECT_STORAGE_SECRET_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:782` | `OBJECT_STORAGE_BUCKET_NAME` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:980` | `EMBEDDING_SHADOW_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:987` | `MILVUS_SHADOW_COLLECTION_NAME` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:993` | `MILVUS_COLLECTION_NAME` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1000` | `EMBEDDING_SHADOW_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1005` | `EMBEDDING_SHADOW_API_BASE` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1010` | `EMBEDDING_SHADOW_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1245` | `EVIDENCE_CAPSULE_SIGNING_SECRET` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1363` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1582` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/core/config_validation.py:347` | `REDIS_URL` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:464` | `DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:702` | `ALGORITHM` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:773` | `DATA_REGION` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:888` | `HIERARCHY_RECALL_FAMILY_AGGREGATION` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1140` | `KG_SEARCH_QUERY_MODE_DEFAULT` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1317` | `CHAT_DEFAULT_RETRIEVAL_PROFILE` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1333` | `RAG_CLAIM_VERIFIER_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1340` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:333` | `REDIS_URL` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:1483` | `source chain` | `—` | retain | logical OR / configuration-source precedence, not a literal default |
| `app/core/config_validation.py:1180` | `KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY` | `str` | direct | declared non-Optional default owns the value |
| `app/core/config_validation.py:976` | `VECTOR_BACKEND` | `Literal['milvus', 'memory', 'qdrant', 'pgvector']` | direct | declared non-Optional default owns the value |

## rag_kg_engine

| 原位置 | 字段 | 类型 | 裁决 | 理由 |
|---|---|---|---|---|
| `app/rag/engine_support/doc_utils.py:105` | `RETRIEVAL_RRF_K` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:100` | `LLM_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:109` | `LLM_TEMPERATURE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:110` | `LLM_STRUCTURED_TEMPERATURE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:194` | `ADAPTIVE_RETRIEVAL_SIMPLE_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:195` | `ADAPTIVE_RETRIEVAL_COMPLEX_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:48` | `LLM_MOCK_RESPONSE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:164` | `MODEL_COMPLEXITY_THRESHOLD` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:87` | `LLM_API_BASE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:199` | `ADAPTIVE_RETRIEVAL_SIMPLE_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:205` | `ADAPTIVE_RETRIEVAL_COMPLEX_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/llm_routing.py:209` | `ADAPTIVE_RETRIEVAL_COMPLEX_MQ_COUNT` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_corrective.py:362` | `RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_corrective.py:152` | `MULTI_QUERY_DIVERSIFY_BUDGET` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_corrective.py:361` | `RAG_ABSTAIN_MIN_CITATIONS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:183` | `RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:644` | `RAG_CONTEXT_MAX_CHARS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:645` | `RAG_CONTEXT_MAX_TOTAL_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:646` | `RAG_CONTEXT_MAX_TOKENS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:647` | `RAG_CONTEXT_MAX_TOTAL_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:182` | `RAG_ABSTAIN_MIN_CITATIONS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:818` | `RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:819` | `RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:291` | `FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/engine_support/standard_stream_evidence.py:676` | `EVIDENCE_POST_RERANK_PIPELINE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:745` | `VECTOR_BACKEND` | `Literal['milvus', 'memory', 'qdrant', 'pgvector']` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:749` | `SPARSE_RETRIEVAL_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:752` | `COLBERT_RETRIEVAL_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:754` | `COLBERT_RETRIEVAL_MAX_DOCS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:756` | `RAG_PARENT_CHILD_AUTO_MERGE_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:766` | `EVIDENCE_POST_RERANK_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:767` | `EVIDENCE_POST_RERANK_TOP_N` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:813` | `RAG_CONTEXT_CLIFF_THRESHOLD_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:35` | `RAG_TEMPORAL_INTENT_MAX_DOCS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/engine_support/standard_stream_evidence.py:301` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:302` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:303` | `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/engine_support/standard_stream_evidence.py:446` | `RAG_ABSTAIN_MIN_CITATIONS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:447` | `RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:539` | `RAG_CONTEXT_MAX_KG_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:59` | `RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:60` | `RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:209` | `RAG_OUT_OF_SCOPE_VECTOR_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:210` | `RAG_OUT_OF_SCOPE_HYDE_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:297` | `FAITHFULNESS_SCORE_MAX_CLAIMS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:737` | `COLBERT_RERANK_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_evidence.py:298` | `RAG_CLAIM_VERIFIER_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:87` | `RETRIEVAL_MAX_CHUNKS_PER_DOC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:88` | `RETRIEVAL_MIN_DISTINCT_DOCS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:147` | `RAG_CONTEXT_MAX_TOTAL_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:148` | `RAG_CONTEXT_MAX_TOTAL_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:149` | `RAG_CONTEXT_MAX_CHARS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:150` | `RAG_CONTEXT_MAX_TOKENS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:162` | `EMBEDDING_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:163` | `EMBEDDING_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:184` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:185` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:211` | `RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_finalization.py:216` | `RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:22` | `RAG_CLAIM_CHECK_MAX_CLAIMS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:155` | `VISION_RAG_GENERATION_MAX_IMAGES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/engine_support/standard_stream_generation.py:156` | `VISION_RAG_GENERATION_MAX_IMAGE_BYTES` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/engine_support/standard_stream_generation.py:311` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:312` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:313` | `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/engine_support/standard_stream_generation.py:410` | `FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/engine_support/standard_stream_generation.py:628` | `EMBEDDING_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:629` | `EMBEDDING_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:640` | `VECTOR_BACKEND` | `Literal['milvus', 'memory', 'qdrant', 'pgvector']` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:256` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:257` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:258` | `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/engine_support/standard_stream_generation.py:420` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:421` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:422` | `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/engine_support/standard_stream_generation.py:23` | `RAG_CLAIM_VERIFIER_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:385` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:386` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:387` | `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/engine_support/standard_stream_generation.py:416` | `FAITHFULNESS_SCORE_MAX_CLAIMS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:550` | `SENTENCE_CITATIONS_INLINE_MAX_ITEMS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:551` | `SENTENCE_CITATIONS_INLINE_MAX_EVIDENCE_PER_CLAIM` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:437` | `SENTENCE_CITATIONS_INLINE_STYLE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:487` | `SENTENCE_CITATIONS_INLINE_MAX_ITEMS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_generation.py:491` | `SENTENCE_CITATIONS_INLINE_MAX_EVIDENCE_PER_CLAIM` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_query.py:88` | `RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_query.py:87` | `RAG_CORRECTIVE_MAX_ATTEMPTS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_query.py:105` | `RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_query.py:106` | `MULTI_QUERY_COUNT_CAP` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_query.py:90` | `RAG_CORRECTIVE_SECOND_PASS_PROFILE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_retrieval.py:44` | `RETRIEVAL_QUERY_PARALLELISM` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_retrieval.py:150` | `MULTI_QUERY_DIVERSIFY_BUDGET` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_retrieval.py:258` | `RAG_KG_CHUNK_INJECTION_MAX_CHUNKS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_retrieval.py:263` | `RAG_KG_CHUNK_INJECTION_MAX_CHUNKS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_retrieval.py:419` | `RAG_KG_CHUNK_BOOST_WEIGHT` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_retrieval.py:424` | `RAG_KG_CHUNK_BOOST_MAX_PROMOTED` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine_support/standard_stream_retrieval.py:532` | `LLM_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/kg/api/routes_support/extraction.py:82` | `KG_EXTRACT_PROMPT_TEMPLATE_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/kg/api/routes_support/extraction.py:112` | `KG_EXTRACT_PROMPT_TEMPLATE_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/kg/api/routes_support/extraction.py:117` | `KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/kg/api/routes_support/extraction.py:229` | `KG_EXTRACTION_BACKEND` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/kg/api/routes_support/projection.py:239` | `KG_ENTITY_LINK_MAX_ENTITIES_PER_EVENT` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/api/routes_support/projection.py:469` | `KG_API_MAX_DOCUMENT_IDS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:994` | `KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:2379` | `KG_RELATION_ALIAS_MAX_CANDIDATES_PER_CHUNK` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/extraction/extractor.py:2469` | `KG_RELATION_MAX_RELATIONS_PER_CHUNK` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/extraction/extractor.py:4191` | `KG_EXTRACT_CHUNK_TIMEOUT_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:4193` | `KG_EXTRACT_CHUNK_RETRY_BACKOFF_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:3851` | `KG_SKILL_MAX_SKILLS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:4143` | `KG_EXTRACT_LONG_DOC_MIN_CHUNKS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:4189` | `KG_EXTRACT_MAX_CONCURRENCY` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:2465` | `KG_RELATION_ALLOWED_PREDICATES` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:4215` | `KG_EXTRACT_MAX_EVENTS_PER_CHUNK` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/kg/extraction/extractor.py:4216` | `KG_EXTRACT_MAX_ENTITIES_PER_EVENT` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/kg/extraction/extractor.py:4217` | `KG_EXTRACT_EMBED_BATCH_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:4220` | `KG_EXTRACT_MIN_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:4221` | `KG_EXTRACT_CHUNK_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:996` | `KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/extractor.py:4219` | `KG_EXTRACT_CONTEXT_WINDOW_CHUNKS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/extraction/processor.py:27` | `KG_EXTRACT_CONTEXT_MAX_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/models.py:22` | `DEFAULT_TENANT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:431` | `KG_SEARCH_QUERY_MODE_DEFAULT` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:406` | `KG_SEARCH_MULTI_DATASET_MAX_CONCURRENCY` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/kg/pipeline.py:458` | `KG_SEARCH_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:459` | `KG_SEARCH_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:473` | `KG_COMMUNITY_MAX_EVENTS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:474` | `KG_COMMUNITY_MAX_ENTITIES_PER_EVENT` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:475` | `KG_COMMUNITY_MIN_EDGE_WEIGHT` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:476` | `KG_SEARCH_RELATION_MIN_CONFIDENCE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:477` | `KG_SEARCH_RELATION_MAX_EDGES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:478` | `KG_SEARCH_RELATION_MAX_NEIGHBORS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:479` | `KG_SEARCH_MAX_RERANK_CANDIDATES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:480` | `KG_SEARCH_EXPAND_BUDGET_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:483` | `KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:486` | `KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:487` | `KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:488` | `KG_SEARCH_SERVING_MIN_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/pipeline.py:489` | `KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/quality/kg_completeness_scorer.py:252` | `KG_QUALITY_LOW_CONFIDENCE_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/repository.py:1078` | `KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS` | `int` | direct | zero rejected by existing positive configuration validation |
| `app/rag/kg/search/expand.py:227` | `KG_SEARCH_RELATION_MIN_CONFIDENCE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/expand.py:229` | `KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/expand.py:230` | `KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/expand.py:231` | `KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/expand.py:221` | `KG_SEARCH_RELATION_MAX_NEIGHBORS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/expand.py:228` | `KG_SEARCH_RELATION_MAX_EDGES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/expand.py:517` | `KG_SEARCH_MAX_RERANK_CANDIDATES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/query_mode.py:101` | `KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/query_mode.py:98` | `KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS` | `int` | direct | zero rejected by existing positive configuration validation |
| `app/rag/kg/search/query_mode.py:128` | `KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/query_mode.py:145` | `KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/query_mode.py:122` | `KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS` | `int` | direct | zero rejected by existing positive configuration validation |
| `app/rag/kg/search/ranking/pagerank.py:187` | `KG_SEARCH_EXACT_PHRASE_RERANK_BOOST` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/ranking/rrf.py:188` | `KG_SEARCH_EXACT_PHRASE_RERANK_BOOST` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:883` | `KG_SEARCH_RELATION_MIN_CONFIDENCE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:885` | `KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:886` | `KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:887` | `KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:228` | `KG_SEARCH_MAX_RERANK_CANDIDATES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:233` | `KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:484` | `KG_SEARCH_RELATION_MIN_CONFIDENCE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:877` | `KG_SEARCH_RELATION_MAX_NEIGHBORS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:426` | `KG_SEARCH_GRAPH_EMBEDDINGS_MIN_SIMILARITY` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:884` | `KG_SEARCH_RELATION_MAX_EDGES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:1115` | `KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:1116` | `KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:1117` | `KG_SEARCH_SERVING_MIN_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:422` | `KG_SEARCH_GRAPH_EMBEDDINGS_MAX_EVENTS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/search/recall.py:423` | `KG_SEARCH_GRAPH_EMBEDDINGS_MAX_ENTITIES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/search/recall.py:424` | `KG_SEARCH_GRAPH_EMBEDDINGS_MAX_RELATIONS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/search/recall.py:425` | `KG_SEARCH_GRAPH_EMBEDDINGS_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:650` | `KG_SEARCH_GRAPH_EMBEDDINGS_DIM` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:651` | `KG_SEARCH_GRAPH_EMBEDDINGS_NUM_WALKS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:652` | `KG_SEARCH_GRAPH_EMBEDDINGS_WALK_LENGTH` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:653` | `KG_SEARCH_GRAPH_EMBEDDINGS_WINDOW_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/recall.py:654` | `KG_SEARCH_GRAPH_EMBEDDINGS_SEED` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/relation_scoring.py:118` | `KG_SEARCH_RELATION_MENTION_EVIDENCE_MULTIPLIER` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/searcher.py:469` | `KG_SEARCH_TIMEOUT_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/searcher.py:298` | `KG_SEARCH_LATENCY_SLO_MS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/searcher.py:400` | `KG_COMMUNITY_MAX_EVENTS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/search/searcher.py:502` | `KG_SEARCH_EXPAND_BUDGET_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/searcher.py:112` | `KG_LAZY_COMMUNITY_SUMMARY_TOP_N` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/searcher.py:113` | `KG_LAZY_COMMUNITY_SUMMARY_MAX_TOKENS` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/kg/search/searcher.py:114` | `KG_LAZY_COMMUNITY_SUMMARY_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/searcher.py:115` | `KG_LAZY_COMMUNITY_SUMMARY_CACHE_MAX_ENTRIES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/search/searcher.py:410` | `KG_COMMUNITY_MAX_ENTITIES_PER_EVENT` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/search/searcher.py:411` | `KG_COMMUNITY_MIN_EDGE_WEIGHT` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/searcher.py:412` | `KG_COMMUNITY_LABEL_PROPAGATION_ITERS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/searcher.py:413` | `KG_COMMUNITY_MAX_COMMUNITIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/searcher.py:414` | `KG_COMMUNITY_MAX_ENTITIES_PER_COMMUNITY` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/search/searcher.py:415` | `KG_COMMUNITY_MAX_EVENTS_PER_COMMUNITY` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/search/searcher.py:416` | `KG_COMMUNITY_GLOBAL_SUMMARY_MAX_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/kg/search/tracker.py:18` | `KG_SEARCH_NODE_TEXT_MAX_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/kg/search/tracker.py:72` | `KG_SEARCH_MAX_CLUES` | `int` | direct | declared non-Optional default owns the value |

## rag_other

| 原位置 | 字段 | 类型 | 裁决 | 理由 |
|---|---|---|---|---|
| `app/rag/agents/multi_agent.py:456` | `RAG_AGENTIC_COMPLEXITY_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/agents/multi_agent.py:458` | `RAG_MULTI_AGENT_MAX_SUB_AGENTS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/agents/multi_agent.py:122` | `QUERY_DECOMPOSITION_TEMPERATURE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/agents/rag_agent.py:320` | `RAG_AGENTIC_REFLECT_TOP_SCORE_MIN` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/agents/rag_agent.py:876` | `RAG_AGENTIC_COMPLEXITY_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/agents/rag_agent.py:319` | `RAG_AGENTIC_REFLECT_TOP_CITATIONS_MIN` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/agents/rag_agent.py:751` | `RAG_SELF_RAG_ENABLED` | `bool` | retain | logical OR / configuration-source precedence, not a static default |
| `app/rag/agents/rag_agent.py:878` | `RAG_AGENTIC_MAX_RETRIEVE_ROUNDS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/agents/rag_agent.py:271` | `QUERY_DECOMPOSITION_TEMPERATURE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/core/claim_nli_verifier.py:101` | `LLM_API_BASE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/core/claim_nli_verifier.py:104` | `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/core/claim_nli_verifier.py:98` | `LLM_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/core/claim_nli_verifier.py:99` | `LLM_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/core/context_denoise.py:235` | `RAG_CONTEXT_LLM_COMPRESSION_TARGET_RATIO` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/core/evidence_capsule_builder.py:157` | `EVIDENCE_CAPSULE_SIGNING_SECRET` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/core/evidence_capsule_builder.py:236` | `EVIDENCE_CAPSULE_SIGNING_SECRET` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/core/evidence_capsule_builder.py:238` | `EVIDENCE_CAPSULE_SIGNING_KEY_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/core/vision_reader.py:267` | `VISION_LLM_MAX_TOKENS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/core/vision_reader.py:353` | `VISION_LLM_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/core/vision_reader.py:457` | `VISION_LLM_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/core/vision_reader.py:476` | `VISION_RAG_READER_MAX_IMAGES` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/core/vision_reader.py:477` | `VISION_RAG_READER_MAX_IMAGE_BYTES` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/core/vision_reader.py:478` | `VISION_RAG_READER_MAX_OUTPUT_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/embedding/adapter.py:96` | `EMBEDDING_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/embedding/adapter.py:260` | `EMBEDDING_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/embedding/providers/_embedding_http.py:100` | `EMBEDDING_API_RETRY_BACKOFF_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/embedding/providers/_embedding_http.py:101` | `EMBEDDING_API_RETRY_JITTER_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/embedding/providers/_embedding_http.py:109` | `EMBEDDING_API_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/embedding/providers/_embedding_http.py:46` | `EMBEDDING_API_MAX_CONCURRENCY` | `int` | direct | zero rejected by existing positive configuration validation |
| `app/rag/embedding/providers/dashscope.py:69` | `EMBEDDING_API_TIMEOUT_SEC` | `float` | direct | zero rejected by existing positive configuration validation |
| `app/rag/embedding/providers/dashscope.py:96` | `EMBEDDING_API_TIMEOUT_SEC` | `float` | direct | zero rejected by existing positive configuration validation |
| `app/rag/embedding/providers/ollama.py:74` | `EMBEDDING_API_TIMEOUT_SEC` | `float` | direct | zero rejected by existing positive configuration validation |
| `app/rag/embedding/providers/ollama.py:113` | `EMBEDDING_API_TIMEOUT_SEC` | `float` | direct | zero rejected by existing positive configuration validation |
| `app/rag/embedding/providers/ollama.py:105` | `EMBEDDING_API_BATCH_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/embedding/providers/ollama.py:138` | `EMBEDDING_API_BATCH_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/embedding/providers/openai.py:74` | `EMBEDDING_API_TIMEOUT_SEC` | `float` | direct | zero rejected by existing positive configuration validation |
| `app/rag/embedding/providers/openai.py:119` | `EMBEDDING_API_TIMEOUT_SEC` | `float` | direct | zero rejected by existing positive configuration validation |
| `app/rag/embedding/providers/openai.py:66` | `EMBEDDING_API_BATCH_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/embedding/utils.py:106` | `EMBEDDING_API_BASE` | `str` | retain | logical OR / configuration-source precedence, not a static default |
| `app/rag/engine.py:244` | `LLM_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine.py:737` | `LLM_TEMPERATURE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine.py:738` | `LLM_TIMEOUT` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine.py:739` | `LLM_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/engine.py:744` | `LLM_MOCK_RESPONSE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine.py:620` | `RAG_AGENTIC_COMPLEXITY_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/engine.py:729` | `LLM_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine.py:252` | `LLM_MODEL_FAST` | `str | None` | retain | logical OR / configuration-source precedence, not a static default |
| `app/rag/engine.py:257` | `LLM_MODEL_HEAVY` | `str | None` | retain | logical OR / configuration-source precedence, not a static default |
| `app/rag/engine.py:732` | `LLM_API_BASE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine.py:733` | `LLM_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/engine.py:734` | `LLM_MODEL_FAST` | `str | None` | optional | Optional: only None chooses the fallback; explicit false/empty values preserved |
| `app/rag/engine.py:735` | `LLM_MODEL_HEAVY` | `str | None` | optional | Optional: only None chooses the fallback; explicit false/empty values preserved |
| `app/rag/engine.py:742` | `LLM_FALLBACK_MODELS` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/kg_search_diagnostics.py:578` | `KG_EXTRACT_MAX_CONCURRENCY` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/evaluation/poc_runner/png_tasks.py:55` | `DATASET_ANALYSIS_PNG_REDIS_PREFIX` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/poc_runner/png_tasks.py:59` | `DATASET_ANALYSIS_PNG_STALE_AFTER_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/poc_runner/png_tasks.py:64` | `DATASET_ANALYSIS_PNG_TERMINAL_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/poc_runner/png_tasks.py:68` | `DATASET_ANALYSIS_PNG_STALE_AFTER_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/poc_runner/png_tasks.py:72` | `DATASET_ANALYSIS_PNG_RESULT_MAX_BYTES` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/evaluation/ragas.py:329` | `LLM_TIMEOUT` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/evaluation/ragas.py:1022` | `RAGAS_RESPONSE_RELEVANCY_STRICTNESS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/ragas.py:1221` | `EMBEDDING_API_KEY` | `str` | retain | logical OR / configuration-source precedence, not a static default |
| `app/rag/evaluation/ragas.py:1222` | `EMBEDDING_API_BASE` | `str` | retain | logical OR / configuration-source precedence, not a static default |
| `app/rag/evaluation/ragas.py:1448` | `RAGAS_CONVERSATION_WALL_TIMEOUT_SEC` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/evaluation/ragas.py:1216` | `LLM_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/ragas.py:1217` | `LLM_API_BASE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/ragas.py:1910` | `CHAT_TAG_MAX_DOC_IDS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/ragas.py:2063` | `LANGGRAPH_RECURSION_LIMIT` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/evaluation/ragas.py:1040` | `RAGAS_RUN_TIMEOUT_SEC` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/evaluation/ragas.py:1041` | `RAGAS_RUN_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/ragas.py:1042` | `RAGAS_RUN_MAX_WAIT_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/ragas.py:1043` | `RAGAS_RUN_MAX_WORKERS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/evaluation/ragas.py:1611` | `RAGAS_CONVERSATION_WALL_TIMEOUT_SEC` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/evaluation/test_generator.py:68` | `LLM_TIMEOUT` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/llm/factory.py:91` | `LLM_USE_POOLED_ASYNC_HTTP_CLIENT` | `bool` | retain | logical OR / configuration-source precedence, not a static default |
| `app/rag/llm/factory.py:179` | `EMBEDDING_API_BATCH_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/llm/factory.py:180` | `KG_EXTRACT_EMBED_BATCH_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/llm/factory.py:279` | `LLM_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/llm/langchain_chat.py:345` | `LLM_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/llm/prompt_cache.py:46` | `PROMPT_CACHE_MIN_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/middleware/agent_logging.py:99` | `AGENT_LOG_MAX_PREVIEW_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/middleware/tool_logging.py:199` | `TOOL_CALL_LOG_MAX_PREVIEW_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/pipeline_plugins/refs.py:13` | `PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipeline_plugins/registry.py:210` | `PYTHON_PIPELINE_PLUGIN_DIRS` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:180` | `RAG_GRAPH_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:649` | `RETRIEVAL_TOP_K` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1132` | `RAG_CONTEXT_MAX_TOTAL_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1133` | `RAG_CONTEXT_MAX_TOTAL_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1134` | `RAG_CONTEXT_MAX_CHARS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1135` | `RAG_CONTEXT_MAX_TOKENS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1351` | `RAG_CORRECTIVE_MAX_ATTEMPTS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1353` | `RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1361` | `RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:289` | `RAG_CONTEXT_MAX_CHARS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:290` | `RAG_CONTEXT_MAX_TOTAL_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:291` | `RAG_CONTEXT_MAX_TOKENS_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:292` | `RAG_CONTEXT_MAX_TOTAL_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:736` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:737` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:738` | `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/pipelines/langgraph.py:985` | `FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/pipelines/langgraph.py:1055` | `RAG_CONTEXT_EVIDENCE_MAX_SENTENCES_PER_CHUNK` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1060` | `RAG_CONTEXT_EVIDENCE_MIN_SENTENCE_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1148` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1149` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1541` | `LANGGRAPH_RECURSION_LIMIT` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/pipelines/langgraph.py:724` | `RAG_CLAIM_CHECK_MAX_CLAIMS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:906` | `SENTENCE_CITATIONS_INLINE_MAX_ITEMS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:909` | `SENTENCE_CITATIONS_INLINE_MAX_EVIDENCE_PER_CLAIM` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1014` | `RAG_CLAIM_NLI_VERIFIER_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1015` | `RAG_CLAIM_NLI_VERIFIER_MODEL` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1016` | `RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/pipelines/langgraph.py:1362` | `MULTI_QUERY_COUNT_CAP` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1971` | `LANGGRAPH_RECURSION_LIMIT` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/pipelines/langgraph.py:175` | `RAG_GRAPH_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1010` | `FAITHFULNESS_SCORE_MAX_CLAIMS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1125` | `RAG_CONTEXT_CLIFF_THRESHOLD_TOKENS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:709` | `RAG_CLAIM_VERIFIER_MODE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:1357` | `RAG_CORRECTIVE_SECOND_PASS_PROFILE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/pipelines/langgraph.py:857` | `SENTENCE_CITATIONS_INLINE_STYLE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/preprocessing/processor.py:271` | `GOVERNANCE_REGEX_TIMEOUT_MS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/preprocessing/tokenization.py:242` | `BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS` | `int` | direct | zero rejected by existing positive configuration validation |
| `app/rag/preprocessing/tokenization.py:269` | `BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/rerank_result_cache.py:280` | `EVIDENCE_POST_RERANK_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/rerank_result_cache.py:199` | `EVIDENCE_POST_RERANK_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/rerank_result_cache.py:95` | `RERANKER_MODEL` | `str | None` | optional | Optional: only None chooses the fallback; explicit false/empty values preserved |
| `app/rag/rerank_result_cache.py:96` | `RERANKER_API_BASE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/rerank_result_cache.py:202` | `EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/rerank_result_cache.py:88` | `COLBERT_RERANK_EMBED_DIM` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/rerank_result_cache.py:185` | `EVIDENCE_POST_RERANK_CACHE_PREFIX` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/rerank_result_cache.py:247` | `EVIDENCE_POST_RERANK_CACHE_BACKEND` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/rerank_result_cache.py:87` | `COLBERT_RERANK_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:182` | `RERANKER_API_RATE_LIMIT_QPS` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:201` | `RERANKER_API_RATE_LIMIT_QPS` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:698` | `RERANKER_API_TIMEOUT_SEC` | `float` | decision | external request timeout fallback chain requires review |
| `app/rag/reranker/base.py:781` | `RERANKER_API_BATCH_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:785` | `RERANKER_MAX_CHARS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:230` | `RERANKER_API_CIRCUIT_BREAKER_FAILURE_THRESHOLD` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:231` | `RERANKER_API_CIRCUIT_BREAKER_RESET_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:551` | `RERANKER_API_MAX_CONCURRENCY` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/reranker/base.py:552` | `RERANKER_API_RATE_LIMIT_QPS` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:553` | `RERANKER_API_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:621` | `RERANKER_API_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:622` | `RERANKER_API_RETRY_BACKOFF_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:623` | `RERANKER_API_MAX_CONCURRENCY` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/reranker/base.py:699` | `RERANKER_API_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:700` | `RERANKER_API_RETRY_BACKOFF_SEC` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:701` | `RERANKER_API_MAX_CONCURRENCY` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/reranker/base.py:405` | `RERANKER_API_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:510` | `RERANKER_API_MAX_CONCURRENCY` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/reranker/base.py:511` | `RERANKER_API_RATE_LIMIT_QPS` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:512` | `RERANKER_API_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:409` | `RERANKER_API_CACHE_MAX_ENTRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:410` | `RERANKER_API_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:574` | `RERANKER_API_MAX_CONCURRENCY` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/reranker/base.py:575` | `RERANKER_API_RATE_LIMIT_QPS` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/base.py:576` | `RERANKER_API_MAX_RETRIES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/capabilities.py:45` | `COLBERT_RERANK_PROVIDER` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/reranker/llm_based.py:308` | `LLM_MODEL_FAST` | `str | None` | retain | logical OR / configuration-source precedence, not a static default |
| `app/rag/reranker/llm_based.py:452` | `RERANKER_MAX_CHARS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/reranker/llm_based.py:318` | `RERANKER_TEMPERATURE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/retrieval_candidate_cache.py:300` | `RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/retrieval_candidate_cache.py:441` | `RETRIEVAL_CANDIDATE_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/retrieval_candidate_cache.py:525` | `RETRIEVAL_CANDIDATE_CACHE_TTL_SEC` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/retrieval_candidate_cache.py:219` | `RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC` | `float` | direct | zero rejected by existing positive configuration validation |
| `app/rag/retrieval_candidate_cache.py:228` | `RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC` | `float` | direct | zero rejected by existing positive configuration validation |
| `app/rag/retrieval_candidate_cache.py:239` | `RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC` | `float` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/retrieval_candidate_cache.py:114` | `RETRIEVAL_CANDIDATE_CACHE_PREFIX` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/retrieval_candidate_cache.py:233` | `SECRET_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:160` | `HIERARCHY_RECALL_OVERFETCH_FACTOR` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:1030` | `RETRIEVAL_CANDIDATE_CACHE_ENABLED` | `bool` | retain | logical OR / configuration-source precedence, not a static default |
| `app/rag/retriever.py:1193` | `RETRIEVAL_QUERY_MAX_CHARS` | `int` | direct | zero rejected by existing positive configuration validation |
| `app/rag/retriever.py:1807` | `RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:1808` | `RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:1358` | `MILVUS_EXPR_MAX_DOC_IDS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:1809` | `RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:223` | `DEFAULT_TENANT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:389` | `RAG_VECTOR_SHARD_MAX_CONCURRENCY` | `int` | direct | zero rejected by existing positive configuration validation |
| `app/rag/retriever.py:1293` | `RERANK_PROFILE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:1299` | `RETRIEVAL_OVERFETCH_MULTIPLIER` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:1304` | `RETRIEVAL_OVERFETCH_MAX_K` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:786` | `SPARSE_RETRIEVAL_SYNONYMS` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:1222` | `RERANK_PROFILE` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:790` | `SPARSE_RETRIEVAL_SYNONYMS` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/retriever.py:772` | `VECTOR_BACKEND` | `Literal['milvus', 'memory', 'qdrant', 'pgvector']` | direct | declared non-Optional default owns the value |
| `app/rag/safety/input_guard.py:127` | `INPUT_GUARD_WARN_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/safety/input_guard.py:128` | `INPUT_GUARD_SCORE_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/safety/input_guard.py:129` | `INPUT_GUARD_MODE` | `Literal['warn', 'block']` | direct | declared non-Optional default owns the value |
| `app/rag/store/factory.py:35` | `LANGGRAPH_STORE_BACKEND` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/tools/mcp_tools.py:195` | `DEFAULT_TENANT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/tools/mcp_tools.py:436` | `DEFAULT_TENANT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/tools/mcp_tools.py:517` | `DEFAULT_TENANT_ID` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/tools/pre_poc_scanner/settings.py:28` | `PRECHECK_PDF_SCAN_RATIO_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/tools/pre_poc_scanner/settings.py:34` | `PRECHECK_PDF_LOW_DENSITY_RATIO_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/tools/pre_poc_scanner/settings.py:40` | `PRECHECK_TEXT_SHORT_CHARS_THRESHOLD` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/tools/pre_poc_scanner/settings.py:46` | `PRECHECK_TEXT_LOW_DENSITY_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/tools/pre_poc_scanner/settings.py:52` | `PRECHECK_TEXT_GIBBERISH_DENSITY_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/tools/pre_poc_scanner/settings.py:58` | `PRECHECK_TEXT_HIGH_REPLACEMENT_RATIO_THRESHOLD` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/tools/pre_poc_scanner/settings.py:64` | `PRECHECK_NEAR_DUP_HAMMING_THRESHOLD` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/tools/pre_poc_scanner/settings.py:70` | `PRECHECK_NEAR_DUP_MAX_PAIRS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/tools/pre_poc_scanner/settings.py:76` | `PRECHECK_SAMPLE_SIZE` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/tools/web_search.py:70` | `TAVILY_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/tools/web_search.py:116` | `SERPER_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/tools/web_search.py:166` | `BRAVE_SEARCH_API_KEY` | `str` | direct | declared non-Optional default owns the value |
| `app/rag/tools/web_search.py:214` | `WEB_SEARCH_MAX_RESULTS` | `int` | direct | existing positive max() minimum prevents disabling the bound |
| `app/rag/tools/web_search.py:85` | `WEB_SEARCH_TIMEOUT_SEC` | `float` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/tools/web_search.py:135` | `WEB_SEARCH_TIMEOUT_SEC` | `float` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/tools/web_search.py:181` | `WEB_SEARCH_TIMEOUT_SEC` | `float` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/workflows/crag_streaming.py:53` | `RAG_CRAG_STREAMING_MIN_TOP_SCORE` | `float` | direct | declared non-Optional default owns the value |
| `app/rag/workflows/crag_streaming.py:52` | `RAG_CRAG_STREAMING_MIN_CITATIONS` | `int` | direct | declared non-Optional default owns the value |
| `app/rag/workflows/crag_streaming.py:75` | `RAG_CRAG_STREAMING_MAX_RESULTS` | `int` | decision | security/resource ceiling zero semantics requires commander review |
| `app/rag/workflows/critic.py:79` | `FAITHFULNESS_SCORE_MAX_CLAIMS` | `int` | direct | declared non-Optional default owns the value |
