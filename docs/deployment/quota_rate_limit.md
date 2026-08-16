# Quotas & Rate Limits（MimirQ）

本页汇总 MimirQ 的 **限流与配额**相关配置（env / settings），用于：

- 防滥用、防雪崩（保护后端依赖与成本）
- 多租户公平性（避免单租户打爆系统）
- 交付验收（能解释“429 是什么、怎么调”）

> 约定：当触发限流/配额时，接口通常返回 **HTTP 429**，并带 `Retry-After`（秒）与结构化 `detail`（见 runbook 的 429 小节）。

---

## 1) 全局请求限流（RateLimitMiddleware）

作用：对 API 请求做 token-bucket 限流（按用户/租户/IP 聚合，best-effort）。

常用配置：

- `RATE_LIMIT_ENABLED`：是否启用（bool）
- `RATE_LIMIT_REQUESTS_PER_SECOND`：全局接口 RPS（float）
- `RATE_LIMIT_BURST_SIZE`：突发容量（int）
- `RATE_LIMIT_CHAT_RPS` / `RATE_LIMIT_CHAT_BURST`：对 chat/stream 额外限流（可选）

分布式（多副本一致性）：

- `RATE_LIMIT_REDIS_ENABLED=true`：启用 Redis 作为分布式 limiter
- `REDIS_URL`：Redis 连接（必需）
- `RATE_LIMIT_REDIS_PREFIX`：key 前缀（默认 `rl`）
- `RATE_LIMIT_REDIS_KEY_TTL_SEC`：key TTL（默认 600）

生产环境使用多个 Uvicorn worker 时，启动检查会要求启用 Redis 分布式限流；Kubernetes 多 Pod 部署无法由单个进程感知，必须在 Helm values 中显式设置 `RATE_LIMIT_REDIS_ENABLED=true` 并提供共享 `REDIS_URL`。

触发时的 `scope`：

- `rate_limit:api`
- `rate_limit:chat`

---

## 2) 租户级 QPS 配额（Tenant QPS quota）

作用：按 tenant 做 QPS 上限（保护共享依赖；多租户场景常用）。

配置：

- `TENANT_QPS_QUOTA_ENABLED`：是否启用（bool）
- `TENANT_QPS_QUOTA_REQUESTS_PER_SECOND`：tenant 维度 RPS（float）
- `TENANT_QPS_QUOTA_BURST_SIZE`：突发容量（int；<=0 时会按 rps*2 估算）
- `TENANT_QPS_QUOTA_MODE`：`block` / `warn`

分布式：

- 复用 `RATE_LIMIT_REDIS_ENABLED=true` + `REDIS_URL`
- `TENANT_QPS_QUOTA_REDIS_PREFIX`：key 前缀（默认 `tq`）
- `TENANT_QPS_QUOTA_REDIS_KEY_TTL_SEC`：key TTL（默认 600）

生产环境多 worker 或多 Pod 启用租户 QPS 配额时，Redis 是必需项，否则各进程会分别计数。

触发时的 `scope`：

- `tenant_qps:chat`
- `tenant_qps:retrieval`

---

## 3) Chat token 配额（成本治理）

作用：限制 tenant 在滚动窗口内的 **assistant tokens** 消耗（成本治理）。

配置：

- `CHAT_ASSISTANT_TOKEN_QUOTA_ENABLED`：是否启用（bool）
- `CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT`：窗口内 token 上限（int）
- `CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS`：窗口小时数（默认 24）
- `CHAT_ASSISTANT_TOKEN_QUOTA_MODE`：`block` / `warn`

触发时的 `scope`：

- `chat_tokens`

---

## 4) Upload 配额（文档数 / 存储容量）

作用：对上传入口做“文档数 / 存储容量”保护，避免无限增长。
`multipart`、URL ingest、local HTML ingest 复用同一组 tenant 文档数 / 存储字节配额，
并且在持久化到对象存储前先检查；超额或 fail-closed 故障时会清理临时文件。

配置：

- `TENANT_DOC_QUOTA_ENABLED` / `TENANT_DOC_QUOTA_LIMIT`
- `TENANT_STORAGE_QUOTA_ENABLED` / `TENANT_STORAGE_QUOTA_LIMIT_BYTES`

触发时的 `scope`：

- `tenant_documents`
- `tenant_storage`

---

## 5) Embedding 工作量配额（rolling chars）

作用：限制 tenant 在滚动窗口内的向量化“工作量”（用字符数近似，避免细粒度计量的成本）。

配置：

- `TENANT_EMBED_CHAR_QUOTA_ENABLED`
- `TENANT_EMBED_CHAR_QUOTA_LIMIT`
- `TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS`
- `TENANT_EMBED_CHAR_QUOTA_MODE`：`block` / `warn`
- `TENANT_QUOTA_FAIL_CLOSED`：配额依赖异常时是否阻断入库；默认 `false` 保持兼容

说明：

- 默认 `TENANT_QUOTA_FAIL_CLOSED=false`：QPS、文档数、存储、embedding 配额的
  Redis / DB / 查询故障保持兼容 fail-open，但会记录低敏 metrics / audit 证据。
- 对计费或租户隔离边界要求严格的生产环境，建议显式设置
  `TENANT_QUOTA_FAIL_CLOSED=true`；QPS 会返回 `503`，文档上传配额会显式拒绝，
  embedding 配额会抛领域异常，并保留 `closed` 原因供重试与排障。

---

## 6) 429 响应形状（客户端如何处理）

当你看到 429，请优先查看：

- Header：`Retry-After`（秒）
- Body：`detail.retry_after_sec`、`detail.limit`、`detail.scope`

客户端建议：

1. 优先按 `Retry-After` 退避重试
2. 把 `scope` 打到日志/监控（用于定位是哪一类限流）

Runbook：`docs/deployment/runbook.md`（429 小节）
