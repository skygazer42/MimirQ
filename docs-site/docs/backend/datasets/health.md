---
sidebar_label: "健康度（Health）"
sidebar_position: 10
---

# 数据集 — 健康度（Health）

## 概述

本页属于 **数据集** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

健康检查聚合指标与健康策略在 API 层的暴露。

## 与任务的关系

- 运维与租户管理员在 [数据集上线](../../integration/tasks/task-dataset-go-live.md) 后，用健康视图做 **持续运营**（索引滞后、失败率升高等）。  
- 与全站探针不同：此处更偏 **数据集维度** 的质量信号，详见 OpenAPI。

## 前端入口（对照）

- Web **健康** 子页：见 Frontend [数据集 — 用户路径](../../frontend/datasets/overview.md)。

## 联调要点

| 关注点 | 说明 |
| --- | --- |
| 与全局 health | `GET /api/v1/health` 绿 **不意味** 单数据集健康 |
| 告警 | 将关键指标接入监控时对齐 **同一 dataset_id** |
| 与排障 | 异常时落到 [排障](./troubleshooting.md) 与文档/解析队列 |

## 相关链接

- [数据集 — API 索引](./api-index.md) · [请求要点](./schemas.md) · [排障](./troubleshooting.md)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
