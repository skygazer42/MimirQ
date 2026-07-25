# Retrieval Debugging Cookbook

本指南面向开源贡献者，目标是快速回答三个问题：

1. 召回为什么下降了？
2. 排名为什么抖动了？
3. 哪个通道（vector / keyword / sparse / rerank）导致结果变化？

本文默认聚焦检索质量与可复现性，不展开安全议题。

---

## 0) 最小可复现实验环境

建议先使用最小栈启动：

```bash
make up-retrieval-dev
make api-ping
```

说明：

- `up-retrieval-dev` 只启 postgres + redis + api，默认 `LLM_MOCK_ENABLED=true`。
- 这样可以把问题范围收敛到“检索与排序逻辑”，避免外部模型依赖噪音。

---

## 1) 先跑一个稳定基线（5 秒内）

```bash
python scripts/run_sample_retrieval_benchmark.py --out runs/sample_bench.json
```

输出文件：`runs/sample_bench.json`

重点看 `summary`：

- `hit_at_k`
- `mrr`
- `ndcg_at_k`
- `avg_latency_ms` / `p95_latency_ms`

如果这一步都不稳定，优先排查本地环境差异（依赖版本、配置文件、向量后端设置）。

---

## 2) 用 Evidence API 看“单次请求为何命中”

先构造一个最小请求（只看检索）：

```bash
curl -sS -X POST "http://localhost:8000/api/v1/rag/evidence/retrieve" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "How does reciprocal rank fusion work?",
    "top_k": 10,
    "retrieval_mode": "hybrid"
  }' | jq .
```

重点字段：

- `citations[*].hit_type`
- `citations[*].retrieval_role`
- `citations[*].vector_score` / `bm25_score` / `sparse_score`
- `citations[*].rerank_score` / `rerank_score_calibrated`
- `metrics.retrieval_per_query[*].retriever_debug.channels`
- `metrics.evidence_post_rerank_*`

这些字段足够定位“召回没进来”还是“进来了但被重排压下去”。

### 2.1 Retrieval Contract 与 Claim Verifier 快速定位

Wave B 增加了 retrieval contract 与 claim verifier 的显式调试面，排查“为什么拒答/为什么被删句”时优先看这组字段。

请求侧可控参数：

- `rag_config.retrieval_contract_mode`
  - `deterministic_recall`：强制 hard fallback，优先保证“有可检索证据”。
  - `evidence_strict`：开启更严格的 evidence gate，证据不足时更倾向拒答。
  - `audit_trace`：保留默认行为但加强 trace/metrics 审计信息。
- `rag_config.retrieval_profile`
  - `grounded_strict`：一键启用 `evidence_strict + visible_evidence_only`，并固定 hybrid 检索；重排后端沿用部署配置的 `RERANKER_PROVIDER`。
- `RAG_CLAIM_VERIFIER_MODE`
  - `token_overlap`（默认）
  - `semantic_heuristic`（含数值/否定冲突检测）
  - `strict`（更严格 overlap + 冲突检查）
- `RAG_CLAIM_NLI_VERIFIER_ENABLED`
  - `false`（默认）：只使用本地 deterministic heuristic
  - `true`：当 heuristic 判定不支持时，允许再走一次受限 NLI fallback
- `RAG_CLAIM_NLI_VERIFIER_PROVIDER`
  - `none`（默认）
  - `openai_compatible`

重点观测字段：

- `metrics.retrieval_contract_mode`
- `metrics.retrieval_contract_policy`
- `metrics.claim_verifier_mode`
- `metrics.claim_verifier_enable_contradiction_check`
- `metrics.claim_nli_verifier`
- `metrics.claim_check_removed`
- `metrics.claim_check_removed_reasons[*].reason_code`
- `metrics.claim_check_removed_reasons[*].contradiction_type`
- `metrics.claim_evidence`

判读建议：

- `claim_check_removed > 0` 且 `claim_verifier_mode=semantic_heuristic`：通常是检测到数值冲突或否定冲突。
- `claim_check_removed_reasons[*].reason_code=overlap_insufficient`：通常是 lexical overlap 不足，优先检查 chunk 文本、引用范围和 query 改写。
- `claim_check_removed_reasons[*].reason_code=contradiction_numeric_mismatch`：claim 与 evidence 数值不一致。
- `claim_check_removed_reasons[*].reason_code=contradiction_negation_conflict`：claim 与 evidence 在否定语义上冲突。
- `metrics.claim_nli_verifier.enabled=true` 且 removed reason 里出现 `nli_*`：说明本地 heuristic 已失败，系统又走了一次 NLI fallback；这时要同时检查 provider 可用性和 prompt/模型稳定性。
- `retrieval_contract_policy.enforce_visible_evidence_only=true`：回答会更保守，拒答率升高是预期行为。
- `retrieval_contract_policy.hard_fallback_enabled=true` 但仍空证据：优先检查 `document_ids/metadata_filter` 是否过窄。

Claim verifier 模式选择建议：

- `token_overlap`
  - 适合：默认生产基线、最小成本路径、先看有没有明显回归
  - 风险：对语义改写/释义不敏感
- `semantic_heuristic`
  - 适合：希望更早拦住数值/否定类硬冲突
  - 风险：对证据文本质量更敏感
- `strict`
  - 适合：`grounded_strict` / 高风险问答 / 明确偏保守场景
  - 风险：拒答率更高，对 span/切块质量要求更高
- `NLI fallback`
  - 推荐只在 heuristic 已经失败的链路上作为补充，不建议替代 deterministic baseline
  - 默认关闭；开启后优先把它当成“减少误删句”的二次判定层，而不是主判定器

`grounded_strict` 排障最小清单：

- 确认 `metrics.retrieval_contract_mode=evidence_strict`
- 确认 `metrics.evidence_span_strict_enabled=true`
- 关注 `metrics.evidence_span_missing_citations` 是否持续偏高（通常意味着解析/切块 span 质量不足）
- 若 `abstain_triggered=true` 频率异常，先修复证据链质量，再考虑回退 profile

---

## 2.2 Hierarchy Recall Overlay（层级召回）快速定位

当你遇到“chunk 命中不稳定，但其实命中的是同一段落/同一章节附近”的问题时，可以用 hierarchy recall overlay 做结构化的 recall 稳定性增强（不改变解析/索引存储模型，属于 retrieval overlay）。

### 如何开启

两种方式（二选一）：

1) 用 profile 一键开启（推荐做 ablation / 复现）：
- `rag_config.retrieval_profile=hierarchy_recall20`
- `rag_config.retrieval_profile=hierarchy_recall20_expand`
- `rag_config.retrieval_profile=hierarchy_hybrid_ce`
- `rag_config.retrieval_profile=hierarchy_grounded_strict`

2) 在任意 profile 上显式开启（适合做局部对比）：
- `rag_config.enable_hierarchy_recall=true`
- 可配套：
  - `hierarchy_family_collapse`
  - `hierarchy_family_aggregation`（`frequency|score|combined`）
  - `hierarchy_tree_dedup`
  - `hierarchy_overfetch_factor`
  - `hierarchy_parent_depth` / `hierarchy_sibling_window`（上下文扩展）

### 重点看哪些字段

在 `/api/v1/retrieval/explain`：
- 顶层 `hierarchy_recall`：快速确认是否启用以及关键 knobs 生效情况。
- `query_debug.hierarchy_recall`：包含 `tree_dedup_meta` 与 `context_expansion_*` 的详细诊断信息。

在 Evidence API（`/api/v1/rag/evidence/retrieve`）返回的引用里：
- `citations[*].retrieval_role`
  - `main`：主召回候选（应承担“主证据”职责）
  - `hierarchy_parent` / `hierarchy_sibling`：层级上下文扩展的“补充上下文”（用于补齐前后文，不应成为 must-recall 的唯一锚点）

### 常见现象解释

- `family_collapse=true` 后 top-k 变“少”：
  - 这是预期行为，同一 family 的重复候选会被折叠。
  - 建议结合 `hierarchy_overfetch_factor`（或增大 `top_k`）保证最终可见候选数充足。
- `context_expansion_attempted=true` 但 `context_expansion_used=false`：
  - 常见原因：没有找到可用的 parent/sibling chunk，或扩展后被 tree-dedup / budget 丢弃。
- 开启扩展后 must-recall anchor-field 误判：
  - 必须保证 `main` 引用仍然包含必要锚点字段（span/page/char range 等）；层级扩展引用是“context-only”，不会替代主证据。

## 3) 常见故障分层诊断

### A. 召回缺失（应命中的 chunk 没出现）

优先检查：

- `retrieval_mode` 是否被错误设置为 `vector` 或 `keyword`
- `top_k` 是否太小
- `score_threshold` 是否过高
- `metadata_filter` / `document_ids` 是否把候选裁掉
- `metrics.empty_retrieval` 是否出现过滤信号

推荐动作：

- 对同一 query 依次跑 `keyword` / `vector` / `hybrid` 对比。
- 打开 `retrieval_per_query` 的通道计数，确认哪个通道产出了候选。

### B. 召回有，但排序错

优先检查：

- `rerank_score` 与 `retrieval_score` 的相对尺度差异
- 是否开启 `EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED`
- `metrics.evidence_post_rerank_score_calibration` 中 `moved_positions/top_changed`

推荐动作：

- 同 query 对比校准开关前后结果（A/B）。
- 观察 `rerank_score_calibrated` 是否符合预期。

### C. 同配置偶发抖动

优先检查：

- 缓存是否跨版本复用（尤其 post-rerank cache）
- 语料 token/fingerprint 是否变化
- 稀疏索引/ANN 索引是否命中持久化复用路径

推荐动作：

- 对比 `retrieval_trace.post_rerank.cache`
- 检查索引持久化目录时间戳与指纹变化

---

## 4) 回归与门禁（避免“修了又回退”）

日常建议最小组合：

```bash
pytest -q tests/test_retrieval_trace_schema_v1.py tests/test_retrieval_ablation.py
pytest -q tests/test_evidence_post_rerank_pipeline.py tests/test_rerank_score_calibration.py
```

需要切片/阈值门禁时：

```bash
python scripts/regression_gate.py --help
python scripts/run_nightly_ablations.py --help
```

---

## 5) 提 PR 时建议附带的最小证据

- 变更前后 `runs/sample_bench.json` 的 `summary` 对比
- 1-2 个代表性 query 的 `citations` + `metrics` 关键字段差异
- 若涉及 rerank：附 `rerank_score` 与 `rerank_score_calibrated` 变化

这样 reviewer 可以快速判断是“真实质量提升”还是“偶然命中”。

---

## 6) Index Consistency / Drift 排障

当 chunk patch / disable / delete 后出现“DB 改了但召回面没同步”的问题，优先确认索引一致性严格度：

- `INDEX_CONSISTENCY_STRICTNESS=off`
  - 只做 best-effort index 操作，不因为失败阻塞请求。
- `INDEX_CONSISTENCY_STRICTNESS=warn`
  - 请求继续成功，但会写 `index_operation_result` / `index_drift_markers`，并记录 durable drift item。
- `INDEX_CONSISTENCY_STRICTNESS=strict`
  - delete / disable 失败直接返回 `409`
  - patch 失败也会返回 `409`
  - 适合需要“DB 与检索面必须同步成功”的高风险环境

推荐排查路径：

1. 看 chunk 元数据里的 `index_operation_result`
2. 看 `index_drift_markers[*]`
3. 看 observability API：
   - `GET /api/v1/observability/index-drift?dataset_id=...`
   - `POST /api/v1/observability/index-drift/{id}/resolve`
4. 需要重放时运行：

```bash
python scripts/replay_index_drift.py \
  --tenant-id <tenant_uuid> \
  --dataset-id <dataset_uuid> \
  --execute \
  --out runs/index_drift_replay.json
```

手动 resolve 只适用于“你已经通过别的运维动作修好，并确认不需要再重放”的情况；否则优先保留 open 状态。

---

## 7) Must-Recall / Partial-Miss 合同排障（G1 + G2）

当你关心“数据明明在库里，为什么没被召回”，优先看这组字段：

- `metrics.must_recall_enabled`
- `metrics.must_recall_status`：`disabled|passed|partial_miss_recovered|failed`
- `metrics.must_recall_fail_reasons`
- `metrics.must_recall_missing_source_keys`
- `metrics.must_recall_second_pass_*`
- `metrics.must_recall_proof`
- `metrics.iterative_pass_*`
- `retrieval_trace.contract_diagnostics.must_recall`
- `retrieval_trace.contract_diagnostics.must_recall.proof`
- `retrieval_trace.iterative_pass`
- `query_debug.retrieval_contract.must_recall`
- `query_debug.retrieval_contract.must_recall_proof`
- `query_debug.iterative_pass`

proof 语义（`mimirq.must_recall_proof.v1`）：

- `status/passed`：合同最终状态（含 second-pass 之后）。
- `obligation_ledger`：`mimirq.recall_obligation_ledger.v1`，明确 required/matched/missing。
- `contract_fail_reason_taxonomy`：fail reason 的稳定 taxonomy 版本。

离线审计（推荐在 run detail artifact 上执行）：

```bash
python scripts/must_recall_proof_audit.py \
  --input artifacts/run.detail.json \
  --out artifacts/must_recall_proof_audit.report.json
```

Iterative pass rollout/回滚开关（默认安全）：

- `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS`（默认 `1`）
- `RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS`（默认 `500`）
- 需要快速回滚时，保留 `RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED=true` 也可仅把 `MAX_HOPS=1` 与较小 budget，避免多跳放大延迟。

---

## 8) Adaptive Router 策略发布与回滚（G4）

Adaptive Router 是 intent_router 之后的一层策略覆盖器，用来从离线评测产物生成轻量路由规则，不依赖 GraphRAG。

开关与策略：

- `RAG_ADAPTIVE_ROUTER_ENABLED=true|false`
- `RAG_ADAPTIVE_ROUTER_POLICY_PATH=ci/adaptive_router_policy.v1.json`
- 请求级覆盖：`adaptive_router=true` + `adaptive_router_policy={...}`

CI 产物生成：

```bash
python scripts/generate_adaptive_router_policy.py \
  --benchmark-report artifacts/sample_retrieval_bench.json \
  --out artifacts/adaptive_router_policy.v1.json
```

上线前检查：

- `query_debug.adaptive_router`
- `metrics.adaptive_router`
- `retrieval_trace.adaptive_router`

回滚策略（最小动作优先）：

1. 先关闭开关：`RAG_ADAPTIVE_ROUTER_ENABLED=false`
2. 若需要保留开关，回退策略文件到上一版（Git revert 或替换 `RAG_ADAPTIVE_ROUTER_POLICY_PATH`）
3. 观察 1-2 个关键 query 的 `adaptive_router.used` 与 `matched_rule_ids` 是否符合预期

关键语义：

- `must_recall_strict` 不只是“空召回重试”，还会处理 **partial-miss**（有 citations 但缺关键 source key / anchor）。
- second-pass 成功补齐时，状态会变为 `partial_miss_recovered`。
- strict 模式下仍未补齐时，系统会触发 `abstain_reason=must_recall_failed`，避免“看似回答了但证据不完整”。

推荐排障顺序：

1. 先看 `must_recall_fail_reasons`（`missing_required_source_keys` / `missing_required_anchor_fields` / `secondary_pass_no_effect`）。
2. 再核对 request 里 `must_recall_expected_source_keys` 是否过窄或拼写不一致。
3. 对 TAG/DB rows 场景，检查 `CHAT_TAG_MUST_RECALL_SOURCE_KEY_MATCH` 与 `CHAT_TAG_DBROWS_SQL_FIRST_ENABLED` 是否按预期开启。

## 9) Evidence Capsule（有据可查）

`/api/v1/rag/evidence/retrieve` 现在可返回 `evidence_capsule`（`mimirq.evidence_capsule.v1`），用于不可变回放与审计归档：

- capsule 包含 must-recall 合同状态、retrieval 合同策略、解析质量风险、citation hash 集合、retrieval trace。
- 每个 citation 包含 `citation_hash` 和 `evidence_anchor_hash`，便于后续 diff / replay。
- capsule 根对象包含 `capsule_hash`，用于完整性校验。

相关工具：

- 持久化 API：`POST /api/v1/evidence/capsules` / `GET /api/v1/evidence/capsules/{capsule_id}`
- 回放 CLI：
```bash
python scripts/replay_from_evidence_capsule.py \
  --capsule runs/evidence_capsules/<capsule_id>.json \
  --out runs/evidence_replay.json
```

---

## 10) KG Query-Mode Routing 排障（G7）

KG search 已加入 deterministic query-mode 路由（`local|global|drift|auto`），不依赖 GraphRAG。

关键配置：

- `KG_SEARCH_QUERY_MODE_DEFAULT=auto|local|global|drift`
- `KG_SEARCH_QUERY_MODE_CLASSIFIER_ENABLED=true|false`
- `KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS`
- `KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS`
- `KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS`

最小排障路径：

1. 看 `query_debug` 或 `kg_search` 返回里的 `query_mode.resolved`。
2. 看 `query_mode.reason_codes` 是否与 query 形态一致（如 `drift_pattern/global_pattern/local_pattern`）。
3. 看 `stats.query_mode*` 与 `kg.search.*` metrics 是否一致，确认不是缓存或路径分支导致。
4. 若线上需要稳定行为，临时强制 `query_mode=local|global|drift`，避免 `auto` 分类波动。

---

## 11) Contextual Follow-up Pass 排障（G8）

Contextual follow-up 是 orchestrator 中的一个可选二次召回通道：
- 从第一轮已命中的 docs 提取高信号 term。
- 组装一条 bounded follow-up query。
- 按独立 mode/top-k 再跑一次检索并并入候选。

关键配置：

- `RETRIEVAL_CONTEXTUAL_FOLLOWUP_ENABLED`
- `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE=hybrid|vector|keyword|mmr`
- `RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K`
- `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS`
- `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS`
- `RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS`

看哪些字段：

- `metrics.contextual_followup_*`
- `query_debug.contextual_followup`
- `retrieval_trace.contextual_followup`
- `retrieval_trace.retrieval.per_query[*].kind=contextual_followup`

常见现象与处理：

- `enabled=true` 但 `attempted=false`
  - 通常是首轮 docs 太少或没有提取到新 terms（`reason_codes` 会给出原因）。
- `attempted=true` 但 `used=false`
  - 二次检索没有带来去重后的新增候选，检查 `mode/top_k` 与 metadata 过滤范围。
- `added_docs>0` 但 `added_citations` 低
  - 可能被后续过滤（去重、evidence span strict、must-recall contract）裁掉，继续看 `retrieval_contract` 相关字段。
