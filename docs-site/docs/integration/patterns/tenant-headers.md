---
sidebar_label: "租户 / 可见性"
sidebar_position: 3
---

# 租户与可见性边界

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 何时查阅

列表与详情结果「对不上」、或同一 ID 在不同账号下表现不同时；对应 [数据集上线](../tasks/task-dataset-go-live.md)、[文档入库](../tasks/task-ingest-documents.md) 中的 ACL 验收。

## 业务影响与验收要点

- 产品文案与 **404/403** 策略一致：不可见资源是隐藏还是显式无权限。  
- 集成测试覆盖 **多租户** 与 **partial 成员列表** 边界，避免上线后批量投诉。

## 典型失败与对策

| 症状 | 业务影响 | 优先动作 |
| --- | --- | --- |
| 列表可见、详情 404 | 信任崩塌 | 核对租户上下文与 partial 列表语义 |
| 管理端与普通用户列表不一致 | 运营误操作 | 对照 OpenAPI scope；分角色测 |

## 原则

- 多租户下，资源列表与单资源 GET 均受 **租户 + ACL** 约束；404 有时表示「不可见」而非不存在。

## 联调

- 用同一 Token 分别请求列表与详情，确认 `dataset_id` / `document_id` 属于当前租户。
- 管理端与普通用户可见集合可能不同；对照 OpenAPI 上 **依赖与 scope 说明**。

## 文档

- [API_CONTRACT.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
