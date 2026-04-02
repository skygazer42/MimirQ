---
sidebar_label: "租户与系统管理员"
sidebar_position: 1
---

# 租户与系统管理员 — 从哪开始

## 本页回答的业务问题

你是 **管理员或数据负责人**：要在组织内把 MimirQ 用起来，让用户能 **安全地** 使用知识库与对话，而不是自己啃完整套 API。

## 建议阅读路径

1. **首日上线**（业务结果：有人能登录、有数据集、能试传文档）：[业务剧本：新租户首日上线](../tasks/go-live-tenant)。
2. **让知识库真正可问答**（业务结果：文档进库且对话能命中）：[业务剧本：知识库可对用户问答](../tasks/knowledge-base-qa)。
3. **文档一直处理不完**（业务影响：用户看不到内容、投诉增加）：[业务剧本：文档卡在解析或索引](../tasks/document-stuck)。

## 你在 Web 上常去的模块（路径以实际部署为准）

| 目的 | 典型入口（仓库内路由） |
| --- | --- |
| 数据集总览与配置 | `/datasets`、各数据集子页（预检、画像、健康等） |
| 知识入库 | `/knowledge/ingestion` |
| 隔离与审核 | `/knowledge/quarantine` |
| 系统设置 | Settings 相关页（见 OpenAPI **settings** / **meta**） |

## 需要深入时

- **契约与权限边界**：[API_CONTRACT](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
- **端点调用顺序（集成向）**：[workflows.md](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)
- **全量 Schema**：[Redoc](https://skygazer42.github.io/MimirQ/)

## 与其他视角的关系

- **Frontend 侧栏**：页面、组件与 `web/lib/api` 调用细节。
- **Backend 侧栏**：各域 API 与状态机说明。
- **Ops 侧栏**：探针、部署与 Runbook。
