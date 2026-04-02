---
sidebar_label: "分页"
sidebar_position: 4
---

# 列表分页与查询参数

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 何时查阅

实现表格翻页、导出大量 ID、或脚本扫列表时；任何 **列表类** 任务（数据集、文档、任务队列）都应与此页约定一致。

## 业务影响与验收要点

- 翻页 **不丢查询条件**；深链 URL 可分享且可复现。  
- 大 `limit` 不被静默截断却不提示（应 422 或明确上限）。

## 典型失败与对策

| 症状 | 业务影响 | 优先动作 |
| --- | --- | --- |
| 重复或漏行 | 对账错误 | 固定排序键；避免并发写时盲翻页 |
| 422 on limit | 集成脚本失败 | 读 Redoc 上限；分批 |

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
