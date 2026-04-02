---
sidebar_label: "错误码与响应体"
sidebar_position: 1
---

# HTTP 4xx/5xx 与错误体

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

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
