# Runbook 内容治理 SOP（作者 / 审核 / 更新 / 废弃）

本 SOP 用于治理 **runbook / 政策 / 处置手册** 类文档，目标是让知识库长期保持：

- **可追责**：每份关键文档都有明确 owner（负责人）
- **可审计**：关键字段变更可追溯
- **不过期**：有 review 周期 + 到期提醒 / 报表入口
- **可替换**：新版文档能明确 supersede 旧版，检索默认优先权威/最新

> 原则：不要依赖“大家记得更新”。把治理信息写进系统字段，并把日常巡检变成可自动化任务。

---

## 1) 角色定义（RACI 简化版）

- **Author（作者）**：写/改内容的人（可以是任何编辑者）
- **Owner（生命周期负责人）**：对内容有效性负责的人/团队（值写入 `lifecycle_owner`）
- **Reviewer（审核人）**：对关键 runbook/政策类内容做 review 的人（通常是 oncall lead / domain owner）
- **Ops（运维）**：推动周期性巡检、演练与复盘沉淀（不一定是内容专家）

建议：

- `lifecycle_owner` 用团队名或轮值标识（例如 `team:sre` / `team:platform` / `oncall:search`），避免写个人姓名导致离职后无人维护。

---

## 2) 字段与含义（对应系统内 Document 生命周期元数据）

MimirQ 对文档提供一组小而稳定的治理字段（不包含内容，PII-safe）：

- `lifecycle_owner`：负责人（建议写团队/角色）
- `review_due_at`：下次 review 截止时间（到期/临近可用于报表）
- `authority_level`：权威等级（0-100，数值越高越权威；建议对 runbook/政策类文档设置较高）
- `supersedes_document_id`：新版文档“取代”的旧文档 ID（用于检索偏好与去重）

编辑入口：

- UI：文档详情 Drawer（`lifecycle_owner` / `review_due_at` / `authority_level` / `supersedes_document_id`）
- API（RBAC 受限）：
  - `GET /api/v1/documents/{document_id}/lifecycle-metadata`
  - `PATCH /api/v1/documents/{document_id}/lifecycle-metadata`

示例（patch）：

```bash
curl -fsS -X PATCH \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  -H "Content-Type: application/json" \
  "$BASE_URL/api/v1/documents/<doc-uuid>/lifecycle-metadata" \
  -d '{
    "lifecycle_owner": "team:sre",
    "review_due_at": "2026-06-01T00:00:00Z",
    "authority_level": 80,
    "supersedes_document_id": null
  }' | jq .
```

审计建议：

- 生命周期字段 patch 会写审计日志（action：`document.lifecycle_metadata.patch`），便于合规与追责。

---

## 3) 建议的 review 周期（可按文档类型分层）

建议以“风险/变化频率”划分：

1. **高风险/高变更（每 2-4 周）**
   - 事故处置 runbook（IR）、回滚剧本、限流/降级策略
2. **中风险（每 1-3 个月）**
   - 备份/恢复、DR 演练、容量规划、告警阈值
3. **低风险（每 6-12 个月）**
   - 架构说明、历史背景、已稳定的操作流程

落地做法：

- 新建/更新文档时，总是设置 `review_due_at`
- 每次 review：更新 `review_due_at`（滚动向后）

---

## 4) 变更流程（建议最小闭环）

### 4.1) 新建关键 runbook/政策类文档

1. Author 完成初稿
2. 设置治理字段（至少 `lifecycle_owner` + `review_due_at`）
3. Reviewer 走一遍“可执行性校验”：
   - 命令是否完整？是否包含安全边界？
   - 是否给出失败时的回退路径？
4. 发布后，在 runbook 入口（`docs/deployment/runbook.md`）加入索引链接

### 4.2) 更新（修订）关键文档

1. 优先用“增量更新”（保持历史可读）
2. 更新后设置新的 `review_due_at`
3. 若变更影响重大（例如阈值/回滚策略），建议在审计日志或变更记录中同步（你们自己的流程）

### 4.3) 废弃 / 被替代（supersede）

当出现“新版取代旧版”时，推荐：

1. 新文档创建并发布
2. 在新文档上设置：
   - `supersedes_document_id = <old_doc_id>`
3. 保留旧文档（便于追溯），但避免继续作为默认检索来源：
   - 检索策略已倾向“更权威/更新的文档”（依赖 `authority_level` + `supersedes_document_id`）
4. 可选：在旧文档正文开头加一句“已被 XXX 取代”（减少误用）

---

## 5) 巡检入口（stale / due 文档报表）

### 5.1) API：按 dataset 列出到期/临期文档

```bash
curl -fsS \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  "$BASE_URL/api/v1/governance/datasets/<dataset-uuid>/stale-documents?mode=overdue&limit=50" | jq .
```

### 5.2) 自动化：每日 stale report（可写审计日志）

```bash
python scripts/run_stale_report_jobs.py --dry-run
python scripts/run_stale_report_jobs.py --execute --stale-after-days 30 --max-documents 5000
```

建议：

- 把 daily report 结果写入审计日志并接入告警/看板（你们的 SIEM / 日常巡检体系）

