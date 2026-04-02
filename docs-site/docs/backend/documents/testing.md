---
sidebar_label: "测试"
sidebar_position: 7
---

# 文档 — 测试

## 概述

本页属于 **文档与入库** 域的 **后端** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

API 与解析相关的 pytest / smoke 指针。

## 与任务的关系

- [文档入库](../../integration/tasks/task-ingest-documents.md) 与 [解析止损](../../integration/tasks/task-parse-failure-triage.md) 中的 **回归用例** 可引用本页指向的自动化；上传/批处理边界建议有专项测。

## 建议覆盖

| 范围 | 目的 |
| --- | --- |
| upload + status | MIME、大小、dataset 绑定 |
| 失败重试 | 幂等与重复提交 |
| 解析器切换 | 多 backend 回归（若部署启用） |

## 相关链接

- [文档 — API 索引](./api-index.md) · [排障](./troubleshooting.md)
- 仓库脚本：[scripts/api_smoke.py](https://github.com/skygazer42/MimirQ/blob/main/scripts/api_smoke.py)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
