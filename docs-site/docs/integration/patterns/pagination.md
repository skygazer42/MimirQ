---
sidebar_label: "分页"
sidebar_position: 4
---

# 列表分页与查询参数

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 常见约定

- 多数列表支持 `skip`、`limit`（或 `offset`/`page`，以 OpenAPI 为准）。
- 默认值与上限以 Redoc 中参数说明为准；超出上限可能 422。

## 前端

- 表格翻页时避免在路由中丢失 `limit`；大页 deep link 注意 URL 长度。

## 集成测试

- 断言总数与当前页条数；空列表与最后一页边界。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
