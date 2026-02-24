# ColBERT Reranker（Late-interaction）指南

ColBERT（late-interaction）是一类用于 **证据精排** 的 reranker：它不是生成模型，而是对候选 chunks 做更细粒度的匹配与排序。

在 retrieval-only 场景里，它通常用于：
- 提升 Top-N 证据的排序质量（MRR / NDCG）
- 降低 “候选里有证据，但排得太靠后” 的问题

---

## 1) 当前实现的定位（重要）

仓库中的 `colbert` provider 是一个 **deterministic scaffolding**：
- 不下载模型
- 不构建真实 ColBERT 索引
- 主要用于把 “late-interaction rerank 的接口/数据流/测试闭环” 先打通

代码位置：
- `app/rag/reranker/colbert.py`
- `app/rag/reranker/factory.py`（provider wiring）

如果你要做生产级 ColBERT，需要另行实现真实模型与索引（见 `docs/plans/2026-02-24-retrieval-only-rag-gap-snapshot.md` 的后续建议）。

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

说明：
- `RERANKER_TOP_N` 建议不要太大（rerank 发生在候选融合之后，会线性增加开销）。
- 该 rerank 会在 `HybridRetriever._hybrid_search()` 的融合/去重之后执行。

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

## 4) 什么时候不该用？

- 候选本身就很少（Top-K 很小），rerank 的边际收益不明显
- 你更需要召回（Recall/Hit）而不是精排（MRR/NDCG）
- 你还没有用回归门禁锁住 “召回不退化”，先加 rerank 可能掩盖召回问题
