# ColBERT 实验召回已退出

项目已删除 ColBERT 的哈希向量实验通道、索引实现和相关 Mixin。当前 requirements 没有 ColBERT 神经模型依赖；原实验实现不提供真实 ColBERT 模型能力。

原 `COLBERT_*` 配置、专属命令参数和离线 fixture 已删除。请从部署配置中移除旧参数；现存索引文件不由本轮操作删除，也不再加载。

当前召回由 `app/rag/retrieval/recall` 持有，融合与排序归 `ranking`，模型/API 重排归 `reranking`。保留的向量、BM25 和可选稀疏通道见 [RAG 结构说明](../development/rag_structure.md)。

历史 trace 中的 `colbert_ann` 和 `colbert_score` 仍可读取，它们不再表示当前可执行通道。重排旧配置的处理见 [ColBERT 重排退役说明](reranking_colbert.md)。
