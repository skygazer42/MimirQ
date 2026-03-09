# ColBERT Reranker（Late-interaction）指南

ColBERT（late-interaction）是一类用于 **证据精排** 的 reranker：它不是生成模型，而是对候选 chunks 做更细粒度的匹配与排序。

在 retrieval-only 场景里，它通常用于：
- 提升 Top-N 证据的排序质量（MRR / NDCG）
- 降低 “候选里有证据，但排得太靠后” 的问题

---

## 1) 当前实现的定位（重要）

仓库中的 `colbert` provider 现在有两条路径：
- `deterministic`：默认值，不下载模型，用稳定 hash 向量做 late-interaction 脚手架
- `hf`：显式 opt-in，按 token 调 Hugging Face 模型做真实 embedding，再走 late-interaction 打分

代码位置：
- `app/rag/reranker/colbert.py`
- `app/rag/reranker/factory.py`（provider wiring）

说明：
- 当前 provider tier：
  - `colbert + deterministic`：`offline_only`
  - `colbert + hf`：`experimental`
- `hf` 路径是 reranker 级别的真实模型接入，不是完整 ColBERT 训练/索引体系
- 如果你要做全量生产级 ColBERT 召回，仍然需要单独建设索引、部署和容量策略
- 当前建议的 production baseline 不是 ColBERT，而是 `retrieval_profile=hybrid_ce`

另：仓库还提供一个可选的候选召回通道脚手架（ANN + 持久化索引），见：
- `docs/guides/colbert_ann_retrieval.md`

---

## 2) 如何启用（HybridRetriever 内置 reranker）

当你希望 “检索融合后，在 retriever 内部 rerank”：

环境变量（示例）：

```bash
ENABLE_RERANKER=true
RERANKER_PROVIDER=colbert
RERANKER_TOP_N=30
```

若要启用 HF token embedder，再加：

```bash
COLBERT_RERANK_PROVIDER=hf
COLBERT_RERANK_MODEL_NAME=colbert-ir/colbertv2.0
COLBERT_RERANK_DEVICE=cpu
COLBERT_RERANK_BATCH_SIZE=16
COLBERT_RERANK_MAX_LENGTH=256
```

说明：
- `RERANKER_TOP_N` 建议不要太大（rerank 发生在候选融合之后，会线性增加开销）。
- 该 rerank 会在 `HybridRetriever._hybrid_search()` 的融合/去重之后执行。
- 如果不配置 `COLBERT_RERANK_PROVIDER`，系统保持 deterministic fallback，不会偷偷下载模型。

---

## 3) 如何启用（Evidence API 的 post-fusion rerank）

当你希望对 `POST /api/v1/rag/retrieve` 的最终证据列表再做一次后置精排（常用于 evidence-first 平台实验）：

```bash
EVIDENCE_POST_RERANK_ENABLED=true
EVIDENCE_POST_RERANK_PROVIDER=colbert
EVIDENCE_POST_RERANK_TOP_N=30
```

该开关在 `app/rag/retrieval/orchestrator.py:run_retrieval` 中生效。

输出体现：
- citations 会携带 `reranker_provider=colbert`、`rerank_score`、`retrieval_score`（best-effort）
- metrics 会记录 `evidence_post_rerank_*` 字段（best-effort）

---

## 4) 如何离线评估它到底值不值得开？

先取 Evidence API 的 pre-rerank 候选，再在本地串接 `ltr` / `colbert` 管线：

```bash
python scripts/eval_rerank_pipeline_offline.py \
  --cases ./tmp/cases.json \
  --pipeline '[{"provider":"colbert","top_n":20}]' \
  --top-k 50 \
  --k 20 \
  --colbert-provider hf \
  --colbert-model-name colbert-ir/colbertv2.0 \
  --colbert-device cpu
```

脚本输出除了 baseline / pipeline 的平均指标，还会给出每个指标的 `wins/losses/ties` 计数。

判断方式：
- `MRR/NDCG` wins 明显大于 losses：说明 late-interaction 值得继续灰度
- `Recall/Hit` 没有明显提升但 losses 上升：说明你可能只是把本来可命中的证据排坏了
- deterministic 路径适合先做 wiring / 回归门禁，HF 路径才适合判断真实收益

## 5) 什么时候不该用？

- 候选本身就很少（Top-K 很小），rerank 的边际收益不明显
- 你更需要召回（Recall/Hit）而不是精排（MRR/NDCG）
- 你还没有用回归门禁锁住 “召回不退化”，先加 rerank 可能掩盖召回问题
