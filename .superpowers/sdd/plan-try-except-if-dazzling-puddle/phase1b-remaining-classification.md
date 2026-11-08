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
