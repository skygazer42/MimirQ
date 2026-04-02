---
sidebar_label: "状态与任务"
sidebar_position: 4
---

# 数据集 — 状态与任务

## 概述

本页属于 **数据集** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

数据集元数据与关联任务（若有异步预检/画像）在 UI 与 API 之间的刷新策略；长耗时操作建议轮询任务状态端点（以 OpenAPI 为准）。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
