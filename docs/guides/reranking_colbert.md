# ColBERT 重排已退出

项目已删除 ColBERT 的确定性实验重排实现及工厂注册。当前 requirements 没有 ColBERT 神经模型依赖，不再提供 ColBERT 安装、启用或评测命令。

执行 `colbert` 或 `late_interaction` 重排配置会明确拒绝，不自动切换模型。已保存设置和历史分数仍可读取；使用旧配置的环境需要显式选择当前支持的 provider，或关闭重排。

重排实现及工厂归 `app/rag/retrieval/reranking`，通道/查询融合归 `ranking`，阶段顺序归 `stages`。当前职责与入口见 [RAG 结构说明](../development/rag_structure.md)，实验召回的退出范围见 [召回退役说明](colbert_ann_retrieval.md)。
