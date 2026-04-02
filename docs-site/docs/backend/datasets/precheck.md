---
sidebar_label: "预检（Precheck）"
sidebar_position: 8
---

# 数据集 — 预检（Precheck）

## 概述

本页属于 **数据集** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

预检结果如何影响入库与质量门禁；相关 REST 路径以 OpenAPI 标签为准。

## 与任务的关系

- 集成侧 [数据集上线](../../integration/tasks/task-dataset-go-live.md) 中「预检/画像门禁」依赖此处 API 与产品策略。  
- 若预检失败会 **阻断或告警批量入库**，需在运维与数据 Owner 之间约定 SLA。

## 前端入口（对照）

- Web 数据集详情下 **预检** 子页：见 Frontend [数据集 — 用户路径](../../frontend/datasets/overview.md) 中的路由说明。

## 联调要点

| 关注点 | 说明 |
| --- | --- |
| 路径与模型 | 以 OpenAPI **datasets** 下 precheck 相关 operation 为准 |
| 异步 | 长任务时配合 [状态与任务](./state-jobs.md) 轮询策略 |
| 与画像 | 与 [画像](./profile.md) 一并规划门禁，避免重复跑重任务 |

## 相关链接

- [数据集 — API 索引](./api-index.md) · [请求要点](./schemas.md) · [排障](./troubleshooting.md)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
