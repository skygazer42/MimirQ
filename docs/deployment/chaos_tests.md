# Chaos Tests（依赖故障演练）：Redis / MinIO / Milvus

本指南提供一组 **可控、安全边界明确** 的 chaos 场景，用于在 staging/DR 环境持续验证：

- 故障发生时系统是否能 **正确降级/报错**（不“假成功”）
- 告警/观测是否能 **及时暴露**（readiness / metrics / dashboard）
- 故障恢复后系统是否能 **回到健康状态**（readiness + smoke + index-audit）

> 强制原则：**不要在生产演练破坏性 chaos**。先在 staging/DR 演练，形成稳定流程后再讨论生产级混沌工程。

---

## 0) 安全边界（必须遵守）

- 只在隔离环境演练：独立 namespace / 独立 DB / 独立 bucket / 独立向量库
- 故障窗口短（建议 60-180s），并设置 `concurrencyPolicy=Forbid` 避免重复触发
- 每次演练必须记录证据（输出 JSON + 结论 + follow-up issues）
- 所有“执行破坏”的动作必须显式确认（脚本 `--execute`）

---

## 1) 演练通用前置：基线快照

1. 记录 readiness：

```bash
curl -fsS "$BASE_URL/api/v1/health/ready" | jq .
```

2. 记录聚合指标（admin-only）：

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/observability/rag-metrics/summary" | jq .
```

3. 记录配置指纹（用于恢复后对比）：

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/observability/config/snapshot" | jq .
```

---

## 2) 场景 A：Redis 故障（队列/缓存）

适用前提：

- 启用队列：`TASK_QUEUE_ENABLED=true`

### 2.1) 注入故障（示例：K8s 内部 Redis）

> 注意：本 repo 的 Helm chart 默认不安装 Redis。下面仅适用于你们把 Redis 部署在集群里（或有可控的测试 Redis）。

Dry-run：

```bash
python scripts/chaos_dependency_outage.py --namespace infra --resource deployment/redis --down-seconds 120
```

Execute：

```bash
python scripts/chaos_dependency_outage.py --namespace infra --resource deployment/redis --down-seconds 120 --execute
```

### 2.2) 预期现象（应当可观测）

- readiness 可能变为 503（取决于你们是否把 Redis 作为 hard dependency）
- 队列快照异常（admin-only）：
  - `GET /api/v1/observability/task-queue/snapshot`
- ingest 异步任务可能堵塞（若走队列）

### 2.3) 恢复验证

Redis 恢复后：

- readiness 回到 200
- 跑一次 DR verify（推荐）：

```bash
python scripts/dr_verify_restore.py --base-url "$BASE_URL" --tenant-id "$TENANT_ID" --out chaos_redis_verify.json
```

---

## 3) 场景 B：MinIO 故障（对象存储）

适用前提：

- 启用对象存储相关开关（例如 `MINIO_ENABLED=true`，具体以你们部署为准）

注入故障方式（按你们环境选择）：

- 集群内 MinIO：用 `scripts/chaos_dependency_outage.py` scale down
- 外部 MinIO/S3：用网络策略/防火墙/服务网格做短时阻断（更推荐）

预期现象：

- 上传/解析链路可能失败（应返回明确错误，而不是 silent success）
- readiness 可能变为 503（依赖不可用）

恢复验证：

- 重点验证“上传 → ingestion → 检索”端到端恢复（跑 smoke test / dr_verify_restore）

---

## 4) 场景 C：Milvus 故障（向量检索）

适用前提：

- `VECTOR_BACKEND=milvus`（或你们实际使用的向量库）

注入方式：

- 集群内 Milvus：scale down
- 外部托管：短时网络阻断（推荐）

预期现象：

- 检索延迟飙升或错误率上升（应能被 metrics/summary 捕捉）
- readiness 可能变为 503

恢复验证：

1. readiness 回到 200
2. smoke test 通过
3. index-audit（对关键 dataset）通过或在可接受范围内

---

## 5) 演练后产出（必须）

每次 chaos 演练必须沉淀：

- 演练日期/环境/场景（Redis/MinIO/Milvus）
- 故障窗口（down-seconds）
- 观测证据（summary/config snapshot/verify report）
- 发现问题与改进项（创建 beads issues）

