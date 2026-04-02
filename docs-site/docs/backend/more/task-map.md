---
sidebar_label: "任务与域对照"
sidebar_position: 0
---

# 后端域 × 集成任务（导航）

**本文适用于**：已读 Integration **[任务总览](../../integration/tasks/task-catalog.md)**，需要快速跳到 **本侧栏（其余业务域）** 或 **Datasets/Documents** 细页做契约深挖时。

## 任务 → 建议后端入口

| 集成任务 | 本手册优先阅读 |
| --- | --- |
| [新租户与环境首配](../../integration/tasks/task-new-tenant-setup.md) | [平台与账号](./platform.md)（auth/RBAC 等）、[运维 — 健康探针](../../ops/health-probes.md) |
| [数据集上线与可问答](../../integration/tasks/task-dataset-go-live.md) | [数据集 — API 索引](../datasets/api-index.md)、[请求要点](../datasets/schemas.md)、[排障](../datasets/troubleshooting.md) |
| [文档入库与可检索](../../integration/tasks/task-ingest-documents.md) | [文档 — API 索引](../documents/api-index.md)、[请求要点](../documents/schemas.md)、[排障](../documents/troubleshooting.md) |
| [解析失败止损](../../integration/tasks/task-parse-failure-triage.md) | [解析（概要）](./parsing.md)、文档域排障与 OpenAPI **documents** |
| [检索效果变差](../../integration/tasks/task-retrieval-quality.md) | [检索（概要）](./retrieval.md)、[对话（概要）](./chat.md) |
| [治理与隔离](../../integration/tasks/task-governance-quarantine.md) | [治理（概要）](./governance.md)、[审计/证据](./evidence.md)（若流程涉及导出） |

## 说明

- **OpenAPI / Redoc** 仍是字段与路径的单一事实来源；上表只解决「从任务跳进哪本手册」。  
- 自动化 **tag ↔ 前端路由** 对照见 Integration [FE/BE 矩阵](../../integration/generated/fe-be-matrix.mdx)。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
