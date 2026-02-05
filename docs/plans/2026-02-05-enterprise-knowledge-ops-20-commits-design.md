# Enterprise Knowledge Ops (Tags + Duplicates + Batch ACL/Move) (Design Notes)

**Date:** 2026-02-05

## Goal

在现有 FastAPI 能力不大改的前提下，补齐“企业级知识库运维”关键操作面板（对标 RAGFlow 的日常运维体验）：

- **文档 Tags（`metadata.user.tags`）**：可视化展示、单文档编辑、批量追加/移除/覆盖
- **重复文档治理**：在数据集内按 `file_sha256` 扫描重复组，**默认只做“归档其他副本”**（可回滚、低风险）
- **批量运维动作补齐**：批量更新文档访问控制（ACL）与批量移动数据集（Move），并把 denied/conflicts 明确反馈给操作者

> 说明（Corridor）：`AGENTS.md` 要求在生成代码前使用 Corridor MCP 做安全分析，但当前环境未配置 `corridor` MCP server；本轮以**人工安全审计 + 前端单测/类型检查**替代。

## Direction (Interface Design)

**Who:** 知识库管理员/数据团队/工程师（企业内部），需要在高频入库与治理迭代中快速定位问题、批量处理、保留审计线索。

**Feel:** Ops 工具台（Calm & Safe）。默认保守、反馈明确、可回滚优先；不追求花哨装饰。

**Signature:** “Safe Sweeps”——把高风险动作收敛为：
- 先**预览/统计**
- 再**强确认（AlertDialog）**
- 最后**分批执行 + 明确结果汇总**（updated/denied/not_found/conflicts）

**Rejecting defaults:**
- 拒绝“一键删除重复文档”作为默认（默认归档）
- 拒绝批量操作的“静默部分失败”（必须展示 denied/conflicts）
- 拒绝把运维能力堆到单文件里继续膨胀（尽量组件化拆分）

## Data Model & APIs

### Tags（用户可编辑）

- 存储：`documents.metadata.user.tags: string[]`
- 写入：
  - 单文档：`PATCH /api/v1/documents/{id}/metadata`（`DocumentUserMetadataPatchRequest`）
  - 批量：优先用 `POST /api/v1/documents/batch/metadata`（当 patch 可统一时）；对“追加/移除”这种需要按文档计算的操作，用并发受控的 per-doc patch（避免引入新后端接口）

### Duplicates（重复文档）

- 扫描：`GET /api/v1/documents/duplicates?dataset_id=...`（按 `metadata.file_sha256` 分组，已含 ACL 裁剪）
- 治理：本轮默认策略
  - **保留最新（created_at 最大）的一份**
  - 其余副本：`batchArchive`
  - 可选：对被归档副本写入 `metadata.user.duplicate_of` / `duplicate_sha256` 等运维标记（best-effort）

### Batch ACL / Move

- ACL：`POST /api/v1/documents/batch/access`
- Move：`POST /api/v1/documents/batch/move`（后端会返回 conflicts：processing/minio/img_ids 等）

## UX / Safety Guardrails

- 默认上限：对批量“逐文档 patch”的操作做数量限制（例如 50），防止误操作扩散。
- 破坏性/不可逆动作一律 `AlertDialog`；**归档**作为重复治理默认动作。
- 对批量接口的返回：必须落地到 UI（成功数量 + 失败 ID 列表 → 映射成文件名/原因提示）。
- 仅使用项目既有 primitives（Radix/shadcn + Tailwind tokens），不引入新交互系统。

## Testing Strategy

- `vitest`：覆盖
  - tags 规范化/解析/patch 计算（纯函数）
  - duplicates “keep + archive others” 规划逻辑（纯函数）
- `pnpm -C web run verify` 作为本轮主要回归门禁（lint/ui-check/typecheck/tests/api-check）。

