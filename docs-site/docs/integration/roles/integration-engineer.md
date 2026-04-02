---
sidebar_label: "集成工程师"
sidebar_position: 2
---

# 集成工程师 — 从哪开始

## 本页回答的业务问题

你要把 MimirQ **接进现有系统**（门户、工单、自建前端）：需要 **稳定的认证、可预期的错误、可重复的调用顺序**，而不是只对着 Redoc 试错。

## 建议阅读路径

1. **环境与契约**：[集成模式 — 认证](../patterns/auth-modes.md) · [租户与可见性](../patterns/tenant-headers.md) · [OpenAPI 与前端对照](../patterns/openapi-contract-check.md)。
2. **端到端顺序**（方法 + 路径清单）：仓库 [docs/api/workflows.md](https://github.com/skygazer42/MimirQ/blob/main/docs/api/workflows.md)。
3. **业务级验收流**（目标 + 步骤 + 异常）：[业务剧本](../tasks/go-live-tenant) 三篇，对照你的集成范围选读。
4. **自动生成对照**：[FE/BE 矩阵](../generated/fe-be-matrix.mdx)（改 API 或前端 path 后须重新生成并提交）。

## 联调必备清单

- [ ] `Authorization: Bearer` 与租户上下文与文档一致（[API_CONTRACT](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)）。
- [ ] 上传、SSE、长轮询路径上 **网关不缓冲、不截断 body**（见 [SSE 模式](../patterns/sse-streaming.md)、[multipart](../patterns/multipart-upload.md)）。
- [ ] 4xx/5xx 可映射到业务动作（重试、换 Token、改参数）：[错误码与响应体](../patterns/errors-4xx-5xx.md)。

## 排障

- [FE_BE_DEBUG.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)

## 与其他视角的关系

- **Backend**：按 Tag 查路径与语义。
- **Frontend**：对齐 `web/lib/api` 与路由，便于对照你们自建 UI。
