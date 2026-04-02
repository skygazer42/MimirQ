---
sidebar_label: "重试 / 幂等"
sidebar_position: 7
---

# 重试、幂等与重复提交

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 何时查阅

设计客户端重试、批处理脚本、或 **503/429** 洪峰时；对应 [解析止损](../tasks/task-parse-failure-triage.md) 中的重试与熔断描述。

## 业务影响与验收要点

- **非幂等 POST** 默认不重试，除非有幂等键或业务可接受重复资源。  
- UI 防双击与 **退避** 一致，避免雪崩。

## 典型失败与对策

| 症状 | 业务影响 | 优先动作 |
| --- | --- | --- |
| 重复订单式资源 | 数据脏 | 加 Idempotency-Key 或去重键 |
| 重试风暴 | 全站更慢 | 指数退避 + 抖动 + 上限 |

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
