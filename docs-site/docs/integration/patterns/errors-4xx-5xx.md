---
sidebar_label: "错误码与响应体"
sidebar_position: 1
---

# HTTP 4xx/5xx 与错误体

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 何时查阅

接口返回非 2xx、客服只截到状态码、或需区分 **鉴权 / ACL / 校验 / 限流** 时；与 [新租户首日上线](../tasks/go-live-tenant.md)、[文档卡在解析或索引](../tasks/document-stuck.md) 中的止损表对照阅读。

## 业务影响与验收要点

- 集成侧能 **归类** 错误，避免把 ACL 404 当成「服务崩溃」。  
- 前端对高频错有 **可理解反馈**（可结合仓库 extract-errors 技能），并带 `request_id`（若响应体提供）便于后端对齐日志。

## 典型失败与对策

| 症状 | 业务体感 | 优先动作 |
| --- | --- | --- |
| 全站 502/503 | 产品不可用 | 查网关与依赖；[可观测性](./observability-requests.md) |
| 单接口 422 | 表单或脚本字段不对 | 对照 Redoc 必填与类型 |
| 列表有、详情 404 | 「系统坏了」误判 | [租户与可见性](./tenant-headers.md) |

## 阅读顺序

1. 看 **HTTP 状态码** 与响应 JSON 中的业务 `code` / `detail`（以 OpenAPI `ErrorResponse` 或实际返回为准）。
2. 对照 [FE_BE_DEBUG](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md) 中的 Network / 后端日志路径。

## 常见映射（经验）

| 症状 | 优先怀疑 |
|------|----------|
| 401 | 未带或过期 `Authorization: Bearer`；时钟漂移 |
| 403 | 租户/数据集 ACL；功能开关 |
| 404 | 路径或资源 ID 错误；租户下不可见 |
| 409 | 并发更新、唯一约束、非法状态迁移 |
| 422 | Pydantic 校验失败；检查请求体字段名与类型 |
| 429 / 503 | 限流或依赖不可用；退避重试 |

## 前端

未知业务码时参考仓库内 **extract-errors** 技能，避免静默吞错。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
