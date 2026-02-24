# LTR Reranker（XGBoost）指南

LTR（Learning-to-Rank）用于把多个检索信号（dense/bm25/lexical/sparse/KG 角色等）组合成一个可学习的排序函数。

本仓库提供的是一个 **可插拔、可回归** 的 xgboost LTR 骨架：
- deterministic tests 可跑通
- 生产默认不启用（必须显式配置 model path）

代码位置：
- `app/rag/reranker/ltr.py`
- `app/rag/reranker/factory.py`（provider wiring）

---

## 1) 特征规范（Feature Spec）

特征顺序必须稳定（训练与推理一致）：
- 见 `app/rag/reranker/ltr.py:LTRFeatureSpec.default()`

当前默认 spec 包含：
- `vector_score`
- `bm25_score`
- `lexical_score`
- `sparse_score`
- `base_score`
- `role_*` one-hot（用于把 query expansion/KG 注入等 “来源角色” 作为信号）

> 如果你修改了 feature spec，必须同时更新训练与推理侧，并通过回归测试锁住。

---

## 2) 训练模型（从 regression cases 生成训练数据）

脚本：`scripts/train_ltr_from_regression_cases.py`

它会：
1. 读取 regression case bundle（`mimirq.regression_cases.v1`）
2. 通过 Evidence API 拉取 `citations`
3. 用 `reference_sources.chunk_id` 给 citations 打 label（命中=1，否则=0）
4. 训练 xgboost 并输出模型文件（JSON bytes）

示例：

```bash
python scripts/train_ltr_from_regression_cases.py \
  --base-url http://localhost:8000/api/v1 \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id test-admin \
  --cases ./regression_cases.json \
  --out-model ./artifacts/ltr.json \
  --top-k 50 \
  --retrieval-mode hybrid \
  --score-threshold 0.0 \
  --num-boost-round 50
```

建议：
- 默认会把 retriever 内置 reranker 关闭（收集 pre-rerank candidates），避免 “用 rerank 训练 rerank” 的污染。
- `--max-negatives-per-case` 用于控制训练集规模与类别不平衡。

---

## 3) 启用 LTR（HybridRetriever 内置 reranker）

当你希望在 retriever 内部进行 LTR 精排：

```bash
ENABLE_RERANKER=true
RERANKER_PROVIDER=ltr
LTR_MODEL_PATH=./artifacts/ltr.json
RERANKER_TOP_N=30
```

说明：
- `LTR_MODEL_PATH` 必填；不设置不会启用（避免默认行为改变）。
- `RERANKER_TOP_N` 建议从 20-50 起步，用回归门禁观察 MRR/NDCG 的提升与 latency 成本。

---

## 4) 启用 LTR（Evidence API 的 post-fusion rerank）

如果你想在 retrieval-only Evidence API 上做后置精排实验：

```bash
EVIDENCE_POST_RERANK_ENABLED=true
EVIDENCE_POST_RERANK_PROVIDER=ltr
EVIDENCE_POST_RERANK_TOP_N=30
LTR_MODEL_PATH=./artifacts/ltr.json
```

输出体现：
- citations：`reranker_provider=ltr`、`rerank_score`、`retrieval_score`（best-effort）
- metrics：`evidence_post_rerank_*`（best-effort）

---

## 5) 生产化差距（需要额外工程）

当前训练目标是 `binary:logistic`（更像 pointwise 分类）。
生产级 LTR 通常需要：
- 按 query 分组的 pairwise/listwise objective
- hard negative mining
- 模型与特征版本治理
- A/B 与回归门禁策略

详见差距快照：`docs/plans/2026-02-24-retrieval-only-rag-gap-snapshot.md`。

