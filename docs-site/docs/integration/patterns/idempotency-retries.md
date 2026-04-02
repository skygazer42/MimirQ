---
sidebar_label: "重试 / 幂等"
sidebar_position: 7
---

# 重试、幂等与重复提交

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 重试

- **仅对幂等或带幂等键的请求重试**：GET、PUT 覆盖、显式 `Idempotency-Key`（若 API 支持）。
- POST 创建类默认 **非幂等**；盲目重试可能导致重复资源。

## 退避

- 429/503 使用指数退避 + 抖动；设置最大重试次数。

## 与 UI

- 提交按钮 loading 防双击；失败后可安全重试的场景在集成文档中写明。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
