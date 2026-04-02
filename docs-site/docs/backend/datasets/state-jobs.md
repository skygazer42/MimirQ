---
sidebar_label: "状态与任务"
sidebar_position: 4
---

# 数据集 — 状态与任务

## 概述

本页属于 **数据集** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

数据集元数据与关联任务（若有异步预检/画像）在 UI 与 API 之间的刷新策略；长耗时操作建议轮询任务状态端点（以 OpenAPI 为准）。

## 与任务的关系

- [数据集上线](../../integration/tasks/task-dataset-go-live.md) 与 [解析止损](../../integration/tasks/task-parse-failure-triage.md) 都依赖 **可轮询的任务 ID** 与明确终态。  
- 前端需避免 **过频轮询** 与无退避重试（参见 Integration [重试/幂等](../../integration/patterns/idempotency-retries.md)）。

## 前端入口（对照）

- 数据集详情内 **异步任务** 或进度展示：见 Frontend [数据集 — 用户路径](../../frontend/datasets/overview.md)。

## 联调要点

| 关注点 | 说明 |
| --- | --- |
| 终态 | 区分 success / failed / cancelled，勿永远转圈 |
| 与预检/画像 | 同一任务模型若复用，文档要写清 **类型字段** |
| 超时 | 产品承诺的 SLA 应 ≥ 后端最坏耗时 + 余量 |

## 相关链接

- [预检](./precheck.md) · [画像](./profile.md) · [API 索引](./api-index.md)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
