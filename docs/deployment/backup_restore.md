# 备份 / 恢复指南（Postgres + MinIO + Vector Backend）

本指南用于把 MimirQ 的核心数据做成可演练的备份/恢复闭环，覆盖：

- Postgres（元数据/审计日志/评估结果等）
- MinIO（对象存储：文档/图片等，取决于部署开关）
- 向量库（Milvus / Chroma 等，取决于 `VECTOR_BACKEND`）

> 重要：不同团队的合规/成本/恢复时长（RTO/RPO）目标不同。你需要先明确：哪些数据必须“原样恢复”，哪些可以“恢复后重算”。

---

## 0) 建议的策略（先选一种）

### 策略 A：Postgres + MinIO 备份，向量库可重建（推荐默认）

适用：数据规模中等、可接受重建索引时间，或向量库没有强一致的备份方案。

- 必备：Postgres 备份 + MinIO 备份
- 可选：向量库不做备份；恢复后触发 re-ingest / re-embed 重建

优点：

- 备份简单、可移植
- 恢复链路清晰

风险：

- 大规模数据集重建索引耗时（RTO 变长）

### 策略 B：Postgres + MinIO + 向量库全量备份（大规模/严格 RTO）

适用：向量库数据量巨大、重建成本高、RTO 要求严格。

优点：

- 恢复后可快速恢复检索能力

风险：

- 向量库备份/恢复通常更复杂，需要严格测试（避免“备份能做但恢复不可用”）

---

## 1) Postgres（必备）

### 1.1) 备份（pg_dump）

建议使用 **custom format**（可并行恢复）：

```bash
export PGHOST="<pg-host>"
export PGPORT="5432"
export PGUSER="<pg-user>"
export PGPASSWORD="<pg-password>"
export PGDATABASE="mimirq"

mkdir -p backups/postgres
pg_dump -Fc -Z 6 -f "backups/postgres/mimirq.$(date -u +%Y%m%dT%H%M%SZ).dump"
```

建议：

- 生产建议用只读专用账号（最小权限）
- 备份文件必须加密并妥善存储（对象存储 + KMS）

### 1.2) 恢复（pg_restore）

> 恢复建议在隔离环境（staging / DR 环境）先演练，再用于生产灾备。

```bash
export DUMP_FILE="backups/postgres/mimirq.<timestamp>.dump"

# 先建库（按你们规范）
createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" mimirq

# 再恢复（可加 --clean 覆盖旧对象；生产慎用）
pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d mimirq --no-owner --no-privileges "$DUMP_FILE"
```

---

## 2) MinIO / S3（可选但强烈建议：当启用对象存储时）

### 2.1) 备份（mc mirror）

前置：安装 `mc`（MinIO client）。

```bash
mc alias set mimirq-minio https://<minio-endpoint> <access_key> <secret_key>

mkdir -p backups/minio
mc mirror --overwrite --remove --md5 mimirq-minio/<bucket-name> backups/minio/<bucket-name>
```

建议：

- 分 bucket 做备份（更易管理与演练）
- 备份应具备版本控制/不可变（WORM）能力（按你们合规要求）

### 2.2) 恢复（mc mirror 回放）

```bash
mc mirror --overwrite backups/minio/<bucket-name> mimirq-minio/<bucket-name>
```

---

## 3) 向量库（Milvus / Chroma / 其他）

### 3.1) 原则：先确认你们的 `VECTOR_BACKEND`

MimirQ 运行依赖向量库实现检索。向量库数据是否“必须备份”，取决于：

- 是否可接受恢复后重建索引（策略 A）
- 索引构建成本与时间窗口
- 是否有成熟的备份工具链（不同向量库差异巨大）

### 3.2) Milvus（示例建议）

Milvus 的备份/恢复通常要依赖你们的部署方式（standalone / cluster）与其配套存储（ETCD、对象存储等）。

建议：

1. 优先在 **DR/staging** 验证“备份文件 → 新集群恢复 → index-audit 通过”
2. 没有成熟备份链路时，采用策略 A：向量库可重建，并在 DR 演练中验证重建流程与耗时

### 3.3) Chroma（示例建议）

若使用 Chroma 并开启持久化目录，通常可通过 **持久化卷快照** 完成备份（具体取决于你们的存储类）。

建议：

- 定期对 Chroma 挂载卷做 snapshot（同样需要演练验证）

---

## 4) 恢复演练（必做：验证“可恢复”）

### 4.1) 演练频率建议

- 每月至少一次在 staging/DR 环境做完整恢复演练
- 重大版本升级/存储迁移后必须做演练

### 4.2) 最小演练步骤（Checklist）

1. 恢复 Postgres（§1）
2. 恢复 MinIO bucket（§2，若启用）
3. 恢复/重建向量库（§3）
4. 启动 MimirQ（Helm / Compose）
5. 验证：
   - Readiness：`GET /api/v1/health/ready`
   - smoke test：`python scripts/smoke_test.py ...`
   - index consistency：`GET /api/v1/observability/index-audit?dataset_id=...` 或 `python scripts/run_periodic_audit_jobs.py --index-audit ...`

> DR drill 的更完整流程与自动化脚本：见 `MimirQ-eh26.39` 任务产出（恢复验证 checklist + automation）。

