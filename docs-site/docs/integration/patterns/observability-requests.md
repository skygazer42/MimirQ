---
sidebar_label: "可观测性"
sidebar_position: 10
---

# 请求关联：日志与排障

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 何时查阅

跨团队排障、需要把 **浏览器一条失败** 与 **后端日志** 对齐时；[检索效果](../tasks/task-retrieval-quality.md) 与 [解析止损](../tasks/task-parse-failure-triage.md) 的深度调查都依赖此习惯。

## 业务影响与验收要点

- 支持人员能向用户索要 **时间与 request_id**，并在日志中 **唯一定位** 一次请求链。  
- 健康探针与业务指标 **分开展示**，避免把「能登录」当成「解析队列正常」。

## 典型失败与对策

| 症状 | 业务影响 | 优先动作 |
| --- | --- | --- |
| 无 request_id | 无法对齐 | 推动网关与后端统一字段 |
| 就绪探针绿但业务红 | 误判可用 | 增加队列/依赖子检查 |

## 后端

- 关注结构化日志中的 `request_id` / 租户 / 用户字段（以后端实现为准）。

## 前端

- 在开发环境对失败请求记录 **path + status + 响应体摘要**（注意脱敏）。

## 运维

- 健康检查：`GET /api/v1/health`、`GET /api/v1/health/ready`（见 OpenAPI **health**）；与 K8s 探针配置对齐。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
