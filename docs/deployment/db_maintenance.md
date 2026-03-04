# DB Maintenance 指南（VACUUM/ANALYZE + Retention）

本指南面向运维自动化：提供一个 **统一入口** 来跑数据库维护（Postgres VACUUM/ANALYZE）与现有的 retention jobs（审计日志 / regression runs）。

目标：

- **可重复执行（idempotent）**：脚本可安全重复跑
- **默认安全（safe-by-default）**：支持 dry-run；可选 table allowlist（防误操作 / 防注入）
- **日志清晰**：统一输出 JSON（适合 CronJob / 采集）

---

## 1) CLI：`scripts/run_db_maintenance_jobs.py`

脚本位置：`scripts/run_db_maintenance_jobs.py`

支持操作：

- Postgres：`VACUUM` / `ANALYZE`（可组合为 `VACUUM (ANALYZE)`）
- retention：审计日志 / regression runs（按 tenant 维度，bounded delete）

### 1.1) Dry-run（推荐先跑）

只输出计划，不做写入：

```bash
python scripts/run_db_maintenance_jobs.py --vacuum --analyze --dry-run
python scripts/run_db_maintenance_jobs.py --audit-logs --dry-run --retention-days 90
```

输出为单行 JSON：

- `ok`: 聚合状态
- `results[]`: 每个子 job 的摘要（PII-safe）

### 1.2) Execute（执行）

> 重要：`VACUUM` 会产生 IO/CPU 压力，建议低峰跑，并设置 `concurrencyPolicy=Forbid` 避免并发。

```bash
python scripts/run_db_maintenance_jobs.py --vacuum --analyze --execute
python scripts/run_db_maintenance_jobs.py --audit-logs --execute --retention-days 90 --max-delete 100000
```

### 1.3) Table allowlist（可选）

如果你只想维护少量表（降低风险），可传 `--table`（可重复）：

```bash
python scripts/run_db_maintenance_jobs.py --vacuum --analyze --table documents --table document_chunks --dry-run
```

支持 `table` 或 `schema.table`。为安全起见，脚本会对 identifier 做保守校验，非法输入会报错并返回 `ok=false`。

### 1.4) 多租户（retention）

retention jobs 支持：

- 默认 tenant（`DEFAULT_TENANT_ID`）
- 指定 tenant：`--tenant-id <uuid>`
- 全部 tenant：`--all-tenants`（慎用）

```bash
python scripts/run_db_maintenance_jobs.py --audit-logs --all-tenants --dry-run
```

---

## 2) Helm / Kubernetes：CronJob 模板

Chart 提供可选 CronJob 模板：

- `deploy/helm/mimirq/templates/cronjob-db-maintenance.yaml`

values 配置入口：

- `deploy/helm/mimirq/values.yaml` → `cronjobs.dbMaintenance`

最小示例（建议先 dry-run）：

```yaml
cronjobs:
  dbMaintenance:
    enabled: true
    schedule: "0 3 * * 0"   # 每周日 03:00（以 control-plane 时区为准，常见为 UTC）
    execute: false          # 先 dry-run
    vacuum: true
    analyze: true
```

执行版本（写入）：

```yaml
cronjobs:
  dbMaintenance:
    enabled: true
    execute: true
    vacuum: true
    analyze: true
    auditLogs: true
    retentionDays: 90
    maxDelete: 100000
```

---

## 3) 可观测性 / 审计建议

- retention jobs 会写 audit log（best-effort）：
  - `audit.logs.retention`
  - `evaluations.regression_runs.retention`
- CronJob 输出 JSON 适合直接被日志采集系统收集（ELK / Loki / Cloud Logging）。

---

## 4) 常见问题

### 4.1) 非 Postgres 环境

当 `DATABASE_URL` 不是 Postgres 时，VACUUM/ANALYZE 会被自动 skip，并在结果里标注 `skipped=true`。

### 4.2) VACUUM 为什么需要 AUTOCOMMIT？

Postgres 的 `VACUUM` 不能在事务里执行。实现里通过 SQLAlchemy connection 使用 `AUTOCOMMIT` 来保证兼容性。

