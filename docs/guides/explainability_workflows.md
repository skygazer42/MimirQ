# 可解释性工作流（Explainability Workflows）

本指南描述 Wave20 的“可视化 + explainability workbenches”应如何串起来使用：
当你面对“为什么会这样？”的线上/离线问题时，应该先看哪个面板、再跑哪个对比、最后如何沉淀为可回归的证据与门禁。

典型问题包括：
- **为什么这次没召回证据？**（检索 miss / 融合预算 / 权限裁剪 / 索引不一致）
- **为什么引用变了？**（pipeline_hash 变更、切块漂移、rerank skip reason）
- **为什么 KG 漂移了？**（抽取配置变更、提示词变更、版本混用）
- **为什么入库吞吐下降/失败增多？**（解析器/队列/治理隔离、错误 taxonomy）
- **如何把一次排障沉淀成“可分享 + 可回归 + 可 gate”？**

> 说明：本文强调“流程与定位路径”，各单点能力的细节参数请参考对应专题文档。

---

## 0. 一句话总览：从症状到工具

按“你看到的现象”选入口：

1) **入库/解析问题** → `/knowledge/ingestion`（吞吐 + 错误原因）  
2) **检索 miss / evidence 不稳定** → `/knowledge/evidence`（retrieval-only） + `/history` 的 **RAG Trace**  
3) **对比两个方案/参数是否变好** → `/evaluations/ablations`（run/leaderboard/diff）  
4) **KG 漂移/关系不可信** → `/graph/snapshots`（规模漂移） + `/graph/diagnostics`（hardcase） + `/graph`（过滤+provenance）  
5) **需要导出/分享给他人复核** → `/reports`（HTML 报告） + Evidence Pack / regression artifacts

---

## 1. Workflow A：检索 miss（“应该有证据但没召回”）

目标：回答“**为什么没召回**”以及“**要怎么让它稳定召回**”。

### Step 1：用 Evidence Workbench 复现（不生成回答）

页面：`/knowledge/evidence`（Evidence Workbench）

你要确认三件事：
- `has_evidence` 是否为 true（系统认为是否存在证据）
- `citations[]` 的数量/得分分布是否异常（是否被阈值/融合预算截断）
- 是否出现了 `abstain_triggered`（被 guardrail 主动拒绝/保守）

下一步动作：
- **能召回但质量差/引用不稳**：进入 Step 2（RAG Trace）
- **完全召回不到**：优先检查 index 一致性与权限裁剪

相关参考：
- Evidence API：`docs/guides/evidence_api.md`
- Evidence Pack 沉淀闭环：`docs/guides/evidence_pack_to_regression.md`
- Index Audit：`docs/guides/observability_dashboard.md`

### Step 2：打开 RAG Trace 看“每个 channel 发生了什么”

页面：`/history` → 选中会话 → 点击 `RAG Trace`

RAG Trace 重点看：
- `retrieval_config_hash`：本次检索配置指纹（便于对比“是不是同一套配置”）
- per-channel 的候选数、分数与融合结果（例如 vector vs keyword vs kg/tag）
- **rerank 的 skip reason / error**：为什么没 rerank、或 rerank 失败导致排序异常

常见模式：
- rerank 被跳过：查看 `skip_reason`（例如没启用、预算不足、候选太少/太多）
- channel 候选很多但最终 citations 很少：通常是阈值/融合 cap 或 ACL trimming

相关参考：
- Metrics/Trace 开关与面板：`docs/guides/observability_dashboard.md`
- 检索融合策略：`docs/guides/retrieval_fusion.md`

### Step 3：把“应该召回的证据”导出为 Evidence Pack

仍在 `/knowledge/evidence` 中导出 Evidence Pack（JSON）。

Evidence Pack 的意义：
- 可分享：把“期望证据”发给同事/线上支持
- 可回归：转换为 regression cases，后续每次改检索都能自动验证

下一步动作：
- 转换为 regression cases：见 `docs/guides/evidence_pack_to_regression.md`

---

## 2. Workflow B：参数/方案对比（“到底哪个更好？”）

目标：回答“**这个改动对检索/回答质量是改善还是回归**”，并能输出可审计 artifacts。

页面：`/evaluations/ablations`（Retrieval Ablations）

推荐流程：
1) 选择 dataset（确保 scope 一致）
2) 创建新的 regression run（建议先 `retrieval_only=true` 跑快）
3) 在 runs 中选择 base/target，生成 diff
4) 用 leaderboard 指标快速排序（例如 `retrieval_mrr` / `retrieval_recall`）

技巧：
- 先用 retrieval-only 找到“召回是否变好”；再按需开启 RAGAS 指标看回答侧变化（更慢、更贵）
- diff 出现回归时，回到 Workflow A 的 RAG Trace / Evidence Workbench 看“原因属于哪一段”

相关参考：
- 离线脚本矩阵消融：`docs/guides/retrieval_ablation.md`
- 回归门禁：`docs/guides/regression_gate.md`
- 评测成熟度（从手工 QA → CI gate）：`docs/guides/evaluation_maturity_model.md`

---

## 3. Workflow C：KG 漂移与关系可信度（“图谱为什么变了？”）

目标：回答“**同一批文档在不同 pipeline_hash 下 KG 规模/类型为什么漂移**”，以及“关系边是否有证据支撑”。

### Step 1：先做 PII-safe 的规模对比（KG Snapshots）

页面：`/graph/snapshots`

输入：
- `pipeline_hash A / B`
- 可选 `document_ids`（用于把对比范围缩小到一小组文档）

产出：
- snapshot（计数 + 类型直方图）
- diff（`mimirq.kg_snapshot_diff.v1`）

如果 snapshots 显示明显漂移：
- 去 Step 2 做“hardcase 级别”的检索诊断（KG diagnostics）

相关参考：
- KG 基础与 snapshots API：`docs/guides/knowledge_graph.md`

### Step 2：用 KG Diagnostics 定位“哪些 case 变差了”

页面：`/graph/diagnostics`

KG diagnostics 会：
- 在一个 dataset 上抽样/生成用例（baseline + hardcases）
- 跑 KG 搜索并输出 hit/mrr/recall 之类的 summary
- 支持对比两个 runs，列出变动最大的 cases

使用建议：
- 先把 `max_cases` 控制在 50 左右跑通流程
- diff 出来后，把“变差的 case”拿去复现：回到 Evidence Workbench / RAG Trace 看链路

### Step 3：在 Graph UI 用过滤与 provenance 解释“这条边从哪来”

页面：`/graph`

Graph UI 用于回答：
- 这条 relation 的 predicate 是什么？
- 置信度大概在哪个 bucket？（high/medium/low）
- hover 一条边时的 tooltip 会展示 provenance（document/chunk/event、confidence、content_hash 等）

当图过大/太密时：
- 先用 predicate / entity type / confidence bucket 过滤缩小范围
- 再点选节点查看详情，避免“看起来很复杂但无法解释”

---

## 4. Workflow D：入库吞吐与失败诊断（“为什么最近失败变多了？”）

目标：回答“**入库失败的 top 原因是什么**”“**是不是某个解析器/治理规则导致 quarantined**”。

页面：`/knowledge/ingestion`（Ingestion Monitor）

你可以在这里看到：
- 文档状态分布：pending/processing/completed/failed/quarantined/cancelled
- 时间序列：窗口内 completed/failed/quarantined 的变化
- `top_error_reasons`：错误 taxonomy（适合一眼看出“最近挂在哪”）

推荐排查路径：
1) 先看 `top_error_reasons` 是否集中在某个解析器/依赖（例如外部 parser 服务不可用）
2) 点开失败/隔离的文档详情，确认是 content 问题还是系统性问题
3) 必要时用 `retry` 触发重试（验证是否为瞬态错误）

相关参考：
- 解析/依赖矩阵：`docs/guides/dependencies.md`
- 数据治理与隔离：`docs/guides/data_governance.md`

---

## 5. Workflow E：导出与分享（“怎么把诊断结果交付给别人复核？”）

目标：把一次排障变成**可分享 artifacts**，减少“口头描述”造成的信息损失。

### 5.1 导出 HTML 报告（面向 Review）

页面：`/reports`（Reports Center）

常见导出：
- Dataset Report HTML（概览 + 文件树 + 治理统计等）
- RAG Audit HTML（更偏质量/检索/引用侧审计）

建议：
- 生产环境导出前开启 `redact=true`（默认开启），避免敏感信息外泄
- 报告文件可作为 CI artifact 或 PR 附件

### 5.2 导出 Evidence Pack / Regression artifacts（面向回归）

从 Evidence Workbench 导出 Evidence Pack，再转 regression cases，最终进入 regression gate：
见 `docs/guides/evidence_pack_to_regression.md` 与 `docs/guides/regression_gate.md`。

---

## 6. Workflow F：从负反馈自动发现 hardcases（PII-safe）

目标：把“点踩/低分反馈”自动聚类成 **hardcase 候选**，让 reviewer 快速把它们沉淀到 EvidenceSuite（draft -> reviewed -> approved），最终进入 regression gate。

前置条件：
- `ENABLE_METRICS_LOG=true`（系统会从 metrics JSONL 的 `rag_trace` 记录里取 `question_hash` 等 PII-safe 指纹）
- 助手消息的 `message_metadata.request_id` 存在（用于把 feedback join 到 trace）
- suite 是 dataset-scoped；hardcase discovery 也会按 conversation.dataset_id 做隔离

步骤：
1) 获取 suite 的 hardcase candidates（PII-safe；不返回原始 query 文本）：

```bash
curl -X GET "http://localhost:8000/api/v1/evidence/suites/<suite_id>/hardcase-candidates?max_rating=2&max_candidates=50&window_minutes=10080" \
  -H "Authorization: Bearer <TOKEN>"
```

返回里你会拿到 `candidates[]`，每个候选簇包含：
- `question_hash`（聚类/去重 key）
- `cluster_size`（同类负反馈数量）
- `feedback_ids[]` / `request_ids[]`（reviewer 用来定位与转化的指针）
- `retrieval_config_hash` / `retrieval_error_kinds` / `rag_config_template` 等 PII-safe 元信息

2) reviewer 挑选一个 `feedback_id`，转成 draft EvidenceItem（进入 EvidenceSuite 的审批流）：

```bash
curl -X POST "http://localhost:8000/api/v1/feedback/messages/<feedback_id>/to-evidence-item" \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"suite_id":"<suite_id>","tags":["hardcase"],"extra":{"source":"hardcase_discovery"}}'
```

有界性说明（避免无界扫描）：
- traces 只读 JSONL 尾部（`max_bytes`）；窗口用 `window_minutes` 限制
- feedback 行数 `max_feedback_rows`，候选输出 `max_candidates`
- 返回 `truncated=true` 表示由于 tail 读取导致结果可能不完整

---

## 7. 常见反模式（避免浪费时间）

- **只看最终答案，不看 citations**：可解释性链路的入口是 evidence/citations，而不是 LLM 文本。
- **只看单次请求，不做对比**：没有 base/target diff，很难确定“变好还是变差”。
- **对资产接口做 HTTP 缓存调优**：文档/图片资产接口统一返回 `Cache-Control: private, no-store`（安全设计），浏览器通常不会自动复用缓存；显式发送匹配的 `If-None-Match` 时服务端仍可返回 304。图片加载统一走前端 `AuthImage`。
- **混用 pipeline_hash**：对比时务必确认 scope 与版本（尤其是 KG、文档下载/预览）。
