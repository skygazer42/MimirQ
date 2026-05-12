# Hybrid Search 调优主流方案调研 — 2026-Q2

> 用户选 #1 主题(核心 RAG 功能深挖)。MimirQ `retriever.py` 6341 行 + `retrieval/` 子模块 ~5200 行,**Vector + BM25 + SPLADE + ColBERT/PLAID 已全部实现**,但 RRF k 值 / BM25 k1/b / alpha 融合权重 / SPLADE FLOPS / ColBERT 量化档位 / Adaptive 路由等参数空间**未量化调研**,默认值多处不一致(67 行 alpha=0.5,100 行 alpha=0.6)。本份覆盖业界 7 大调优范式 + 落地路径。

---

## 1. Context

### 1.1 起因

前面 embedding plan 揭示 Quick Win,**召回质量另一半短板在 Hybrid Search 调参**:
- 客户问"为什么换 Conan-v2 / Qwen3 后还是不准" → 大概率是 fusion 权重 + RRF k 没适配该语料
- 静态权重(0.5 / 0.6 / 0.4)对所有 query 一刀切,**业界 2025 共识是 query-adaptive**

### 1.2 调研问题

1. RRF k 值默认 60 是不是真正最优?Bruch et al. 2022 说"convex combination 可以做得更好"
2. BM25 k1/b 默认 1.2 / 0.75 已是 1994 Robertson 经验值,**MimirQ 用 Milvus BM25 没暴露这两个参数**,该不该曝?
3. Dense + Sparse + ColBERT 三路 fusion 该怎么配权重?
4. ColBERT PLAID vs MUVERA(2025-08 新)— 后者 100× 快,值不值得换?
5. SPLADE v3 vs 自家 SPLADE,值不值得升级?
6. Adaptive-RAG complexity routing 在 MimirQ 落地需要多少代码?
7. Pre-filter / partition_keys 已有,但有没有用对?

---

## 2. MimirQ 现状盘点

### 2.1 主要文件

| 文件 | 行数 | 内容 |
|---|---|---|
| `app/rag/retriever.py` | **6341** | HybridRetriever 主体(vector+BM25+SPLADE+ColBERT+RRF+MMR+alpha+fusion_weights+metadata_filter+partition_keys+entity_key) |
| `app/rag/retrieval/orchestrator.py` | **5241** | 检索编排,含 hierarchy/neighbor/sibling expansion |
| `app/rag/retrieval/colbert_ann.py` | ? | ColBERT 近邻索引 |
| `app/rag/retrieval/plaid.py` | ? | **PLAID 引擎** |
| `app/rag/retrieval/sparse.py` | ? | SPLADE 接入 |
| `app/rag/retrieval/sparse_prometheus_metrics.py` | ? | sparse metrics 监控 |
| `app/rag/retrieval/neighbor_expand.py` | ? | 邻近扩展(对照前 context-expansion plan) |
| `app/rag/retrieval/hierarchy_expand.py` | ? | 层级扩展 |
| `app/rag/retrieval/sibling_expand.py` | ? | 兄弟节点扩展 |
| `app/rag/retrieval/decomposition_chain.py` | ? | 问题分解链 |
| `app/rag/retrieval/evidence_gap.py` | ? | 证据缺口检测 |
| `app/rag/retrieval/contextual_followup.py` | ? | 上下文跟进 |
| `app/rag/retrieval/context_expansion.py` | ? | 上下文扩展 |
| `app/rag/retrieval/document_structure.py` | ? | 文档结构 |
| `app/rag/retrieval/metrics.py` | ? | 检索 metrics |
| `app/rag/retrieval/contract.py` | ? | 调用契约 |

### 2.2 现有参数(HybridSearchOptions 实测)

```python
@dataclass(frozen=True)
class HybridSearchOptions:
    top_k: int = 5
    score_threshold: float = 0.7
    document_ids: list[UUID] | None = None
    tenant_id: UUID | None = None
    alpha: float = 0.5                    # ← dense/sparse 融合,但 100 行另一处 alpha=0.6,不一致!
    enable_weight_rerank: bool = True
    vector_weight: float = 0.6
    keyword_weight: float = 0.4
    retrieval_mode: str = "hybrid"
    mmr_lambda: float = 0.7
    mmr_fetch_k_multiplier: int = 4
    metadata_filter: dict[str, Any] | None = None
    entity_key: str | None = None
    partition_keys: list[str] | None = None
    entity_candidates: list[str] | None = None
    requested_k: int | None = None

    # 配置层(从 settings)
    rrf_k: int = settings.RETRIEVAL_RRF_K     # ← 默认 60,业界对标 ✅
    fusion_weights: dict[str, float] | None
```

### 2.3 关键现状判断

| 维度 | 现状 | 业界对照 |
|---|---|---|
| RRF k 值 | 默认 60 ✅ | 60 是经验最优值(Cormack 2009 + Bruch 2022 验证) |
| Dense+Sparse alpha | 0.5(默认)/ 0.6(另一处) | 多处不一致 ❌ |
| vector_weight / keyword_weight | 0.6 / 0.4 | 静态,**业界 2025 主张 query-adaptive** |
| BM25 k1 / b | **未暴露**(Milvus 默认) | 默认 1.2 / 0.75 OK,但客户法律/中文场景该调 |
| SPLADE FLOPS 调节 | ? | SPLADE-v3 默认 0.88 vs 0.13(BM25),可调 |
| ColBERT 引擎 | PLAID(plaid.py 已有) | 2025 MUVERA 比 PLAID 快 100× |
| Adaptive complexity routing | ❌ 无 | RAGRouter-Bench TF-IDF+SVM 93.2% accuracy + 28.1% token savings |
| Pre-filter / partition | ✅ 有(metadata_filter + partition_keys + entity_key) | 业界一流 |
| MMR | ✅ lambda=0.7,fetch_k_multiplier=4 | 业界对标 |
| 监控 | ✅ sparse_prometheus_metrics.py | 业界对标 |

---

## 3. 业界主流 Hybrid Search 7 大调优范式

### 3.1 RRF k 值调优

**公式**:`score = Σ 1/(k + rank)`

**k 的含义**:
- **k 小**(如 10):顶端 rank 1 的文档权重极大,容易让一个 retriever 主导
- **k 大**(如 60-100):consensus 偏好,多个 retriever 一致命中才高分

**业界经验**:
- OpenSearch / Azure AI Search / Chroma:**k=60 默认**(Cormack 2009 原论文)
- **MimirQ ✅ 已用 60**
- 但 Bruch et al. 2022:RRF 在 domain shift 下不如 **learned convex combination**(只要有 50 题 ground truth 就可学权重)
- TREC iKAT 2025:多 query rewrite RRF fusion **nDCG@10 0.4218 → 0.4425**(+4.9%)

**MimirQ 改进点**:
- 暴露 `RETRIEVAL_RRF_K` 给数据集级覆盖(法律窄、医疗宽)
- **加 learned convex combination** 备选模式(per-dataset 训出 weights)

### 3.2 Convex Combination 权重(weighted score fusion)

vs RRF 取舍:

| 方法 | 优点 | 缺点 | 适用 |
|---|---|---|---|
| RRF | 零标注 / 鲁棒 / 跨 distribution | 不利用 score 信息 / domain shift 下次优 | 冷启动 / 无标注 |
| **Convex combination**:`α·dense + (1-α)·sparse` | 利用分数 / 调到极致 | 需要 score normalization / per-dataset 调参 | 有 50+ Golden Set |
| Learned RRF(WRRF) | 介于两者之间 | 需要 lite training | 折中场景 |

**MimirQ 现状是 alpha 静态 + RRF 并存**,但 alpha 默认值多处不一致(67=0.5 / 100=0.6),vector_weight 0.6 / keyword_weight 0.4 又是另一套——**实际上有 3 套并行参数,需要统一**。

### 3.3 BM25 k1 / b 调优

**默认值**:k1=1.2 / b=0.75(Elasticsearch / Lucene / Milvus / OpenSearch 一致)

| 参数 | 作用 | 调高 | 调低 |
|---|---|---|---|
| **k1**(term frequency saturation) | TF 饱和速度 | (1.5-2.0)长文档强调 TF | (0.8-1.2)早期饱和 |
| **b**(length normalization) | 文档长度归一 | (1.0)严格按比例 | (0.0-0.5)忽略长度 |

**MimirQ Milvus BM25 配置未暴露**——可能用了 Milvus 默认,**对极短/极长 chunk 不是最优**。

**业界中文 / 法律建议**:
- 法律(条款长且模板化):**k1=1.5 / b=0.8**(更严格长度归一)
- 中文短问答:**k1=1.0 / b=0.5**(早饱和 + 弱长度归一)
- 默认(混合):k1=1.2 / b=0.75 ✅

**Trotman et al. 2014 大规模实验**:在 [0-3] × [0-1] 搜索空间内,**不同 corpus 最优值差异显著**,需要 per-dataset 调。

### 3.4 SPLADE v3 / Learned Sparse(MimirQ 已有 sparse.py)

**SPLADE 三代演进**:

| 版本 | 核心创新 | FLOPS | MS-MARCO MRR@10 |
|---|---|---|---|
| SPLADE-v1 | log saturation + MLM head | 高 | ~0.34 |
| SPLADE-v2 | max pooling | 0.88 | 0.36 |
| **SPLADE-v3** | multi-negatives + ensemble distill + fused loss | 0.88 | **0.38+**,超 BM25 5-10pt,逼近 cross-encoder |
| BM25 baseline | - | 0.13 | 0.18 |
| Two-Step SPLADE(2024-04) | cascaded:pruned + full rescore | 0.13(stage 1) | 0.38+,**30-40× speedup vs full SPLADE** |

**关键 trade-off**:
- 效果:SPLADE-v3 > BM25 大幅度(语义场景)
- 效率:SPLADE 30522 维(BERT vocab)vs BM25 vocab 维,**SPLADE 非零项更多,Milvus sparse index 慢 5-10×**
- 泛化:在 BEIR 上,**未微调的 SPLADE 可能不如 BM25**(BEIR 偏向 BM25)

**MimirQ 改进点**:
- `sparse.py` 升级到 SPLADE-v3 训练权重
- 接 **Two-Step cascade**(stage1 pruned 取 top-100 → stage2 full rescore)
- FLOPS regularizer 提供 0.13/0.5/0.88 三档(BM25-like / 折中 / 全 SPLADE)

### 3.5 ColBERT PLAID → MUVERA 升级

**MimirQ 已有 `plaid.py`** —— PLAID(2022)是 ColBERT 的产线引擎,centroid interaction + centroid pruning + C++ 多线程:

| 模型 | GPU 延迟 | CPU 延迟 | 召回质量 |
|---|---|---|---|
| Vanilla ColBERTv2 | ~50ms | ~3000ms | 100% baseline |
| **PLAID**(MimirQ 已有) | ~7ms | ~67ms | 100% |
| **MUVERA**(2025-08 新) | **0.72ms**(128D)~ 2ms(2048D) | n/a | 略降(可 +rerank 补) |
| **MUVERA + Rerank** | **0.54ms** | n/a | **= PLAID 质量** |

**MUVERA 核心**:
- SimHash partitioning + AMS sketch → 把每文档 N 个 token vectors 编码成单个 fixed-dim vector
- 走标准 HNSW / IVF(不再需要 ColBERT 专用引擎)
- 之后用 ColBERT MaxSim 对 top-K=100 candidates rerank,质量不掉

**MimirQ 升级路径**:
- 保留 `plaid.py` 作 fallback
- 新增 `muvera.py`,跑 MUVERA + Rerank pipeline
- benchmark 验证:在客户语料上 MUVERA 比 PLAID 快几倍以上 + recall 不掉

### 3.6 Adaptive-RAG / 复杂度路由(MimirQ 缺)

**核心思想**(Jeong et al. 2024 + RAGRouter-Bench 2026):

```
query
   ↓
TF-IDF + SVM classifier(93.2% accuracy)
   ↓ ↓ ↓
simple        single-hop      multi-hop
   ↓             ↓                ↓
no retrieval  hybrid retrieval  CRAG / Self-RAG / 图谱多跳
```

**实测收益**:
- RAGRouter-Bench:**28.1% token savings**(避免简单问题走重型路径)
- HyPA-RAG(NAACL 2025):per-complexity 配 top-k 和 rewrite 次数
- 企业部署:**P50 延迟 -35%、API 成本 -28%、accuracy +8%**

**MimirQ 改进点**:
- 新增 `app/rag/retrieval/router.py` ≈ 300 行
- 三档 classifier(simple / single-hop / multi-hop)+ 路由表
- 路由结果写 trace(`message_metadata.retrieval_route`)
- 配合 prompt plan 的 industry_rules 一起在 query_rewrite 前判定

### 3.7 Pre-filter / Metadata 路由

**MimirQ 已有**:`metadata_filter` / `partition_keys` / `entity_key` 三件套 ✅

**业界经验**:
- Pre-filter > Post-filter(Milvus 文档)— MimirQ 该用对就用对
- **`partition_keys` 是金山**:tenant_id / dataset_id / access_level 早过滤,**百万规模库可降延迟 10-100×**
- entity_key 适合"问 X 公司 2023 财报"这类强约束 query

**潜在问题**:
- HybridSearchOptions 提供了入口,但**调用方是否每次都传**?需要 grep 调用点统计覆盖率
- `score_threshold=0.7` 默认有点高,某些 embedding 模型 cosine 不到 0.7(int8 量化后更低),会**人为剪掉好结果**

---

## 4. Reranker 配套调优(简略,只列与 hybrid 联动)

(独立调研 plan 可单独做,MEMORY 提到 9 种 reranker)

**业界 2026 共识**:
- Hybrid retrieval(Recall@5 ~0.7)+ **Cross-encoder rerank(Recall@5 ~0.82)** 是 SOTA pipeline
- Cohere Rerank 3 / BGE-Reranker v2-m3 / Voyage Rerank 2 / Jina Rerank v2 是主流四家
- MimirQ 9 种已有,**未量化对比**,建议作为 P1 独立 plan

**关键耦合点**:
- Retriever top_K=5 太少给 reranker 看,应该 top_K_retrieval=50 + top_K_after_rerank=5
- MimirQ HybridSearchOptions 现 top_k=5,**需要双层 top_k**(retrieval 50,rerank 后 5)

---

## 5. 推荐 P0 / P1 / P2

### 5.1 P0(2-3 周,内部一致性 + 暴露关键参数 + Adaptive 路由)

| 任务 | 落点 | 估算 |
|---|---|---|
| **统一 alpha 默认值**(67 / 100 行不一致,改一处单一来源) | `retriever.py:67,100` + `settings.RETRIEVAL_DEFAULT_ALPHA` | 0.5 day |
| **暴露 BM25 k1 / b 参数**(Milvus collection schema + settings.BM25_K1=1.2/BM25_B=0.75) | `retriever.py` + Milvus index 设置 | 1 day |
| **`HybridSearchOptions` 加 retrieval_top_k 和 rerank_top_k 双层**(retrieval 50 → rerank 5) | `retriever.py:62-79` | 1 day |
| **score_threshold 改 per-provider 自适应**(int8 量化后 cosine 范围不同,从 0.7 静态改成"模型自检 + p10 自动确定") | `retriever.py` + `embedding/factory.py` | 1 day |
| **`app/rag/retrieval/router.py` 新建**:TF-IDF + SVM 三档 classifier(simple / single-hop / multi-hop) | new | 2 day |
| **Adaptive routing 接入 orchestrator** + trace 透出 `retrieval_route` | `retrieval/orchestrator.py` + `engine.py` | 1 day |
| **Hybrid search benchmark runner**(50 dataset × {RRF k=10/30/60/100} × {α=0.3/0.5/0.7} × {top_K=5/20/50}) | `evaluation/hybrid_search_bench/`(new) | 2.5 day |
| **HTML 报告**(单文件,对齐 PoC 三原则)显示每个 dataset 最优配置 + 显著性 | benchmark runner 配套 | 1 day |
| **Two-Step SPLADE cascade 接入**(stage1 pruned → stage2 full),`sparse.py` 扩展 | `retrieval/sparse.py` | 2 day |

### 5.2 P1(1 个月,工程升级 + 自动调参)

1. **MUVERA 接入**(`retrieval/muvera.py` new + 与 plaid.py 并存可切换)
   - 实测 1k chunk 库 vs 100k chunk 库 latency
   - PLAID-MUVERA-Rerank 三档延迟/质量 trade-off
2. **SPLADE v3 微调**:用 MimirQ feedback_loop 数据走一次 contrastive,目标 nDCG@10 +2pt
3. **Learned convex combination**:per-dataset 训 dense+sparse+colbert 三路权重(L2 loss + 50-200 题 ground truth);保留 RRF 作 fallback
4. **Per-tenant BM25 k1/b auto-tune**:用 200 题客户 PoC 数据走 grid search [k1: 0.8/1.2/1.5/2.0] × [b: 0.5/0.75/0.9]
5. **Reranker 横向 benchmark plan**(独立写,先调研 MimirQ 9 种 + 业界 Cohere v3 / Voyage v2 / BGE v2-m3 / Jina v2)
6. **Pre-filter 覆盖率审计**:grep 所有 retriever 调用点,确认 `partition_keys=[tenant_id, dataset_id]` 全覆盖

### 5.3 P2(独立调研)

| 项 | 内容 |
|---|---|
| Self-RAG critique 集成 | 在 retrieval 后端加 critique token,faithfulness 判定 |
| FLARE 主动召回 | 生成期遇低置信触发新一轮检索 |
| Multi-vector dense(ColBERT 之外的 ColPali / Jina-embeddings-v4 多向量) | 评估存储成本 |
| Hybrid search 在 Vector DB 第二后端(Qdrant)的表现 | 对照 MEMORY 中 Qdrant 战略项 |

### 5.4 不该做的事

- ❌ **不要把 RRF k 从 60 改成 10 或 100**(Bruch 2022 证明 60 在 zero-shot 最稳)
- ❌ **不要去掉 alpha 默认值留给运维填**(产品体验差,要有合理默认 + per-dataset 覆盖)
- ❌ **不要默认开 SPLADE v3**(BEIR 上未微调时可能不如 BM25,需要先在客户语料上验证)
- ❌ **不要一开始就上 MUVERA 替换 PLAID**(MUVERA 是 2025-08 新,工程成熟度待验证;先 P1 实验)
- ❌ **不要在 Adaptive routing 没 90%+ accuracy 时上线**(误路由比一律重型更糟)
- ❌ **不要忘记 metadata_filter 的预过滤 vs 后过滤**(post-filter 是大坑,Milvus 文档明确警告)

---

## 6. 关键文件清单(将动)

### 后端 P0
- `app/rag/retriever.py:62-79`(HybridSearchOptions 加 retrieval_top_k / rerank_top_k / 自适应 score_threshold)
- `app/rag/retriever.py:67,100`(统一 alpha 默认值)
- `app/rag/retrieval/sparse.py`(Two-Step SPLADE cascade)
- `app/rag/retrieval/router.py`(new,TF-IDF + SVM 三档)
- `app/rag/retrieval/orchestrator.py`(接 router)
- `app/rag/engine.py`(trace 写 retrieval_route)
- `app/core/config.py`(暴露 BM25_K1 / BM25_B / RETRIEVAL_DEFAULT_ALPHA 等)

### 评测(P0)
- `evaluation/hybrid_search_bench/`(new)
  - `corpus/`(50 客户文档对应)
  - `golden/`(200 query + ground truth)
  - `runners/{rrf_k_sweep,alpha_sweep,topk_sweep,bm25_k1_b_sweep,adaptive_router_eval}.py`
  - `reports/hybrid_landscape_<date>.html`(单文件)

### 前端(P1)
- `web/components/retrieval/hybrid-search-tuner.tsx`(new,数据集级 RRF k / alpha / top_K 调节器)
- `web/components/retrieval/routing-decision-trace.tsx`(new,Adaptive 路由可视化)
- 链路 trace 加 `retrieval_route=simple/single-hop/multi-hop` 显示

### 测试
- `tests/test_hybrid_options_unified_alpha.py`(new)
- `tests/test_bm25_k1_b_exposure.py`(new)
- `tests/test_adaptive_router_classifier.py`(new)
- `tests/test_two_step_splade_cascade.py`(new)
- `tests/test_score_threshold_adaptive_per_provider.py`(new)

### P1
- `app/rag/retrieval/muvera.py`(new)
- `app/rag/retrieval/learned_convex_fusion.py`(new)
- `app/rag/retrieval/bm25_autotune.py`(new)

---

## 7. 验证

### 7.1 P0 验证

1. `pytest tests/test_hybrid_*.py tests/test_adaptive_router*.py tests/test_two_step_splade*.py` 全绿
2. **alpha 一致性**:全文 grep `alpha\s*=` 在 retriever.py 收敛到单一来源
3. **BM25 k1/b 可热配**:改 settings.BM25_K1=1.5 → 重启服务 → 召回结果应有差异(Trotman 2014 经验值)
4. **Adaptive 路由准确率**:在 200 题路由测试集(simple 80 / single-hop 80 / multi-hop 40)≥ **88%**(对标 RAGRouter-Bench TF-IDF+SVM 93.2%,差距留给标注偏差)
5. **Hybrid Search benchmark runner 完整跑通**:HTML 报告显示每 dataset 最优 (RRF k, α, top_K, BM25 k1/b) 组合 + 统计显著性(p<0.05)
6. **Two-Step SPLADE 加速**:stage1+stage2 比 full SPLADE 快 **5-10×**,nDCG@10 不掉
7. **客户 PoC 数据集**:工控/法律/财务 三组 50 题 Golden Set,跑 baseline(现状)vs P0 后,**Recall@5 +3-5pt**

### 7.2 P1 验证

1. MUVERA 实测延迟比 PLAID 快 **5-50×**(取决于 chunk 数)
2. SPLADE v3 微调后 nDCG@10 +2pt over baseline SPLADE
3. Learned convex combination per-dataset 比 RRF k=60 提升 **+2-4pt**(对标 Bruch 2022 经验)
4. Pre-filter 覆盖率审计:所有 retriever 调用点 `partition_keys` 覆盖率 ≥ 95%

### 7.3 回归(不变性)

- 现有 MMR / metadata_filter / partition_keys / entity_key 行为不变
- ColBERT PLAID 路径继续可用作 fallback
- score_threshold 0.7 静态降级路径保留(per-provider 自适应失败时退到旧逻辑)

---

## Sources

### RRF
- [Introducing RRF for hybrid search — OpenSearch](https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/)
- [Hybrid Search Scoring (RRF) — Azure AI Search](https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking)
- [Hybrid Search with RRF — Chroma Docs](https://docs.trychroma.com/cloud/search-api/hybrid-search)
- [Hybrid retrieval with RRF: solving the score normalization problem — Andrey Chauzov 2025](https://avchauzov.github.io/blog/2025/hybrid-retrieval-rrf-rank-fusion/)
- [Reciprocal Rank Fusion Based Hybrid Dense–Sparse Retrieval — CEUR-WS 2025](https://ceur-ws.org/Vol-4173/T3-7.pdf)
- [The Quiet Hero of RAG Pipelines: RRF — Medium 2025](https://medium.com/@mudassar.hakim/the-quiet-hero-of-rag-pipelines-reciprocal-rank-fusion-explained-1b83af68b997)
- [Better RAG results with RRF and Hybrid Search — Assembled](https://www.assembled.com/blog/better-rag-results-with-reciprocal-rank-fusion-and-hybrid-search)
- [Optimizing Hybrid Search Query with RRF — MariaDB Docs](https://mariadb.com/docs/server/reference/sql-structure/vectors/optimizing-hybrid-search-query-with-reciprocal-rank-fusion-rrf)

### BM25 调参
- [Practical BM25 - Part 3: Considerations for Picking b and k1 in Elasticsearch — Elastic Blog](https://www.elastic.co/blog/practical-bm25-part-3-considerations-for-picking-b-and-k1-in-elasticsearch)
- [Practical BM25 - Part 2: The BM25 Algorithm and its Variables — Elastic](https://www.elastic.co/blog/practical-bm25-part-2-the-bm25-algorithm-and-its-variables)
- [Configure BM25 Relevance Scoring — Azure AI Search](https://learn.microsoft.com/en-us/azure/search/index-ranking-similarity)
- [Okapi BM25 — Wikipedia](https://en.wikipedia.org/wiki/Okapi_BM25)
- [BM25 — Arpit Bhayani](https://arpitbhayani.me/blogs/bm25)
- [Okapi BM25: Guide to Modern IR — ADaSci](https://adasci.org/blog/understanding-okapi-bm25-a-guide-to-modern-information-retrieval)
- [What is BM25 — GeeksforGeeks](https://www.geeksforgeeks.org/nlp/what-is-bm25-best-matching-25-algorithm/)

### SPLADE / Learned Sparse
- [SPLADE-v3: Advancements in Sparse Retrieval — Emergent Mind](https://www.emergentmind.com/papers/2403.06789)
- [Efficiency and Effectiveness of SPLADE Models on Billion-Scale (arXiv 2511.22263, 2025)](https://arxiv.org/html/2511.22263v1)
- [Two-Step SPLADE: Simple, Efficient and Effective (arXiv 2404.13357)](https://arxiv.org/pdf/2404.13357)
- [Lexical vs Learned Sparse Retrieval: BM25 vs SPLADE at Scale — Cosdata](https://www.cosdata.io/blog/lexical-versus-learned-sparse-retrieval-bm25-vs-splade-at-scale)
- [Modern Sparse Neural Retrieval — Qdrant](https://qdrant.tech/articles/modern-sparse-neural-retrieval/)
- [SPLADE for Sparse Vector Search Explained — Pinecone](https://www.pinecone.io/learn/splade/)
- [Comparing SPLADE Sparse Vectors with BM25 — Zilliz](https://zilliz.com/learn/comparing-splade-sparse-vectors-with-bm25)
- [The Past and Present of Sparse Retrieval — HF blog](https://huggingface.co/blog/yjoonjang/the-past-and-present-of-sparse-retrieval)

### ColBERT / PLAID / MUVERA
- [stanford-futuredata/ColBERT — GitHub](https://github.com/stanford-futuredata/ColBERT)
- [PLAID: An Efficient Engine for Late Interaction Retrieval (arXiv 2205.09707)](https://arxiv.org/pdf/2205.09707)
- [ColBERTv2: Effective and Efficient Retrieval (arXiv 2112.01488)](https://arxiv.org/abs/2112.01488)
- [colbert-ir/colbertv2.0 — HF](https://huggingface.co/colbert-ir/colbertv2.0)
- [ColBERT-Att: Late-Interaction Meets Attention (arXiv 2603.25248, 2026)](https://arxiv.org/html/2603.25248v1)
- [ColBERT-Style Late Interaction — Emergent Mind](https://www.emergentmind.com/topics/colbert-style-late-interaction)

### Adaptive Routing
- [Adaptive-RAG: Learning to Adapt via Query Complexity (arXiv 2403.14403)](https://arxiv.org/abs/2403.14403)
- [Adaptive Query Routing: Tier-Based Framework (arXiv 2604.14222, 2026)](https://arxiv.org/html/2604.14222)
- [Lightweight Query Routing for Adaptive RAG: RAGRouter-Bench (arXiv 2604.03455)](https://arxiv.org/html/2604.03455v1)
- [HyPA-RAG: Hybrid Parameter Adaptive RAG (NAACL 2025)](https://aclanthology.org/2025.naacl-industry.79.pdf)
- [Adaptive RAG explained 2026 — Meilisearch](https://www.meilisearch.com/blog/adaptive-rag)
- [Query-Adaptive RAG: Routing Complex Questions — generation RAG](https://ragaboutit.com/query-adaptive-rag-routing-complex-questions-to-multi-hop-retrieval-while-keeping-simple-queries-fast/)
- [Understanding Adaptive-RAG — Medium](https://medium.com/@tuhinsharma121/understanding-adaptive-rag-smarter-faster-and-more-efficient-retrieval-augmented-generation-38490b6acf88)

### Hybrid 综合
- [Dense vs Sparse vs Hybrid RRF — Medium](https://medium.com/@robertdennyson/dense-vs-sparse-vs-hybrid-rrf-which-rag-technique-actually-works-1228c0ae3f69)
- [Hybrid Retrieval-Augmented Generation — Emergent Mind](https://www.emergentmind.com/topics/hybrid-retrieval-augmented-generation-rag)
