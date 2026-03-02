# Evidence Retrieval Gate（Retrieval-only 回归门禁）

这个 Gate 的目标是把 “Evidence API 的检索质量” 变成 **可回归、可量化、可在 CI 强制执行** 的 SLO。

适用范围：
- **只做召回证据**（`POST /api/v1/rag/retrieve`）
- 不依赖回答生成，不依赖 RAGAS/LLM（更适合 CI 与快速迭代）

---

## 1) 关键指标（retrieval-only）

这些指标都基于回归用例中的 `reference_sources`（ground truth chunk_id）与检索输出的 `citations[].chunk_id` 对比得到：

- `retrieval_recall`：召回率（命中证据 chunk 的比例）
- `retrieval_hit_at_{k}`：Hit@K（Top-K 是否命中至少一个证据）
- `retrieval_mrr`：MRR（证据首次出现的平均倒数排名）
- `retrieval_ndcg_at_{k}`：NDCG@K（二值相关性下的排序质量）
- `abstain_rate`：拒答占比（若启用了 abstain/visible-evidence-only）

实现位置（便于二次开发/对齐逻辑）：
- `app/rag/evaluation/evidence_retrieve_gate.py`
- 回归逻辑对齐的参考实现：`app/rag/evaluation/regression_sample_builder.py`

---

## 2) 如何在 CI/本地跑 Gate（推荐）

最推荐的方式是沿用现有 regression gate CLI，但把 `metrics` 置空字符串，让后端只跑 retrieval-only：

```bash
python scripts/regression_gate.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --metrics "" \
  --thresholds ./thresholds.v2.json
```

说明：
- `--metrics ""` 会触发 retrieval-only gate：只跑检索，计算 Recall/Hit/MRR/NDCG 等指标。
- `thresholds` 推荐使用 `mimirq.thresholds.v2`（支持 slice gate），详见 `docs/guides/regression_gate.md`。

---

## 3) 如何在代码层跑 “离线最小 Gate”（pytest）

仓库内有一个不依赖外部向量库/模型的离线回归测试，用于确保 Evidence orchestrator 的最小检索质量不回退：

```bash
pytest -q tests/test_evidence_api_offline_regression_gate.py
```

特点：
- 使用 in-memory BM25（确定性、无外部依赖）
- 直接调用 `app/rag/retrieval/orchestrator.py:run_retrieval`
- 在测试中用 `evidence_retrieve_gate` 计算指标并断言 SLO

---

## 3.5) Nightly：持续跑一组 ablation（cron/K8s CronJob）

如果你希望每天固定跑一组“检索配置消融”（top_k / retrieval_mode / channel weight 等），建议用仓库内置的 CLI：

```bash
# Dry-run：只输出计划（不写 DB）
python scripts/run_nightly_ablations.py \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --dataset-id <dataset_uuid> \
  --dry-run

# Execute：创建 ragas_regression_runs 并同步执行（默认 retrieval-only，不依赖 RAGAS/LLM）
python scripts/run_nightly_ablations.py \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --dataset-id <dataset_uuid> \
  --execute
```

说明：
- 脚本会为每个 ablation 创建一条 regression run，并在 `run.params` 写入：
  - `nightly: true`
  - `job_run_id: <timestamp>`
  - `ablation_key: baseline|topk50|keyword_only|vector_only`
- 结果可以直接在前端的 “检索消融” 页面查看 leaderboard/diff。

## 4) 常见调参建议（retrieval-only）

如果你看到 Recall/Hit 降低，通常按以下顺序排查：

1. **scope 是否正确**：dataset_id / document_ids 是否被 ACL 过滤成空
2. **top_k 是否足够**：Evidence discovery 常用 `recall50` / `coverage80`
3. **score_threshold 是否过高**：回归门禁建议从 `0.0` 起步
4. **fusion 策略**：`rrf` 往往比简单 linear 更稳（但要关注延迟与候选规模）
5. **KG 是否引入噪声**：
   - query expansion 是否漂移（实体类型过滤、min_weight）
   - chunk injection 是否过多（max_chunks）
