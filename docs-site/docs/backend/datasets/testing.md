---
sidebar_label: "测试"
sidebar_position: 7
---

# 数据集 — 测试

## 概述

本页属于 **数据集** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

pytest 中与 datasets 相关的 API 用例；`scripts/api_smoke.py` 中涉及数据集的操作 ID（若有）。

## 与任务的关系

- [首配](../../integration/tasks/task-new-tenant-setup.md) 与 [数据集上线](../../integration/tasks/task-dataset-go-live.md) 的 **自动化验收** 可部分映射到本仓库测试与 smoke 脚本；不能完全替代业务 UAT。

## 建议覆盖

| 范围 | 目的 |
| --- | --- |
| 创建 / 更新 / 列表 / 详情 | ACL 与 404 语义 |
| 预检 / 画像 / 健康（若有集成测） | 异步与轮询 |
| 权限边界 | partial 成员/组 |

## 相关链接

- [数据集 — API 索引](./api-index.md) · [排障](./troubleshooting.md)
- 仓库脚本：[scripts/api_smoke.py](https://github.com/skygazer42/MimirQ/blob/main/scripts/api_smoke.py)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
