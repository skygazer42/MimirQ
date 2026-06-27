# RAG 检索底座现代化 deep-dive（2026-Q2，纯 RAG）

> 日期：2026-06 ｜ 来源：`plans/cosmic-meandering-teapot.md` 调研地图方向 B+D+E
> 定位：纯 RAG（非 RL）。两类增量——**可免费升级的模型代差**（Qwen3/MUVERA）+ **反直觉的生产校准点**（HyDE 可能有害、context<8K），后者需用内部 benchmark 验证我方现状。

## Context

我方检索/embedding/rerank 架构健全（hybrid 四路 + 13 种 reranker + 6 向量后端），但底座模型停在 2024 默认值，且有几个 2025-2026 被反复验证的"反直觉"点我方未校准。这些都不需要改架构，是"换模型 / 加约束 / 跑验证"级别的提升。

## 一、业界方法拆解

### 1.1 检索底座模型（方向 B，可免费涨点）
- **Qwen3-Embedding / Reranker**（arxiv 2506.05176，2025.06）：0.6/4/8B，MTEB-multilingual **70.58 超 Gemini-Embedding**，100+ 语言，**Apache 2.0**，支持 Matryoshka（弹性维度）。Qwen3-8B-Embedding 是当前最强开源之一。
- **Qwen3-VL-Embedding / Reranker**（2026.01）：文本/图/文档图/视频统一空间，2B/8B，cross-attention reranker。多模态需求明确后再上。
- **NV-Embed-v2**（MTEB 72.31）：latent-attention pooling，generalist LLM embedding。
- 实用 cross-encoder：**bge-reranker-v2-m3**（~80ms，精度/成本平衡好）。

### 1.2 MUVERA — late interaction 提速（方向 B）
arxiv 2405.19504（Google）。多向量（ColBERT 系）质量好但贵；MUVERA 用 **固定维编码（FDE）** 把多向量相似度降为单向量检索：SimHash LSH 分簇，**query 嵌入求和、doc 嵌入平均**成质心，同簇内 token 贡献被保留。
- 比 PLAID **recall +10% / 延迟 -90%**；PQ 压缩内存 32×。
- **Qdrant / FastEmbed 已原生支持**（我方有 Qdrant 后端）。
- 最佳实践两阶段：MUVERA 召回（~8× 提速）+ 多向量重排 → 几乎无损还原质量。

### 1.3 生产校准点（方向 D，反直觉，需验证我方现状）
- **HyDE 可能有害**：多 benchmark（如 2604.01733）发现 **HyDE 低于 vanilla dense retrieval**（生成的假设文档引入噪声）。我方有 HyDE 路径，**需跑 with/without 验证是否该默认关**。
- **context cliff <8K**：Chroma 2025 测 18 模型（GPT-4.1/Claude4/Gemini2.5）均随上下文增长退化，短上下文常胜。建议装配端加 <8K 软约束 + 更狠的 rerank 截断。
- **Adaptive Chunking**（2603.25333）：按文档特征自动选切块方法。我方 `strategy_matrix` 偏静态规则。
- **metadata enrichment 量化**：82.5% vs 73.3% precision（IEEE）。我方已有三字段 metadata，可补量化验证。

### 1.4 Long-context × RAG 决策（方向 E）
"naive RAG dead, sophisticated thriving"；检索 chunk 数呈 **inverted-U**（过多反降）；**lost-in-the-middle**（关键证据放首尾）。

## 二、我方现状核实（grep 真实结果）

| 能力 | 现状 | 证据 |
|---|---|---|
| 默认 embedding | `text-embedding-3-small`（≈62，落后 SOTA ~8 分） | `embedding/config.py` |
| embedding provider | 4 真实现 + 4 空壳（voyage/cohere/jina/bedrock 各 10 行） | `embedding/providers/` |
| Qwen3 embedding | 仅注册表条目，非默认 | `embedding/config.py` 命中 |
| reranker 工厂 | 13 种（colbert/cross_encoder/dashscope/hf/aliyun…），**无 Qwen3** | `reranker/factory.py` |
| ColBERT | deterministic ANN，无 MUVERA/FDE | `reranker/colbert.py`(461) |
| Qdrant 后端 | 存在（基础） | `storage/vector/qdrant.py`(123) |
| HyDE | 有路径，未验证收益 | `engine.py` + `llm/prompts/builtin_library.py` |
| LC×RAG / 首尾重排 | 无 | `policy/complexity_classifier.py`(28 行正则) |

## 三、落地设计

### P0 — 免费/低成本，直接落地
1. **Qwen3-Reranker 接入 reranker 工厂**：在 `app/rag/reranker/factory.py` 加一种 provider（参考现有 `cross_encoder`/`hf` 实现），模型 `Qwen3-Reranker-0.6B/4B`。零架构改动。
2. **默认 embedding 升级评估**：在 `embedding/config.py` 评估默认从 `text-embedding-3-small` → `Qwen3-Embedding-0.6B` 或 `BAAI/bge-m3`（中文友好）。先 benchmark 再切默认。
3. **HyDE 有害性验证**：用内部评测栈跑 HyDE on/off 的 recall/nDCG，决定是否默认关 HyDE（可能直接提质量 + 省一次 LLM 调用）。

### P1 — 需 prototype
4. **MUVERA**：基于 Qdrant 原生 FDE 支持，给 ColBERT/多向量路径加"MUVERA 召回 + 多向量重排"两阶段。落地 `storage/vector/qdrant.py` + `reranker/colbert.py`。
5. **context<8K 软约束 + 首尾重排**：在 `retrieval/orchestrator.py`(6075) 装配端，总 context 超阈值时收紧 rerank 截断；关键 chunk 放首尾（抗 lost-in-the-middle）。
6. **metadata enrichment 量化**：补 with/without metadata 的 precision 对比。

### P2 — 进阶
7. **Adaptive Chunking 选择器**：升级 `chunking/strategy_matrix.py`(1014) 为按文档特征自动选策略。
8. **4 空壳 provider 补全**：voyage/cohere/jina/bedrock 补原厂特性（32k context / 多模态 / multi-task instruction）。
9. **Qwen3-VL 多模态检索**：待多模态需求明确。

## 四、优先级矩阵

| 优先级 | 任务 | 工作量 | 落地文件 |
|---|---|---|---|
| **P0** | Qwen3-Reranker 接入 | ~80 行 | `reranker/factory.py` + provider |
| **P0** | 默认 embedding 升级评估 | ~40 行 + benchmark | `embedding/config.py` |
| **P0** | HyDE on/off 验证 | benchmark 脚本 | 复用评测栈 |
| **P1** | MUVERA 两阶段 | ~200 行 | `storage/vector/qdrant.py` + `reranker/colbert.py` |
| **P1** | context<8K + 首尾重排 | ~120 行 | `retrieval/orchestrator.py` |
| **P2** | Adaptive Chunking 选择器 | ~250 行 | `chunking/strategy_matrix.py` |
| **P2** | 4 空壳 provider 补全 | 各 30-50 行 | `embedding/providers/` |

## 五、验证

- **Qwen3-Reranker vs 现有 13 种**：用既有评测栈跑 nDCG@10 / Hit@k / 延迟，对比择优。
- **embedding 升级**：text-embedding-3-small vs Qwen3-Embedding/BGE-M3 的 retrieval recall，中英文分别测。
- **HyDE on/off**：recall/nDCG + 延迟/成本；若 off 不降反升 → 默认关。
- **MUVERA**：召回质量保留率（目标 ≥95%）+ 延迟（目标 5-8× 提速）。
- **决策门槛**：任一替换需 ≥ 现状 + 不劣化延迟预算，才切默认；否则保留为可选。

## 六、学习入口
- **Qwen3-Embedding/Reranker** arxiv 2506.05176 ｜ Qwen3-VL 2026.01
- **MUVERA** arxiv 2405.19504（Google）
- **NV-Embed-v2** 2405.17428
- HyDE 反直觉 benchmark 2604.01733 ｜ Adaptive Chunking 2603.25333
- Chroma context rot（2025）

> 一句话：这一份没有"高难方法"，全是"换更强的开源模型 + 加几个被验证的约束 + 跑 benchmark 砍掉可能有害的 HyDE"——纯 RAG 里最确定、最快见效的一批升级。
