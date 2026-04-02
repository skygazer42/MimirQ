---
sidebar_label: "API 参考索引"
sidebar_position: 2
---

# 文档 — API 参考索引

## 概述

本页属于 **文档与入库** 域的 **后端** 视角。完整契约以 OpenAPI **Documents** 标签与 [Redoc](https://skygazer42.github.io/MimirQ/) 为准。下列为当前 `web/openapi.json` 中该标签下全部路径（共 54 条）。

## OpenAPI 路径（Tag: Documents）

| 方法 | Path |
| --- | --- |
| DELETE | `/api/v1/documents/{document_id}` |
| DELETE | `/api/v1/documents/{document_id}/chunks/{chunk_id}` |
| DELETE | `/api/v1/documents/{document_id}/versions/{pipeline_hash}` |
| GET | `/api/v1/documents/` |
| GET | `/api/v1/documents/batch-upload/status/{batch_id}` |
| GET | `/api/v1/documents/duplicates` |
| GET | `/api/v1/documents/folders` |
| GET | `/api/v1/documents/image-url/{img_id}` |
| GET | `/api/v1/documents/image/{image_id}` |
| GET | `/api/v1/documents/stats` |
| GET | `/api/v1/documents/{document_id}` |
| GET | `/api/v1/documents/{document_id}/access` |
| GET | `/api/v1/documents/{document_id}/chunks` |
| GET | `/api/v1/documents/{document_id}/chunks/matches` |
| GET | `/api/v1/documents/{document_id}/chunks/{chunk_id}` |
| GET | `/api/v1/documents/{document_id}/download` |
| GET | `/api/v1/documents/{document_id}/health` |
| GET | `/api/v1/documents/{document_id}/lifecycle-metadata` |
| GET | `/api/v1/documents/{document_id}/parsed-content` |
| GET | `/api/v1/documents/{document_id}/status` |
| GET | `/api/v1/documents/{document_id}/timeline` |
| GET | `/api/v1/documents/{document_id}/versions` |
| GET | `/api/v1/documents/{document_id}/versions/diff` |
| PATCH | `/api/v1/documents/{document_id}/chunks/{chunk_id}` |
| PATCH | `/api/v1/documents/{document_id}/lifecycle-metadata` |
| PATCH | `/api/v1/documents/{document_id}/metadata` |
| PATCH | `/api/v1/documents/{document_id}/pipeline` |
| POST | `/api/v1/documents/batch-delete` |
| POST | `/api/v1/documents/batch-upload/apply-urls` |
| POST | `/api/v1/documents/batch/access` |
| POST | `/api/v1/documents/batch/archive` |
| POST | `/api/v1/documents/batch/disable` |
| POST | `/api/v1/documents/batch/enable` |
| POST | `/api/v1/documents/batch/metadata` |
| POST | `/api/v1/documents/batch/move` |
| POST | `/api/v1/documents/batch/reingest` |
| POST | `/api/v1/documents/batch/retry` |
| POST | `/api/v1/documents/batch/unarchive` |
| POST | `/api/v1/documents/chunk-preview` |
| POST | `/api/v1/documents/chunk-preview/by-sha` |
| POST | `/api/v1/documents/manual` |
| POST | `/api/v1/documents/preview` |
| POST | `/api/v1/documents/upload` |
| POST | `/api/v1/documents/upload-batch` |
| POST | `/api/v1/documents/upload-url` |
| POST | `/api/v1/documents/{document_id}/cancel` |
| POST | `/api/v1/documents/{document_id}/chunks` |
| POST | `/api/v1/documents/{document_id}/chunks/reembed` |
| POST | `/api/v1/documents/{document_id}/chunks/{chunk_id}/disable` |
| POST | `/api/v1/documents/{document_id}/chunks/{chunk_id}/enable` |
| POST | `/api/v1/documents/{document_id}/qa/generate` |
| POST | `/api/v1/documents/{document_id}/retry` |
| POST | `/api/v1/documents/{document_id}/versions/{pipeline_hash}/activate` |
| PUT | `/api/v1/documents/{document_id}/access` |

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
