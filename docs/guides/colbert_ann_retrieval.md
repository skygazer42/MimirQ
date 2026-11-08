# ColBERT 确定性稠密候选召回

仓库保留一个默认关闭的 ColBERT-stack 实验通道，用确定性哈希向量和 NumPy 精确余弦评分生成候选。它适合离线回归和通道验证，可与受支持的 late-interaction reranker 组合使用。

当前提供方为 `deterministic`。HF/Torch 提供方已退出，不再配置本地模型、设备或模型 batch encode 参数。该实现按 chunk 保存一个稠密向量；完整 token-level ColBERT 检索需要独立的实现与质量评估。

## 代码入口

- `app/rag/retrieval/colbert_ann.py`：确定性 embedder、索引持久化、`resolve_colbert_retrieval_capability` 和 NumPy 评分。
- `app/rag/retrieval/hybrid/corpus_channels.py`：当前候选通道的 `search_colbert` 入口。
- `app/rag/retrieval/hybrid/colbert_index.py`：检索器已有的 `_search_colbert_dense` / `_search_colbert_dense_docs` 方法。
- `app/rag/retrieval/corpus_index.py`：发布语料快照与范围约束。
- `app/rag/retrieval/corpus_artifacts.py`：派生索引的缓存、加载和构建。

已有模块路径、`ColbertAnnIndex` / `ColbertAnnIndexStore` 类名、`mimirq.colbert_ann_index.v1` 持久化 schema 和 `colbert_ann` 诊断字段继续使用原名称，以保持索引及调用契约。

## 查询流程

1. vector 通道没有候选且显式启用该能力时，检索流程尝试确定性 ColBERT 候选通道。
2. `CorpusIndex.load_corpus_snapshot` 从数据库读取指定租户、数据集或文档范围内的发布语料。它使用独立的有界快照，不要求存在 BM25 文档缓存。
3. 按语料指纹和 provider 配置复用或构建稠密向量索引；允许持久化时，沿原格式加载和保存。
4. query 使用相同的确定性编码，NumPy 对范围内向量计算余弦 Top-K，再沿原路径生成候选及范围过滤。

## 配置与资源上限

配置由 `app/core/config.py` 持有：

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `COLBERT_RETRIEVAL_ENABLED` | `false` | 显式启用候选通道。 |
| `COLBERT_RETRIEVAL_PROVIDER` | `deterministic` | 保留的确定性提供方。 |
| `COLBERT_RETRIEVAL_EMBED_DIM` | `64` | 哈希稠密向量维度。 |
| `COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED` | `true` | 按既有 best-effort 策略持久化索引。 |
| `COLBERT_RETRIEVAL_INDEX_DIR` | `./data/colbert_indexes` | 索引目录。 |
| `COLBERT_RETRIEVAL_MAX_DOCS` | `10000` | 单 scope 的候选索引文档数量上限。 |

发布语料快照还遵守 `RETRIEVAL_REBUILD_MAX_CHUNKS` 的现有加载上限：计数检查和加载后复核超限会明确失败。`COLBERT_RETRIEVAL_MAX_DOCS` 用于通道构建前的数量检查，超限时返回 `skipped_reason=too_many_docs` 并清理该 scope 的派生索引缓存。

精确评分需要扫描该 scope 的稠密矩阵，成本随文档数量和维度增长。确定性结果用于验证工程链路，检索质量仍需在实际数据集上评估。

## 诊断与回归入口

现有诊断字段保持：

- `rag_trace.channels.colbert_ann.readiness`
- `rag_trace.channels.colbert_ann.skipped_reason`
- `rag_trace.channels.timing.colbert_ms`
- `rag_trace.channels.counts.colbert_candidates`

仓库的 bounded fixture 位于 `data/sample/retrieval_fixture_colbert_v1.json`，命令入口为：

```bash
python scripts/run_sample_retrieval_benchmark.py \
  --fixture data/sample/retrieval_fixture_colbert_v1.json \
  --out runs/sample_bench.colbert.json \
  --retrieval-mode vector \
  --enable-colbert-retrieval \
  --colbert-retrieval-provider deterministic
```

检查输出中的 provider、是否启用以及 `hit_at_k` / `mrr` / `ndcg_at_k`，并结合实际候选数和跳过原因判断通道是否运行。该夹具用于验证确定性回退流程，不代表生产数据质量验收。
