---
sidebar_label: "状态与任务"
sidebar_position: 4
---

# 文档 — 状态与任务

## 概述

本页属于 **文档与入库** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

解析与索引流水线异步阶段；轮询间隔与超时建议。

## 与任务的关系

- [文档入库](../../integration/tasks/task-ingest-documents.md) 的 **业务验收** 依赖状态从 processing → 完成/失败的可见性。  
- [解析止损](../../integration/tasks/task-parse-failure-triage.md) 需 `status` + `timeline`（或等价）与日志 **同一 request** 对齐。

## 前端入口（对照）

- 入库/解析进度 UI：Frontend [文档 — 用户路径](../../frontend/documents/overview.md)。

## 联调要点

| 关注点 | 说明 |
| --- | --- |
| 轮询 | 使用退避；参见 Integration [重试/幂等](../../integration/patterns/idempotency-retries.md) |
| 终态 | 失败须带可展示原因，便于运营重试 |
| 与流水线 | 对照 [流水线阶段](./pipeline.md) 理解阶段名 |

## 相关链接

- [文档 — API 索引](./api-index.md) · [排障](./troubleshooting.md) · [流水线阶段](./pipeline.md)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
