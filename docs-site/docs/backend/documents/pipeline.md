---
sidebar_label: "流水线阶段"
sidebar_position: 10
---

# 文档 — 流水线阶段

## 概述

本页属于 **文档与入库** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

解析 → 分块 → 向量/索引各阶段在 API/元数据中的体现。

## 与任务的关系

- [文档入库](../../integration/tasks/task-ingest-documents.md)：业务方需理解「完成」指 **哪一阶段**（解析完 vs 已可检索）。  
- [检索效果变差](../../integration/tasks/task-retrieval-quality.md)：切块/嵌入阶段常是召回弱的根因。

## 联调要点

| 阶段 | 排障时多问一句 |
| --- | --- |
| 解析 | 是否选对 parser_backend；依赖侧车是否健康 |
| 分块 | 策略是否与文档类型匹配 |
| 索引 | 向量服务与 DB 是否滞后 |

## 相关链接

- [状态与任务](./state-jobs.md) · [文档 — API 索引](./api-index.md) · [排障](./troubleshooting.md)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
