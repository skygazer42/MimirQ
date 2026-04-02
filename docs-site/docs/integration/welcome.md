---
sidebar_label: "总览"
sidebar_position: 1
---

# 集成与联调总览

本分区从 **「如何把 MimirQ 接进你的环境」** 出发，与 **Frontend / Backend / Ops** 文档互补：那边讲页面与实现细节，这里讲 **业务结果、推荐路径与契约入口**。

## 三层叙事（按你需要选一层）

### 业务层：我要达成什么结果？

- **按角色选入口**（谁来看、从哪开始）：  
  [租户与系统管理员](./roles/admin) · [集成工程师](./roles/integration-engineer) · [运维 / SRE](./roles/sre-ops)
- **按任务走剧本**（单页深度、可验收）：  
  [新租户首日上线](./tasks/go-live-tenant) · [知识库可对用户问答](./tasks/knowledge-base-qa) · [文档卡在解析或索引](./tasks/document-stuck)

### 操作层：具体怎么调、顺序是什么？

- **HTTP 场景顺序**（方法与路径骨架，细节以 OpenAPI 为准）：仓库内 [docs/api/workflows.md](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)
- **集成模式速查**（认证、分页、multipart、SSE、幂等、错误码等）：[集成模式速查](./patterns/auth-modes) 起（侧栏「集成模式速查」下全文）

### 契约层：字段、权限、与前端覆盖是否一致？

- **人机可读契约**：[API_CONTRACT](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
- **全量 Schema / 试调用**：[OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- **前端路由 ↔ 后端路径矩阵**（站点内）：[前后端矩阵（生成）](./generated/fe-be-matrix)

## 与仓库 `docs/integration/` 的关系

站内文章侧重 **导航与整合**；深度长文、清单类仍以 GitHub 上 `docs/integration/*.md` 为准（上表已链出常用篇）。

## 相关链接（速查）

| 类型 | 链接 |
| --- | --- |
| Redoc | [skygazer42.github.io/MimirQ](https://skygazer42.github.io/MimirQ/) |
| 场景化 API 顺序 | [workflows.md](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md) |
| 契约与排障 | [API_CONTRACT](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [FE_BE_DEBUG](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md) |
