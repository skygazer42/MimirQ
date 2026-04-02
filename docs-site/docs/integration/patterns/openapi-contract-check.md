---
sidebar_label: "契约对照"
sidebar_position: 9
---

# OpenAPI 与前端调用对照

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## SSOT

- **路径与模型** 以 `web/openapi.json` / Redoc 为准；前端 `web/lib/api/*.ts` 应对齐生成的类型与 path。

## 日常检查

- 改后端路由后执行 `make openapi-export` 与前端 `gen:api-types`（以 Makefile / package.json 脚本为准）。
- 自动化对照见 [API_CONTRACT.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)。

## 手册内矩阵

- [FE/BE 对照矩阵（自动生成）](../generated/fe-be-matrix.mdx)

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
