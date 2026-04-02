---
sidebar_label: "API 参考索引"
sidebar_position: 2
---

# 数据集 — API 参考索引

## 概述

本页属于 **数据集** 域的 **后端** 视角。完整路径、请求/响应模型以 OpenAPI **Datasets** 标签与 [Redoc](https://skygazer42.github.io/MimirQ/) 为准；下列表格便于复制检索（与当前 `web/openapi.json` 一致）。

## OpenAPI 路径（Tag: Datasets）

| 方法 | Path |
| --- | --- |
| DELETE | `/api/v1/datasets/{dataset_id}` |
| GET | `/api/v1/datasets/` |
| GET | `/api/v1/datasets/{dataset_id}` |
| GET | `/api/v1/datasets/{dataset_id}/categories` |
| GET | `/api/v1/datasets/{dataset_id}/config/export` |
| GET | `/api/v1/datasets/{dataset_id}/documents/export` |
| GET | `/api/v1/datasets/{dataset_id}/export` |
| GET | `/api/v1/datasets/{dataset_id}/health` |
| GET | `/api/v1/datasets/{dataset_id}/ingestion-policy` |
| GET | `/api/v1/datasets/{dataset_id}/ingestion-policy/export` |
| GET | `/api/v1/datasets/{dataset_id}/ingestion-policy/versions` |
| GET | `/api/v1/datasets/{dataset_id}/ingestion/stats` |
| GET | `/api/v1/datasets/{dataset_id}/profile/buckets/documents` |
| GET | `/api/v1/datasets/{dataset_id}/profile/export` |
| GET | `/api/v1/datasets/{dataset_id}/profile/export-html` |
| GET | `/api/v1/datasets/{dataset_id}/profile/findings/{finding_key}` |
| GET | `/api/v1/datasets/{dataset_id}/profile/scan-runs` |
| GET | `/api/v1/datasets/{dataset_id}/profile/scan-runs/{scan_run_id}` |
| GET | `/api/v1/datasets/{dataset_id}/profile/summary` |
| PATCH | `/api/v1/datasets/{dataset_id}` |
| POST | `/api/v1/datasets/` |
| POST | `/api/v1/datasets/{dataset_id}/clone` |
| POST | `/api/v1/datasets/{dataset_id}/config/import` |
| POST | `/api/v1/datasets/{dataset_id}/ingestion-policy/import` |
| POST | `/api/v1/datasets/{dataset_id}/ingestion-policy/rollback` |
| POST | `/api/v1/datasets/{dataset_id}/profile/scan-runs` |
| POST | `/api/v1/datasets/{dataset_id}/purge` |
| PUT | `/api/v1/datasets/{dataset_id}/categories` |
| PUT | `/api/v1/datasets/{dataset_id}/ingestion-policy` |

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
- 路由注册：[app/api/v1](https://github.com/skygazer42/MimirQ/tree/main/app/api/v1)
