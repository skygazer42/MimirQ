---
sidebar_label: "排障"
sidebar_position: 6
---

# 数据集 — 排障

## 概述

本页属于 **数据集** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

典型：列表为空（权限/租户）、更新 409（并发修改）、删除失败（仍存在文档绑定）。结合后端日志与 `docs/integration/FE_BE_DEBUG.md` 定位。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
