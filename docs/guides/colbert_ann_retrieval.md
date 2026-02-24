# ColBERT ANN Retrieval（候选召回通道脚手架）

本仓库提供一个可选的 “ColBERT stack” 候选召回通道（工程脚手架）：

- **默认不启用**（避免改变现有行为）
- 用于在没有可用 vector backend（或 vector 返回空）时提供一个 **可持久化的候选召回** 路径
- 与 late-interaction rerank（`provider=colbert`）/ LTR 等精排组件可以组合使用

代码位置：
- `app/rag/retrieval/colbert_ann.py`（embedder + index store + ANN 计算工具）
- `app/rag/retriever.py`（HybridRetriever 集成）

---

## 1) 当前实现的定位（重要）

这是一个 **工程 scaffolding**，不是完整的 ColBERT token-level index：
- deterministic provider 用于单测/回归（无模型下载）
- HF provider 提供真实模型加载与 batch encode（opt-in）
- ANN 检索以 “chunk -> dense vector” 为主（候选生成），不等价于原始 ColBERT 的 token-level late-interaction 检索

它的价值是把 “索引构建/持久化/冷启动加载/可控 fallback” 的工程链路先打通。

---

## 2) 工作方式（当前实现）

1. **语料来源**：复用 BM25 的 scope cache（tenant/dataset/document scope 下的 chunks）。
2. **索引构建**：对 chunk 文本做 batch encode 得到 dense vectors，落盘保存（可选）。
3. **ANN 查询**：对 query encode 得到向量，与 doc vectors 做 cosine similarity Top-K（可选 FAISS）。
4. **集成策略**：在 `HybridRetriever` 的 vector 通道里，当 vector backend 返回空结果时，使用 ColBERT ANN 作为 fallback（opt-in）。

> 注意：因为语料复用 BM25 cache，如果 scope 没有 BM25 文档缓存（未 upsert / 未 warm），该通道也会是空的。

---

## 3) 配置项（Settings）

后端配置（见 `app/core/config.py`）：

- `COLBERT_RETRIEVAL_ENABLED=true|false`（默认 false）
- `COLBERT_RETRIEVAL_PROVIDER=deterministic|hf`
- `COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED=true|false`（默认 true，best-effort）
- `COLBERT_RETRIEVAL_INDEX_DIR=./data/colbert_indexes`

HF provider（可选，需显式配置模型）：
- `COLBERT_RETRIEVAL_MODEL_NAME=...`（必填；例如任意 HF encoder 模型）
- `COLBERT_RETRIEVAL_DEVICE=cpu|cuda|auto`
- `COLBERT_RETRIEVAL_BATCH_SIZE=16`
- `COLBERT_RETRIEVAL_MAX_LENGTH=256`

Deterministic provider（单测/回归）：
- `COLBERT_RETRIEVAL_EMBED_DIM=64`

---

## 4) Tradeoffs

- 额外索引构建开销（CPU/GPU + 内存）
- 多进程场景下，持久化索引可以显著降低冷启动成本（best-effort）
- 这不是完整 ColBERT 检索：如果你需要真实 token-level ColBERT index，需要额外工程与依赖

