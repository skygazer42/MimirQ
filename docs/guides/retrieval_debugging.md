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
  - `grounded_strict`：一键启用 `evidence_strict + visible_evidence_only`，并固定 hybrid + cross-encoder 基线。
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
- `retrieval_trace.contract_diagnostics.must_recall`
- `query_debug.retrieval_contract.must_recall`

关键语义：

- `must_recall_strict` 不只是“空召回重试”，还会处理 **partial-miss**（有 citations 但缺关键 source key / anchor）。
- second-pass 成功补齐时，状态会变为 `partial_miss_recovered`。
- strict 模式下仍未补齐时，系统会触发 `abstain_reason=must_recall_failed`，避免“看似回答了但证据不完整”。

推荐排障顺序：

1. 先看 `must_recall_fail_reasons`（`missing_required_source_keys` / `missing_required_anchor_fields` / `secondary_pass_no_effect`）。
2. 再核对 request 里 `must_recall_expected_source_keys` 是否过窄或拼写不一致。
3. 对 TAG/DB rows 场景，检查 `CHAT_TAG_MUST_RECALL_SOURCE_KEY_MATCH` 与 `CHAT_TAG_DBROWS_SQL_FIRST_ENABLED` 是否按预期开启。

## 8) Evidence Capsule（有据可查）

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
