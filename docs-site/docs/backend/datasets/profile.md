---
sidebar_label: "画像（Profile）"
sidebar_position: 9
---

# 数据集 — 画像（Profile）

## 概述

本页属于 **数据集** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

数据集画像指标与存储；对接检索配置时的注意点。

## 与任务的关系

- [新租户首日上线](../../integration/tasks/go-live-tenant.md) 中「画像红线」与默认 RAG/切块策略选型，常需对照画像指标再改 `rag_defaults`。  
- [知识库可对用户问答](../../integration/tasks/knowledge-base-qa.md) 中检索验收变差时，画像用于判断 **数据形态** 是否匹配当前分块/嵌入策略。

## 前端入口（对照）

- Web **画像** 子页：见 Frontend [数据集 — 用户路径](../../frontend/datasets/overview.md)。

## 联调要点

| 关注点 | 说明 |
| --- | --- |
| 耗时 | 大库画像可能异步；配合 [状态与任务](./state-jobs.md) |
| 与预检 | 门禁条件不要与 [预检](./precheck.md) 重复冲突 |
| 存储 | 指标落库与展示字段以 OpenAPI 响应为准 |

## 相关链接

- [数据集 — API 索引](./api-index.md) · [请求要点](./schemas.md) · [排障](./troubleshooting.md)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
