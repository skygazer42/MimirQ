---
sidebar_label: "请求与响应要点"
sidebar_position: 3
---

# 文档 — 请求与响应要点

## 概述

上传、列表、状态、分块、解析文本等均以 OpenAPI **Documents** 下对应 operation 为准。

## `POST /api/v1/documents/upload`（multipart）

OpenAPI 体类型 **Body_upload_document_api_v1_documents_upload_post**（名称以导出为准），常见字段：

| 字段 | 说明 |
| --- | --- |
| `file`* | 上传文件（表单字段名以 Redoc 为准，多为 `file`） |
| `dataset_id` | 目标数据集（若可选/必填以 OpenAPI 为准） |
| `parser_backend` / `chunk_strategy` / `pipeline` | 解析与管道覆盖 |
| `user_metadata` | 自定义元数据 JSON |
| `governance_*` | 治理相关开关（去噪、unwrap 等，见 Schema 全量字段） |

## 文档状态

- 轮询 **`GET /api/v1/documents/{document_id}/status`**（或列表中的状态字段），状态枚举以 OpenAPI **Document** / 状态 schema 为准。
- 取消/重试：`POST .../cancel`、`POST .../retry` 等（见本站 **文档 — API 参考索引** 页）。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
