---
sidebar_label: "总览"
sidebar_position: 1
---

# 集成与联调总览

**本文适用于**：**集成工程师、前后端开发、测试、解决方案**；需要把 Web、移动端或第三方系统 **稳定接到 MimirQ API**，并能在出问题时 **快速定位层界**。

## 本侧栏读法（业务优先）

1. **有明确交付目标时**：请先打开 **[按任务上手（业务）](./tasks/task-catalog.md)**，按「首配 → 数据集 → 文档 → 排障」路径执行，每步含 **验收与失败影响**。  
2. **查单点契约时**：用 **[联调模式](./patterns/errors-4xx-5xx.md)**（错误、鉴权、分页、上传、SSE 等）与 **[场景速查](./scenarios/s01-upload-chat.md)**。  
3. **对字段与路径较真时**：以 [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/) 为准，并对照仓库 [API_CONTRACT](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)。

## 任务入口（摘要）

| 任务 | 链接 |
| --- | --- |
| 任务总览与角色表 | [task-catalog](./tasks/task-catalog.md) |
| 新租户与环境首配 | [task-new-tenant-setup](./tasks/task-new-tenant-setup.md) |
| 数据集上线与可问答 | [task-dataset-go-live](./tasks/task-dataset-go-live.md) |
| 文档入库与可检索 | [task-ingest-documents](./tasks/task-ingest-documents.md) |
| 解析失败止损 | [task-parse-failure-triage](./tasks/task-parse-failure-triage.md) |
| 检索效果变差 | [task-retrieval-quality](./tasks/task-retrieval-quality.md) |
| 治理与隔离审批 | [task-governance-quarantine](./tasks/task-governance-quarantine.md) |

## 自动生成材料

- [FE/BE 对照矩阵（自动生成）](./generated/fe-be-matrix.mdx)：OpenAPI tag、`web/lib/api`、Next 路由列表；**不能替代**业务任务说明。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库：[FE_BE_DEBUG.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md) · [API_CONTRACT.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
