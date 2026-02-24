# Sparse Retrieval（SPLADE-style 通道脚手架）

MimirQ 的检索栈除了 dense vector 与 BM25，还支持一个可选的 **sparse retrieval channel**（SPLADE-style）。

定位：
- 这是一个 “额外的候选来源（candidate source）”，参与 `linear` / `RRF` 融合
- 当前实现提供 **deterministic provider**（无模型下载，便于单测/回归）
- 生产级 SPLADE（transformers/ONNX）可以作为后续 provider 增量引入，但必须 opt-in

---

## 1) 什么时候需要 sparse？

典型场景：
- acronym / 缩写：`k8s` vs `kubernetes`
- 领域同义词（不在 embedding 训练分布里）
- 需要 “可解释的词项匹配” 但 BM25 分词/同义词覆盖不足

sparse 的价值通常体现在 **召回**（降低 false negative），而不是直接替代精排。

---

## 2) 工作方式（当前实现）

代码位置：`app/rag/retriever.py` + `app/rag/retrieval/sparse.py`

当前 sparse 通道：
- 复用 BM25 的 in-memory corpus（同一 tenant/dataset/document scope）
- 对每个 chunk 构建 sparse 向量（token 权重）
- query 也编码成 sparse 向量
- 用 dot-product 得到稀疏相似度并取 Top-K

> 注意：因为当前实现复用 BM25 的 corpus 缓存，所以如果你的 scope 没有 BM25 文档缓存（未 upsert / 未 warm），sparse 通道也会是空的。

---

## 3) 配置项（Settings）

后端配置（见 `app/core/config.py`）：

- `SPARSE_RETRIEVAL_ENABLED`：是否启用 sparse 通道（默认 false）
- `SPARSE_RETRIEVAL_PROVIDER`：provider 名称（目前支持 `deterministic`）
- `SPARSE_RETRIEVAL_SYNONYMS`：deterministic provider 的最小同义词表
  - 格式：`"kubernetes:k8s,postgresql:postgres"`
  - 该映射是对称的（两边会互相扩展）

---

## 4) 召回结果如何体现？

当 sparse 通道启用并命中时：
- 最终 `citations` 中会包含 `sparse_score`
- `query_debug.channels.sparse` 会包含候选数与 provider（best-effort）

> `sparse_score` 仅表示 sparse 通道对该 chunk 的支持强度；最终排序仍由融合策略与（可选）rerank 决定。

---

## 5) Tradeoffs

启用 sparse 通道的常见代价：
- 额外的索引构建与内存占用（当前实现是 in-memory）
- 额外的候选融合开销（尤其在 RRF 时会增加排序工作）

建议：
- 先在 retrieval-only regression gate 上评估（Recall/Hit/MRR/NDCG）
- 用 slice（语言/文件类型/质量）观察 sparse 是否只在特定桶收益明显

