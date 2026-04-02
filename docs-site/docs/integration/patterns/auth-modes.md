---
sidebar_label: "认证"
sidebar_position: 2
---

# 认证方式：JWT 与 Header 调试

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## JWT（推荐）

- 登录/注册见 OpenAPI **auth** 分组；后续请求头：`Authorization: Bearer <access_token>`。
- Token 过期：刷新策略以前端实现与 OpenAPI 为准。

## Header 调试模式（仅开发）

- 部分部署允许 `X-User-ID` / `X-Tenant-ID` 等（见后端中间件与 [API_CONTRACT](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)）。
- **禁止**在生产客户端伪造租户头；生产务必走正式认证。

## 联调检查清单

- [ ] `Content-Type: application/json`（JSON 接口）
- [ ] Bearer 前缀与空格
- [ ] 与 Redoc 示例字段名一致（蛇形/驼峰以前端生成类型为准）

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
