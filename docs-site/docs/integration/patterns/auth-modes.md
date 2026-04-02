---
sidebar_label: "认证"
sidebar_position: 2
---

# 认证方式：JWT 与 Header 调试

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 何时查阅

实现登录态、调试 401、或对比 **开发 Header 模式** 与生产 JWT 时；对应 [首配任务](../tasks/task-new-tenant-setup.md) 中的鉴权步骤。

## 业务影响与验收要点

- 生产客户端 **仅** 使用正式 OAuth/密码/IdP 流程拿到的 Token，不在文档中固化长期密钥。  
- Token 刷新失败时 UI **登出或可重试路径** 明确，避免静默失效。

## 典型失败与对策

| 症状 | 业务影响 | 优先动作 |
| --- | --- | --- |
| 间歇 401 | 用户频繁掉线 | 校时 NTP；检查 refresh；[错误码](./errors-4xx-5xx.md) |
| Header 调试误上生产 | 租户伪造风险 | 关网关入口；强制 Bearer |

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
