---
sidebar_label: "集成工程师"
sidebar_position: 2
---

# 集成工程师

集成工程师负责将 MimirQ 的知识库与对话能力接入现有业务系统（门户、工单、自建前端等），需要稳定的认证、可预期的错误处理与可重复的调用序列。

## 职责概览

| 职责 | 说明 |
|------|------|
| API 对接 | 按 OpenAPI 契约实现调用，管理认证与 Header |
| 数据流编排 | 上传 → 解析 → 索引 → 检索 → 对话的全链路集成 |
| 错误处理 | 分类 4xx/5xx，实现重试与降级策略 |
| 契约守护 | 跟踪 OpenAPI 变更，维护集成测试 |

## 推荐阅读路径

| 阶段 | 目标 | 推荐页面 |
|------|------|----------|
| 1. 认证接入 | 拿到 Token、理解租户模型 | [认证模式](../patterns/auth-modes.md) / [租户 Header](../patterns/tenant-headers.md) |
| 2. 首次调通 | 上传文档并对话 | [场景: 上传后对话](../scenarios/s01-upload-chat.md) |
| 3. 错误处理 | 分类错误、实现重试 | [错误码](../patterns/errors-4xx-5xx.md) / [重试与幂等](../patterns/idempotency-retries.md) |
| 4. 流式集成 | SSE 对话与重连 | [SSE 流式](../patterns/sse-streaming.md) / [场景: SSE 重连](../scenarios/s15-sse-reconnect.md) |
| 5. 契约维护 | OpenAPI 对照与 CI 检查 | [契约对照](../patterns/openapi-contract-check.md) / [FE/BE 矩阵](../generated/fe-be-matrix.mdx) |

## 首日清单

- [ ] **获取 API Key 或 Token** — 从管理员处获取凭证，验证认证有效

```bash
# 验证认证
curl -s "$BASE_URL/api/v1/auth/me" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

- [ ] **上传测试文档** — 验证 multipart 上传链路

```bash
curl -X POST "$BASE_URL/api/v1/documents/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.pdf" \
  -F "dataset_id=$DATASET_ID"
```

- [ ] **验证检索** — 确认文档处理完成后可被检索命中
- [ ] **接入对话** — 发起一次 RAG 对话，验证回答引用了上传内容

:::warning 网关配置
确保反向代理（Nginx 等）不缓冲 SSE 响应、不截断大文件上传 body。这是集成联调中最常见的阻塞点。
:::

## 关键 API 端点

| 操作 | 方法 & 路径 | 说明 |
|------|-------------|------|
| 身份验证 | `GET /api/v1/auth/me` | 校验 Token 有效性 |
| 上传文档 | `POST /api/v1/documents/upload` | multipart/form-data |
| 文档状态 | `GET /api/v1/documents/{id}/status` | 轮询处理进度 |
| RAG 对话 | `POST /api/v1/chat/completions` | 支持 SSE 流式 |
| 检索调试 | `POST /api/v1/retrieval/search` | 验证检索命中 |
| 数据集列表 | `GET /api/v1/datasets/` | 分页查询 |

## 联调必备检查

- [ ] `Authorization: Bearer <token>` 格式正确，前缀与空格无误
- [ ] 多租户场景下 `X-Tenant-ID` 或 JWT claims 中包含租户上下文
- [ ] 上传接口 `Content-Type` 为 `multipart/form-data`，字段名与 OpenAPI 一致
- [ ] SSE 路径上网关已配置 `proxy_buffering off`
- [ ] 4xx/5xx 错误可映射到业务动作（重试、刷新 Token、修改参数）

## 相关链接

- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
- [分页模式](../patterns/pagination.md) | [文件上传](../patterns/multipart-upload.md)
- [可观测性与请求追踪](../patterns/observability-requests.md)
