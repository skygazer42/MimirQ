# 待总指挥裁决的安全上限

保留原兜底，未改变运行安全策略。配置声明未明确零语义且未确认既有正数校验/下限的资源限制，需裁决后再改。

- `app/api/v1/scim.py:200` `SCIM_PAGE_SIZE_MAX`：0会使 `if max_page_size > 0` 跳过上限；已恢复 `or 200`，新回归固定未决前仍封顶200。独立审查发现并纠正后缀 `_MAX` 漏筛。
- `app/api/utils/document_pipeline_input.py:21` `PIPELINE_FORM_JSON_MAX_CHARS`（config.py:481，默认 `200000`）：`settings.PIPELINE_FORM_JSON_MAX_CHARS or 200_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/utils/pipeline_options.py:40` `PIPELINE_FORM_JSON_MAX_CHARS`（config.py:481，默认 `200000`）：`settings.PIPELINE_FORM_JSON_MAX_CHARS or 200_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/utils/url_ingest.py:327` `MAX_FILE_SIZE`（config.py:412，默认 `50000000`）：`settings.MAX_FILE_SIZE or 50_000_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:561` `TABLE_SEM_FILTER_MAX_COLS`（config.py:1601，默认 `30`）：`settings.TABLE_SEM_FILTER_MAX_COLS or 30`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1019` `TABLE_QUERY_MAX_ROWS`（config.py:1561，默认 `200`）：`body.max_rows or settings.TABLE_QUERY_MAX_ROWS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1020` `TABLE_QUERY_MAX_COLS`（config.py:1562，默认 `200`）：`body.max_cols or settings.TABLE_QUERY_MAX_COLS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1101` `TABLE_QUERY_MAX_ROWS`（config.py:1561，默认 `200`）：`body.max_rows or settings.TABLE_QUERY_MAX_ROWS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1231` `TABLE_QUERY_MAX_ROWS`（config.py:1561，默认 `200`）：`body.max_rows or settings.TABLE_QUERY_MAX_ROWS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:557` `TABLE_LOTUS_MAX_ROWS`（config.py:1598，默认 `20000`）：`settings.TABLE_LOTUS_MAX_ROWS or 20_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:558` `TABLE_SEM_FILTER_MAX_IN_ROWS`（config.py:1600，默认 `2000`）：`settings.TABLE_SEM_FILTER_MAX_IN_ROWS or 2000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1102` `TABLE_QUERY_MAX_ROWS`（config.py:1561，默认 `200`）：`settings.TABLE_QUERY_MAX_ROWS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1232` `TABLE_QUERY_MAX_ROWS`（config.py:1561，默认 `200`）：`settings.TABLE_QUERY_MAX_ROWS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:709` `TABLE_QUERY_MAX_COLS`（config.py:1562，默认 `200`）：`settings.TABLE_QUERY_MAX_COLS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:710` `TABLE_QUERY_MAX_BYTES`（config.py:1563，默认 `1000000`）：`settings.TABLE_QUERY_MAX_BYTES or 1_000_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:968` `TABLE_QUERY_MAX_COLS`（config.py:1562，默认 `200`）：`settings.TABLE_QUERY_MAX_COLS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:969` `TABLE_QUERY_MAX_BYTES`（config.py:1563，默认 `1000000`）：`settings.TABLE_QUERY_MAX_BYTES or 1_000_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1029` `TABLE_QUERY_MAX_BYTES`（config.py:1563，默认 `1000000`）：`settings.TABLE_QUERY_MAX_BYTES or 1_000_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1128` `TABLE_QUERY_MAX_COLS`（config.py:1562，默认 `200`）：`settings.TABLE_QUERY_MAX_COLS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1129` `TABLE_QUERY_MAX_BYTES`（config.py:1563，默认 `1000000`）：`settings.TABLE_QUERY_MAX_BYTES or 1_000_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:967` `TABLE_QUERY_MAX_ROWS`（config.py:1561，默认 `200`）：`settings.TABLE_QUERY_MAX_ROWS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1027` `TABLE_QUERY_MAX_ROWS`（config.py:1561，默认 `200`）：`settings.TABLE_QUERY_MAX_ROWS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/dataset_tables.py:1028` `TABLE_QUERY_MAX_COLS`（config.py:1562，默认 `200`）：`settings.TABLE_QUERY_MAX_COLS or 200`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/integrations_dify.py:6138` `DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC`（config.py:892，默认 `60.0`）：`settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC or 60.0`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/parsing.py:1289` `VLM_CORRECTION_TIMEOUT_SEC`（config.py:552，默认 `60`）：`settings.VLM_CORRECTION_TIMEOUT_SEC or 60`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/parsing.py:1290` `VLM_CORRECTION_MAX_PAGES`（config.py:1833，默认 `2`）：`settings.VLM_CORRECTION_MAX_PAGES or 3`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/parsing.py:1291` `VLM_CORRECTION_MAX_CHARS`（config.py:553，默认 `40000`）：`settings.VLM_CORRECTION_MAX_CHARS or 40_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/parsing.py:1363` `IMAGE_OCR_MAX_IMAGES`（config.py:579，默认 `20`）：`settings.IMAGE_OCR_MAX_IMAGES or 20`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/parsing.py:1364` `IMAGE_OCR_MAX_CHARS`（config.py:578，默认 `2000`）：`settings.IMAGE_OCR_MAX_CHARS or 2000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/pipeline.py:1293` `GOVERNANCE_REGEX_TIMEOUT_MS`（config.py:1758，默认 `100`）：`settings.GOVERNANCE_REGEX_TIMEOUT_MS or 100`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/settings.py:483` `CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES`（config.py:199，默认 `200000`）：`settings.CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES or 200_000`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
- `app/api/v1/settings.py:588` `MAGIC_PDF_REQUEST_TIMEOUT_SEC`（config.py:1980，默认 `600`）：`settings.MAGIC_PDF_REQUEST_TIMEOUT_SEC or 600`。移除兜底可能让0进入无上限/未知语义路径；本轮未改。
