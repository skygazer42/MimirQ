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

另外：
- 支持可选 **持久化 sparse index**（按 scope + provider_config 哈希落盘），用于多进程/重启后的冷启动加速（best-effort）。

> 注意：因为当前实现复用 BM25 的 corpus 缓存，所以如果你的 scope 没有 BM25 文档缓存（未 upsert / 未 warm），sparse 通道也会是空的。

---

## 3) 配置项（Settings）

后端配置（见 `app/core/config.py`）：

- `SPARSE_RETRIEVAL_ENABLED`：是否启用 sparse 通道（默认 false）
- `SPARSE_RETRIEVAL_PROVIDER`：provider 名称（`deterministic` | `splade`）
- `SPARSE_RETRIEVAL_SYNONYMS`：deterministic provider 的最小同义词表
  - 格式：`"kubernetes:k8s,postgresql:postgres"`
  - 该映射是对称的（两边会互相扩展）

索引持久化（可选）：
- `SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED=true|false`（默认 true，best-effort）
- `SPARSE_RETRIEVAL_INDEX_DIR=./data/sparse_indexes`

SPLADE provider（可选，需显式配置模型）：
- `SPARSE_SPLADE_MODEL_NAME=...`（必填，空值会导致 provider 初始化失败）
- `SPARSE_SPLADE_DEVICE=cpu|cuda|auto`
- `SPARSE_SPLADE_BATCH_SIZE=8`
- `SPARSE_SPLADE_MAX_LENGTH=256`
- `SPARSE_SPLADE_TOP_K=128`
- `SPARSE_SPLADE_MIN_WEIGHT=0.0`

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
 - SPLADE provider 额外引入模型加载与推理成本（建议从小 batch + CPU 起步，先跑回归门禁观察收益）

建议：
- 先在 retrieval-only regression gate 上评估（Recall/Hit/MRR/NDCG）
- 用 slice（语言/文件类型/质量）观察 sparse 是否只在特定桶收益明显

---

## 6) 可观测性（Prometheus Metrics）

当 `PROMETHEUS_ENABLED=true` 时，sparse 通道会暴露一组 **低基数、PII-safe** 的指标，便于灰度与回滚判断：

检索侧：
- `rag_sparse_search_total{provider,outcome}`
- `rag_sparse_search_duration_seconds{provider,outcome}`
- `rag_sparse_search_candidates_count{provider,outcome}`

索引侧（持久化缓存 + 构建）：
- `rag_sparse_index_load_total{provider,outcome}`（`hit|miss|error|skipped`）
- `rag_sparse_index_save_total{provider,outcome}`（`ok|error|skipped`）
- `rag_sparse_index_build_duration_seconds{provider,kind,outcome}`（`kind=full|incremental`）

字段说明：
- `provider`：`deterministic|splade|unknown`
- `outcome`（search/build）：`ok|empty|error|skipped`

> 建议关注：`outcome=error` 的比例、`duration_seconds` 的 P95/P99，以及 `index_load_total{outcome=miss}` 的变化（可能表示频繁重建/冷启动）。

---

## 7) 回滚（Rollback Playbook）

sparse 通道设计为 **默认关闭**，且所有加载/索引持久化均为 best-effort；因此回滚通常只需配置开关：

1) **最安全的回滚**：关闭 sparse 通道  
   - `SPARSE_RETRIEVAL_ENABLED=false`

2) **保留 sparse 但降级 provider**（用于排查 SPLADE 模型问题）：  
   - `SPARSE_RETRIEVAL_PROVIDER=deterministic`（不依赖 transformers/模型下载）

3) **禁用落盘索引**（用于排查磁盘占用/权限问题）：  
   - `SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED=false`

4) **清理索引目录（可选）**：  
   - `SPARSE_RETRIEVAL_INDEX_DIR=./data/sparse_indexes` 下会按 provider 分目录写入 `index_*.json.gz`  
   - 改 provider/config 会自动生成新的 index key；旧文件可按需清理（不影响 correctness，只影响冷启动性能）

建议流程：
- 先看 Prometheus：`rag_sparse_search_total{outcome="error"}` 是否突然升高、`rag_sparse_search_duration_seconds` 是否飙升
- 先把 `SPARSE_RETRIEVAL_ENABLED=false`（硬回滚），然后在预发/灰度环境逐步恢复并跑 retrieval-only regression gate 验证收益
