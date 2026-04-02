---
sidebar_label: "总览"
sidebar_position: 1
---

# 前端视角总览

## 概述

本页属于 **全站** 域的 **前端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

Next.js 路由、`web/lib/api/*` 调用与 UI 状态从此侧栏进入。

## 如何读本侧栏

- 先 **用户路径与入口**（路由表），再 **web/lib/api 模块**（函数与能力分组），排障页对照浏览器 Network 与 [FE_BE_DEBUG](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)。
- 类型与 path 应与 OpenAPI 生成类型一致；后端变更后请同步 `openapi-export` 与前端类型生成。

## 按任务上手（业务）

若需要按交付顺序走通界面（登录、数据集、入库、解析、治理），见 Integration 侧栏 **[任务总览](../integration/tasks/task-catalog.md)**。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
