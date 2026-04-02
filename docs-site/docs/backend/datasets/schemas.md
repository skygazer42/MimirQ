---
sidebar_label: "请求与响应要点"
sidebar_position: 3
---

# 数据集 — 请求与响应要点

## 概述

字段以 OpenAPI Schema **DatasetCreate** / **DatasetUpdate** / **Dataset** 为准（Redoc）。以下为联调最常碰到的键位说明（带 `*` 表示创建时必填，以 OpenAPI `required` 为准）。

## DatasetCreate（摘录）

| 字段 | 说明 |
| --- | --- |
| `name`* | 数据集显示名 |
| `description` | 描述 |
| `permission` | 可见性/权限模型（枚举见 OpenAPI） |
| `partial_member_list` / `partial_group_list` | 部分成员/组 ACL |
| `default_parser_backend` / `default_chunk_strategy` | 默认解析与分块 |
| `rag_defaults` | 默认 RAG/检索相关嵌套配置 |
| `default_rag_config_template_id` / `default_rag_config_template_key` | 默认 RAG 模板引用 |
| `default_prompt_template_id` | 默认提示词模板 |

创建成功响应一般为 **Dataset** 对象（含 `id`、时间戳等），以 OpenAPI 为准。

## 列表 `GET /api/v1/datasets/`

- 查询参数常见：`skip`、`limit`、`category_id`、`include_descendants`（以 Redoc 为准）。
- 响应包装类型见 **DatasetListResponse**。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
