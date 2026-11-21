# SPARSE 实验检索已退出

项目已删除确定性 SPARSE 实验通道、编码器、本地索引、派生缓存、配置、命令参数和专属 CI。SPLADE 神经模型此前已退出，目前也不再保留测试提供方。

旧 `sparse_retrieval_enabled`、`sparse_retrieval_provider`、sparse 模式或融合通道的新执行会明确拒绝。请移除旧 `SPARSE_RETRIEVAL_*`、`MILVUS_NATIVE_HYBRID` 配置，并重新生成只含 vector、bm25、lexical 的调优产物；不会自动把旧配额分给其他通道。

当前全文索引和评分交给 [Milvus BM25](milvus_bm25.md)。Milvus 自身的 `SPARSE_FLOAT_VECTOR` 和倒排索引是其原生全文实现，继续保留。PostgreSQL 的全文、模糊和元数据精确匹配见 [词法查询](lexical_fallback.md)，融合与重排见 [融合说明](retrieval_fusion.md)。

历史 trace 的 `sparse_score` 仍可读取；旧磁盘索引文件不再加载，本轮不删除用户持久数据。
