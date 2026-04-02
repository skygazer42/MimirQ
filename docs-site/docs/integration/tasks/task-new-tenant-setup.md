---
sidebar_label: "新租户与环境首配"
sidebar_position: 2
---

# 任务：新租户与环境首配

**本文适用于**：**平台运维、集成工程师、租户管理员**；在全新环境或新租户接入时，把系统推到「可登录、可调 API、核心依赖不红」。

## 业务目标

- 业务方可使用 **合法凭据** 访问 Web 与 API，且 **租户上下文** 正确。  
- **健康检查** 通过或已知降级项在可接受范围内，避免上线后才发现依赖全挂。  
- 集成方拿到 **Base URL、鉴权方式、环境差异说明**，可开始对接数据集与文档。

## 前置条件

- 部署拓扑已按 [docker_compose](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md) 或贵司规范落地。  
- 已配置 **数据库、对象存储、向量库、LLM** 等必选依赖（见仓库 `.env.example` 与运维文档）。  
- 若使用企业 SSO/SCIM，需与 OpenAPI 中 **auth / scim** 等标签对齐（以 Redoc 为准）。

## 推荐步骤（概要）

1. **连通性**：自浏览器打开 Web；自终端 `GET /api/v1/health` 与 `GET /api/v1/health/ready`（见 [运维 — 健康探针](../../ops/health-probes.md)）。  
2. **鉴权**：走正式 **注册/登录** 或企业 IdP 流程，确认 `Authorization: Bearer` 在后续请求生效（见 [联调模式 — 认证](../patterns/auth-modes.md)）。  
3. **租户**：用同一 Token 调 **当前用户/租户** 相关接口，确认列表类接口返回符合预期可见性（见 [租户与可见性](../patterns/tenant-headers.md)）。  
4. **前端环境变量**：`NEXT_PUBLIC_*` 与后端 origin 一致，避免 CORS 与错端口（见 [环境变量导读](../patterns/env-matrix.md)）。  
5. **记录基线**：保存一份「首配成功」时的 **版本号、配置摘要、探针结果**，便于后续变更对比。

## 验收标准（业务）

- [ ] 至少一名业务用户可 **稳定登录** 并完成一次 **读列表类 API**（如数据集列表）。  
- [ ] 就绪探针在运维监控中 **持续为绿**，或仅有已备案的 **已知降级**。  
- [ ] 集成方文档中写明 **Base URL、鉴权步骤、禁止在生产使用的 Header 调试方式**。

## 失败时的业务影响与止损

| 现象 | 业务影响 | 止损动作 |
| --- | --- | --- |
| 健康/就绪失败 | 全站不可用或半可用 | 按依赖顺序查 DB/存储/向量/LLM；切只读或公告停机 |
| 登录 401/403 | 无法开展任何业务 | 查时钟、Token、租户中间件；对照 [错误码](../patterns/errors-4xx-5xx.md) |
| CORS / 错端口 | 前端「全坏」、API 实际正常 | 统一前后端域名与 env；勿在业务层误判为后端故障 |

## 相关手册链接

- [集成总览](../welcome.md) · [数据集上线](./task-dataset-go-live.md) · [文档入库](./task-ingest-documents.md)  
- Backend：[认证相关 API 索引](https://github.com/skygazer42/MimirQ/tree/main/docs-site/docs/backend)（侧栏检索 auth）  
- Frontend：[欢迎与读法](../../frontend/welcome.md)  
- 仓库：[FE_BE_DEBUG](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
