# Incident Response Cookbook（MimirQ）

本 cookbook 目标是把“常见事故 → 采集证据 → 排障操作 → 回滚/恢复 → 复盘沉淀”串成一个 **可执行** 的流程（尽量 PII-safe、可自动化）。

适用对象：owner / admin / ops（具备 RBAC 权限 + 生产变更权限）。

> 原则：**先止血，再定位，再验证修复**。事故处理过程中不要复制/传播原始 query 或文档内容；优先用 `request_id`、hash、聚合指标和脱敏快照。

---

## 0) 你需要准备的信息

- `BASE_URL`：服务地址（例如 `https://mimirq.example.com`）
- `TENANT_ID`：租户 UUID（建议总是显式传 `X-Tenant-ID`）
- `ADMIN_TOKEN`：管理员 JWT（或按你们部署的 AUTH_MODE）
- （可选）`DATASET_ID`：受影响的数据集 UUID
- （可选）`REQUEST_ID`：一次异常请求的 request_id（强烈推荐）

下面示例默认使用：

```bash
export BASE_URL="https://mimirq.example.com"
export TENANT_ID="<tenant-uuid>"
export ADMIN_TOKEN="<admin-jwt>"
```

---

## 1) 5 分钟快速分诊（Triage）

### 1.1) 先看 Readiness：是否依赖挂了？

```bash
curl -fsS "$BASE_URL/api/v1/health/ready" | jq .
```

- `200`：依赖都 OK（不代表无问题）
- `503`：通常是 Postgres / Redis / 向量库 / MinIO 等依赖异常 → 先恢复依赖（最优先）

### 1.2) 看聚合观测：SLO/错误/zero-hit 是否异常

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/observability/rag-metrics/summary" | jq .
```

关注：

- latency（p95/p99）
- error rate
- zero-hit rate（`citations_count=0`）

### 1.3) 对比配置指纹：是否“刚刚变更”导致？

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/observability/config/snapshot" | jq .
```

用途：

- 事故期间对比两次 `fingerprint` 是否变化（配置漂移）
- 用于复盘：把“当时配置”存档（脱敏）

---

## 2) 证据采集（PII-safe 优先）

### 2.1) request_id 一键诊断包（强烈推荐）

如果你拿到了一个异常 `request_id`，优先导出 bundle：

```bash
python scripts/incident_bundle.py \
  --base-url "$BASE_URL" \
  --tenant-id "$TENANT_ID" \
  --token "$ADMIN_TOKEN" \
  --request-id "<request-id>"
```

bundle 通常包含：

- trace bundle（PII-safe）
- config snapshot（脱敏）
- 关键聚合指标快照

### 2.2) Trace tail / diff（本地排查）

如果你在本地/容器里能访问 metrics JSONL（或已导出 bundle），可用：

```bash
python scripts/rag_trace_tail.py --help
python scripts/rag_trace_diff.py --help
```

用途：

- `rag_trace_tail.py`：快速看近期 trace 的结构化字段（默认 PII-safe）
- `rag_trace_diff.py`：对比两个 request 的差异（配置指纹 / 检索路径 / 引用数等）

---

## 3) 常见事故 → 操作手册

> 每个场景都遵循：**观察 → 收集证据 → 止血 → 定位 → 修复 → 验证**。

### 3.1) Readiness 503（依赖不可用）

观察：

- `GET /api/v1/health/ready` 返回 503

优先级：

1. Postgres（最致命）
2. 向量库（Milvus/Chroma）
3. Redis（若启用队列）
4. MinIO（若启用对象存储）

操作：

- 看依赖快照（admin-only）：

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/observability/diagnostics/deps" | jq .
```

> 如果你们没有暴露该端点或被网关挡住，至少要在基础设施层检查：连接、DNS、网络策略、证书、凭据。

止血：

- 若 Redis 崩且队列导致 ingest 堵塞，可临时关闭队列（配置回滚优先）：
  - `TASK_QUEUE_ENABLED=false`

验证：

- readiness 回到 200
- 再跑一次 smoke test（见 §4）

### 3.2) 检索延迟飙升（p99 / p95 异常）

观察：

- `rag_retrieval_elapsed_seconds` / `rag_rerank_elapsed_seconds` p95/p99 飙升
- 或前端明显卡顿/超时

证据：

- 导出 1-3 个异常 request 的 bundle（见 §2.1）
- 看 config snapshot 指纹是否变化（见 §1.3）

止血（从“低风险”到“高影响”）：

1. **限流 / 配额**：保护后端（减少雪崩）
2. **降级链路**：临时关掉最耗时的组件（例如 reranker / multi-query / query rewrite）
3. **扩容**：API/worker/向量库/Redis/Postgres（按瓶颈）

验证：

- `/api/v1/observability/rag-metrics/summary` 指标回落
- 采样若干 request_id 验证尾延迟

### 3.3) zero-hit 率上升 / 检索质量骤降

观察：

- `rag_zero_hit_total` 增长异常
- 用户反馈“答不上来/引用为空”

证据：

- Query analytics（zero-hit/slow/error）：

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/observability/rag-metrics/query-analytics" | jq .
```

- 对比配置指纹（§1.3）

定位：

1. **索引一致性**：跑 index-audit（dataset 维度）
2. **过滤/ACL**：看候选是否被权限或 filter 截断
3. **回滚最近配置/版本**：优先回滚“可配置项”

操作（index-audit，admin-only）：

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/observability/index-audit?dataset_id=<dataset-uuid>" | jq .
```

（可选）如果你更倾向于 CronJob/脚本方式，也可用：

```bash
python scripts/run_periodic_audit_jobs.py --index-audit --dry-run --tenant-id "$TENANT_ID"
```

### 3.4) ingestion 堵塞 / 失败

观察：

- ingestion runs 状态持续 `processing`
- worker backlog 增长（若启用队列）

证据：

- 看队列快照（admin-only）：

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/observability/task-queue/snapshot" | jq .
```

止血：

- 优先恢复 Redis / worker
- 必要时暂停新 ingestion（避免“越写越乱”）

验证：

- 重新跑 smoke test（§4）

---

## 4) 恢复后验证（推荐标准化）

恢复依赖 / 回滚配置 / 修复 bug 后，建议立刻跑一遍 smoke test：

```bash
python scripts/smoke_test.py --help
```

生产建议：

- 上传内容使用合成文本（脚本默认就是）
- 只在专用 dataset 中跑（或让脚本自动创建/复用）
- 输出保存到工单/事故记录里（作为“修复验证证据”）

---

## 5) 回滚与复盘链接

- 回滚剧本（Runbook）：`docs/deployment/runbook.md` → “Rollback Playbook（回滚剧本）”
- 配置快照：`GET /api/v1/observability/config/snapshot`
- 事故证据打包：`python scripts/incident_bundle.py`
