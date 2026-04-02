---
sidebar_label: "环境变量导读"
sidebar_position: 8
---

# 环境变量索引（导读）

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 后端

- 完整清单以部署文档与 `.env.example` 为准：[docker_compose](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md)、仓库根 `.env.example`。

## 前端

- `NEXT_PUBLIC_*` 在 [web/lib/env](https://github.com/skygazer42/MimirQ/tree/main/web/lib) 及相关构建说明中消费；修改后需重新构建。

## 联调

- 同一浏览器会话中，前端 base URL 与后端实际 origin 必须一致，避免 CORS 与错误端口。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
