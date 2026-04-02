---
sidebar_label: "任务总览"
sidebar_position: 1
---

# 按任务上手 — 总览

**本文适用于**：需要把 MimirQ 从「能连上」推进到「业务可用」的 **租户管理员、集成工程师、平台运维**；若你只做纯后端契约查阅，可直接从顶部导航进入 **Backend** 侧栏。

手册的默认视角曾是「路径与 OpenAPI」；本目录改为 **任务驱动**：先写清 **业务目标、验收与失败影响**，再指向具体 API、页面与仓库排障文。

## 读者角色速查

| 角色 | 建议从这里开始 |
| --- | --- |
| 租户管理员 / 数据 Owner | [数据集上线与可问答](./task-dataset-go-live.md)、[治理与隔离](./task-governance-quarantine.md) |
| 集成 / 前端工程 | [新租户与环境首配](./task-new-tenant-setup.md)、[文档入库与可检索](./task-ingest-documents.md) |
| 运维 / SRE | [新租户与环境首配](./task-new-tenant-setup.md) 中依赖与探针、[运维侧栏](../../ops/welcome.md) |
| 排障（现象驱动） | [解析失败止损](./task-parse-failure-triage.md)、[检索效果变差](./task-retrieval-quality.md) |

## 任务目录

| 任务 | 业务结果（验收） | 主文档 |
| --- | --- | --- |
| 新租户与环境首配 | 前后端可连、鉴权可用、核心依赖健康 | [task-new-tenant-setup](./task-new-tenant-setup.md) |
| 数据集上线与可问答 | 数据集创建、策略与可见性正确，可绑定文档并参与问答 | [task-dataset-go-live](./task-dataset-go-live.md) |
| 文档入库与可检索 | 文档进入处理流水线并达到可检索/可对话状态 | [task-ingest-documents](./task-ingest-documents.md) |
| 解析失败止损 | 定位卡住原因，恢复或隔离，避免队列堆积影响业务 | [task-parse-failure-triage](./task-parse-failure-triage.md) |
| 检索效果变差 | 从现象区分「无结果/错结果/慢」，收敛到配置或数据问题 | [task-retrieval-quality](./task-retrieval-quality.md) |
| 治理与隔离 | 敏感内容按策略进入隔离与审核，满足合规流程 | [task-governance-quarantine](./task-governance-quarantine.md) |

## 与四侧栏的关系

- **Backend**：单域 API、字段与状态机细节。  
- **Frontend**：用户在哪个路由完成哪一步。  
- **Integration（本区）**：端到端顺序与联调；**任务目录**是业务入口。  
- **Ops**：部署、探针、Runbook。

## 相关链接

- [集成总览](../welcome.md) · [场景速查](../scenarios/s01-upload-chat.md) · [联调模式](../patterns/errors-4xx-5xx.md)
- 仓库：[FE_BE_DEBUG](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md) · [API_CONTRACT](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
