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
- `RAG_CLAIM_VERIFIER_MODE`
  - `token_overlap`（默认）
  - `semantic_heuristic`（含数值/否定冲突检测）
  - `strict`（更严格 overlap + 冲突检查）

重点观测字段：

- `metrics.retrieval_contract_mode`
- `metrics.retrieval_contract_policy`
- `metrics.claim_verifier_mode`
- `metrics.claim_verifier_enable_contradiction_check`
- `metrics.claim_check_removed`
- `metrics.claim_evidence`

判读建议：

- `claim_check_removed > 0` 且 `claim_verifier_mode=semantic_heuristic`：通常是检测到数值冲突或否定冲突。
- `retrieval_contract_policy.enforce_visible_evidence_only=true`：回答会更保守，拒答率升高是预期行为。
- `retrieval_contract_policy.hard_fallback_enabled=true` 但仍空证据：优先检查 `document_ids/metadata_filter` 是否过窄。

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
