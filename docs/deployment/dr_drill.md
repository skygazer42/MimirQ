# DR Drill（灾备演练）：恢复验证 Checklist + 自动化

本指南用于把“备份能做”升级为“恢复可验证”：每次演练都产出可复用的证据与结论，形成闭环。

目标：

- 恢复后 **服务可用**（readiness 200）
- 核心路径 **端到端可用**（ingest + query/chat）
- 向量索引 **一致性可接受**（index-audit）
- 权限/RBAC **未失效**（抽查）

---

## 0) 安全边界（必须遵守）

- **不要在生产环境做破坏性演练**（恢复/覆盖/回放数据都可能产生不可逆影响）
- 演练环境必须隔离：独立 namespace / 独立 DB / 独立对象存储 bucket（或只读快照）
- 所有“执行写入”的命令必须明确标注（例如 `--execute`）

---

## 1) 演练前准备

1. 明确 RTO/RPO 目标（你们自己定义）
2. 准备备份：
   - Postgres dump（必备）
   - MinIO bucket mirror/snapshot（若启用对象存储）
   - 向量库（Milvus/Chroma）备份或重建策略
3. 确认演练环境的 Secret/配置齐全（DATABASE_URL / VECTOR_BACKEND / MINIO_* / REDIS_*）

参考：`docs/deployment/backup_restore.md`

---

## 2) 恢复步骤（高层）

1. 恢复 Postgres
2. 恢复 MinIO（若启用）
3. 恢复或重建向量库
4. 启动 MimirQ（Helm 或 Compose）

---

## 3) 恢复后验证（Checklist）

### 3.1) Readiness

```bash
curl -fsS "$BASE_URL/api/v1/health/ready" | jq .
```

期望：

- HTTP 200
- JSON `ok=true`

### 3.2) 端到端 smoke test（合成数据，PII-safe）

```bash
python scripts/smoke_test.py --help
```

建议把输出报告保存为演练证据（工单/文档附件）。

### 3.3) 索引一致性（index-audit）

对关键 dataset 做一次一致性检查（admin-only）：

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/observability/index-audit?dataset_id=<dataset-uuid>" | jq .
```

关注：

- `vector_id_missing`
- `vector_ids_missing_in_backend`
- `milvus_orphan_ids_sample`

### 3.4) 权限/RBAC 抽查（人工步骤，建议固定脚本化用例）

最小抽查建议（至少做 1 项）：

1. 用 **非 admin** 账号访问 admin-only 端点，期望 403：
   - `/api/v1/observability/rag-metrics/summary`
   - `/api/v1/observability/config/snapshot`
2. 检查一个“仅自己可见”的文档不会被他人检索到（ACL/security trimming 不回退）

---

## 4) 自动化脚本（推荐）

脚本：`scripts/dr_verify_restore.py`

它会按顺序跑：

1. readiness
2. `scripts/smoke_test.py`（写出 JSON report）
3. index-audit（对 smoke dataset 或你指定的 dataset）

最小示例（JWT 模式）：

```bash
export BASE_URL="https://mimirq.example.com"
export TENANT_ID="<tenant-uuid>"
export MIMIRQ_DR_ADMIN_TOKEN="<admin-jwt>"

python scripts/dr_verify_restore.py \
  --base-url "$BASE_URL" \
  --tenant-id "$TENANT_ID" \
  --out "dr_verify_report.json"
```

如果你要对生产数据集做检查（不跑 smoke）：

```bash
python scripts/dr_verify_restore.py \
  --base-url "$BASE_URL" \
  --tenant-id "$TENANT_ID" \
  --skip-smoke \
  --dataset-id "<dataset-uuid>"
```

输出：

- 标准输出：单行 JSON（适合 CI/日志采集）
- `--out`：写入可读的 JSON 报告文件

---

## 5) 演练结果沉淀（强烈建议）

每次演练建议至少记录：

- 演练时间、参与人、环境
- 本次使用的备份版本（dump 文件名 / bucket snapshot id）
- `dr_verify_report.json`（或等价证据）
- 发现的问题与后续改进项（创建 beads issue）

