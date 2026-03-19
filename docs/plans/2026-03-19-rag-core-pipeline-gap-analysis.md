# RAG 核心管线能力差距分析

> 分析基于 2026-03-19 代码状态。聚焦 RAG 基础设施核心链路：文档摄入 → 解析 → 分块 → KG 抽取 → 存储索引 → 召回 → 评估。  
> 排除安全/认证、Agent/对话记忆、ASR/TTS 等下游消费侧能力。

## 对标基准

行业：Dify, RAGFlow, Anyscale, Redis RAG Blueprint, Qdrant  
学术：DEG-RAG (KG denoising), RAGPerf (end-to-end bench), DenseX/LumberChunker (chunking taxonomy 2602.16974), Late Chunking, Contextual Retrieval, Self-Healing Indexes  

---

## 已建成能力摘要

| 管线阶段 | 已有能力 |
|---------|---------|
| 文档摄入 | 批量上传(50并发)、9类连接器、SHA256去重、arq异步队列、审计日志、摄入策略 |
| 文档解析 | 15+ PDF 解析器、10+ 非 PDF 解析器、质量评分路由 (`score_pdf_quality`)、解析竞赛 (`select_best_parse_attempt`)、OCR 验证、解析诊断报告 |
| 分块 | 60+ 分块策略、覆盖率/重叠/gap 指标 (`_compute_chunk_coverage_metrics`)、质量信号 (`_compute_chunk_preview_review_signals`)、分块预览与对比 UI |
| KG 抽取 | 实体/关系/事件/技能抽取、EntityVerifier 验证、别名抽取与去重、增量更新(content hash skip) |
| 向量存储 | Milvus/FAISS/Chroma/Memory、BM25 索引重建、索引漂移检测与审计、embedding space hash |
| 混合检索 | 向量 + BM25 + SPLADE、RRF/线性融合、父子层级召回、ColBERT late-interaction、LTR(XGBoost) |
| 评估 | RAGAS(faithfulness/relevancy/precision)、回归门禁(recall/MRR/NDCG/multihop)、证据检索门禁、KG搜索诊断、hard negative mining |

---

## Gap 1: Contextual Retrieval / Late Chunking — 分块丢失文档级上下文

**现状**: 分块后每个 chunk 独立 embedding，丢失了在原文档中的位置和角色语境。检索时短 chunk 缺少自解释能力。

**行业标杆**:
- Anthropic Contextual Retrieval：嵌入前为每个 chunk 注入 2-3 句文档级上下文前缀，检索召回提升 49%
- Late Chunking (arxiv 2602.16974)：先全文过 transformer 获得上下文化 token embedding，再按 chunk 边界做 mean pooling。BEIR NFCorpus +6.5pp
- 适用性：contextual retrieval 对语义连贯性保留更好但计算成本更高；late chunking 效率更高但对文档内检索有退化

**建议方案**:
- 在 `app/rag/chunking/` 后处理阶段新增 `contextual_enrichment.py`
- 对每个 chunk 用 fast model（如 Qwen3-0.6B）生成上下文前缀：`"本段出自《{doc_title}》第{section}节，讨论{topic}。"`
- embedding 时拼接 `context_prefix + chunk_content`，存储时保留原始内容（展示用）
- 可配置：`CONTEXTUAL_RETRIEVAL_ENABLED`、`CONTEXTUAL_RETRIEVAL_MODEL`、仅对指定 dataset/策略启用
- late chunking 需要 long-context embedding model (8192+ tokens)，可作为第二阶段评估

**涉及文件**: `app/rag/chunking/factory.py`, `app/services/document_processing.py`, `app/rag/embedding/adapter.py`

---

## Gap 2: Proposition-Based Chunking (DenseX) — 原子事实级分块

**现状**: 60+ 分块策略覆盖了从固定窗口到领域特定，但无将文本拆分为原子命题（proposition）的策略。

**行业标杆**:
- DenseX Proposition Chunking：LLM 在索引时将段落拆分为自包含、可验证的原子事实，每个命题满足：只表达一个事实、自包含无代词、使用规范名称
- 2602.16974 综合评测显示 proposition 在特定 retrieval task 上优于传统分块
- 生产中成本较高但对精确检索场景（FAQ、法律条款、技术规范）效果显著

**建议方案**:
- 新增 `app/rag/chunking/strategies/proposition.py`
- LLM 将每段文本拆为原子命题列表，每个命题独立 embedding
- 保留 parent doc/section 元数据用于上下文恢复
- 可与现有 `parent_child` 策略组合：proposition 作为 child chunk 检索，parent 作为 context 返回
- 配置: `PROPOSITION_CHUNKING_MODEL`, 仅对高精度需求的 dataset 启用

**涉及文件**: `app/rag/chunking/strategies/`, `app/rag/chunking/factory.py`

---

## Gap 3: 分块质量自动评分（信息密度 / 语义完整性）

**现状**: `_compute_chunk_preview_quality` 和 `_compute_chunk_coverage_metrics` 计算覆盖率、重叠、长度分布等结构性指标。但缺少语义层面的质量评分：信息密度、语义完整性、上下文独立性。

**行业标杆**:
- Galileo ChainPoll：Chunk Utilization Plus（chunk 被实际使用的比例）、Chunk Attribution Plus（答案归因到 chunk 的准确度）
- Anyscale：ingestion quality gates 包含内容验证和结构完整性检查
- 数据驱动分块决策：用 RAGAS Context Precision/Recall 指标反推最优分块参数

**建议方案**:
- 新增 `app/rag/chunking/quality_scorer.py`
- 指标：
  - `information_density`: 实体/关键词数 / token 数（低密度 chunk 可能是噪声）
  - `semantic_completeness`: 是否以完整句结尾、是否被截断的表格/列表
  - `self_containedness`: 未解析的代词/指代比例（高 = 脱离上下文难理解）
  - `dedup_risk`: 与同文档其他 chunk 的 Jaccard/SimHash 相似度
- 在 chunk preview UI 中展示质量分数热力图
- 质量低于阈值的 chunk 标记为 `needs_review`，纳入数据治理流

**涉及文件**: `app/rag/chunking/`, `web/components/chunk-preview/`, `app/api/v1/documents.py`

---

## Gap 4: 语义缓存 — 检索层精确匹配 → 语义匹配

**现状**: `chat_response_cache.py` / `retrieval_candidate_cache.py` 均为精确 query 字符串匹配。语义相近但措辞不同的查询无法命中缓存。

**行业标杆**:
- Higress-RAG：50ms 语义缓存 + 动态阈值
- Redis RAG at Scale：语义缓存减少 LLM 成本 68.8%
- 生产系统 sub-100ms 响应于缓存命中

**建议方案**:
- 新增 `app/services/semantic_cache.py`
- 查询到达时先 embedding，在专用 Milvus collection (`semantic_cache`) 中做 ANN 搜索
- cosine > threshold（默认 0.95）即命中，返回缓存的检索结果 + 生成结果
- TTL + `corpus_cache_token` 联合失效（文档变更时对应缓存自动清除）
- 动态阈值：可按 dataset 或 query intent 调整
- 监控指标：命中率、节省 token 数、命中延迟 vs miss 延迟

**涉及文件**: `app/services/`, `app/rag/retrieval_candidate_cache.py`, `app/core/config.py`

---

## Gap 5: Embedding 模型热切换（Zero-Downtime Migration）

**现状**: `current_embedding_space_hash` 检测模型变更，但切换模型后需要调用 `reembed_document_chunks` 全量重嵌入，期间旧向量与新查询向量空间不一致，导致检索质量断崖。

**行业标杆**:
- Qdrant：blue-green 双 collection 部署 + dual write + feature flag 切换
- 生产案例：48 小时内完成百万级文档迁移，82% 检索结果一致性后切换
- Self-Healing Indexes：持续检测 embedding drift，自动触发局部重嵌入

**建议方案**:
- 实现 blue-green embedding migration：
  1. 创建新 collection（带新模型名后缀）
  2. 开启 dual-write：新文档同时写入新旧 collection
  3. 后台批量 re-embed 旧文档到新 collection（支持断点续传）
  4. 验证检索质量达标后，feature flag 切换查询到新 collection
  5. 清理旧 collection
- 新增 `app/services/embedding_migration.py`
- 在 `app/storage/vector/` 中支持同时操作两个 collection
- 进度追踪 + 质量验证（比对新旧 top-k 结果重叠率）

**涉及文件**: `app/storage/vector/milvus.py`, `app/rag/embedding/`, `app/services/`, `app/core/config.py`

---

## Gap 6: KG 抽取质量评分与去噪

**现状**: `EntityVerifier` 和 `RelationVerifier` 做实体/关系验证，别名抽取做去重。但无 KG 整体质量评分，无系统性去噪。

**行业标杆**:
- DEG-RAG (arxiv 2510.14271)：entity resolution 消除冗余实体 + triple reflection 移除错误关系，图规模减半同时 QA 性能持续提升
- KG-based evaluation (arxiv 2510.02549)：用 KG 结构做 RAG 评估，multi-hop 推理 + 语义社区聚类
- RAGPerf：端到端 benchmark 包含 KG 质量指标

**建议方案**:
- 新增 `app/rag/kg/quality/` 子模块
- `kg_completeness_scorer.py`：
  - 实体覆盖率：chunk 中 NER 识别的实体 vs KG 中已有实体的比例
  - 关系密度：avg relations per entity（过低 = 孤立节点多）
  - 孤立实体比例：无任何关系的实体占比
  - 社区连通性：connected component 数量和大小分布
- `kg_denoiser.py`：
  - Triple reflection：LLM 评估每条关系是否有 chunk 证据支持
  - 低置信度关系标记为 `unverified`，可在 UI 中审核
- KG 质量报告集成到 `/graph/diagnostics` 页面

**涉及文件**: `app/rag/kg/`, `web/components/graph/kg-diagnostics-page.tsx`

---

## Gap 7: Embedding Drift 持续监控

**现状**: `index_audit_service.py` 检测索引漂移（chunk 增删后索引不一致），但不检测 embedding 质量漂移（同一文本在不同时间 embedding 后向量偏移）。

**行业标杆**:
- Embedding drift 是 RAG 准确性的"隐形杀手"：70% 的 RAG 部署缺乏系统性评估框架
- 检测方法：对已知文档比对 cosine distance、追踪最近邻稳定性
- 常见原因：部分重嵌入、预处理管线变更、模型版本变更、chunk 边界漂移

**建议方案**:
- 新增 `app/services/embedding_drift_monitor.py`
- 维护一组"锚点文档"（golden set），定期重新 embedding 并比对与存储向量的 cosine distance
- 漂移超过阈值（如 0.05）时触发告警 + 建议重嵌入
- 追踪指标：anchor drift score、nn stability score、per-dataset drift trend
- 集成到 `/diagnostics` 页面

**涉及文件**: `app/services/`, `app/rag/embedding/`, `web/app/diagnostics/`

---

## Gap 8: 端到端 RAG Pipeline Benchmark（RAGPerf 式）

**现状**: RAGAS 评估 faithfulness/relevancy/precision，回归门禁评估 recall/MRR/NDCG。但缺少端到端性能 benchmark：吞吐量、延迟分布、内存/GPU 利用率、embedding 成本追踪。

**行业标杆**:
- RAGPerf (arxiv 2603.10765)：自动化收集吞吐量、内存占用、CPU/GPU 利用率 + 准确率指标
- Redis：target single-digit ms P95 latency，TTFT p90 < 2s
- 生产系统追踪 per-component 延迟（embedding、retrieval、rerank、generation）

**建议方案**:
- 新增 `app/rag/evaluation/perf_bench.py`
- 指标：
  - `e2e_latency_p50/p95/p99`：端到端查询延迟
  - `retrieval_latency`：纯检索延迟
  - `rerank_latency`：重排延迟
  - `embedding_latency`：嵌入延迟
  - `embedding_cost_per_query`：每次查询的 embedding API 成本
  - `throughput_qps`：查询每秒吞吐量
- 可作为 CI nightly job 运行，结果纳入回归门禁
- 前端 `/diagnostics` 增加 Performance 面板

**涉及文件**: `app/rag/evaluation/`, `scripts/`, `web/app/diagnostics/`

---

## Gap 9: 文档数据治理增强 — 保留策略 + 生命周期自动化

**现状**: 有 `archive`/`delete` 操作和审计日志，但无自动保留策略（如 90 天未访问自动归档）、无跨组件级联清理（文档删除后 KG 实体/向量/缓存的一致性清理）。

**行业标杆**:
- 企业级知识库要求：数据保留 SLA、自动过期、级联删除（文档 → chunks → vectors → KG 节点 → 缓存）
- 合规审计需要完整生命周期追踪

**建议方案**:
- 新增 `app/services/retention_policy.py`
- 支持策略：`max_age_days`、`max_inactive_days`、`max_versions`
- 按 dataset 级别配置保留策略
- 到期文档自动归档或删除，触发级联清理：
  1. 删除 chunks + 向量索引条目
  2. 删除/标记 KG 中仅由该文档产生的实体/关系
  3. 清除检索缓存和语义缓存中的相关条目
- 定时任务 (`cron_retention_sweep`) 每日扫描执行
- 审计日志记录每次保留操作

**涉及文件**: `app/services/`, `app/tasks/`, `app/core/config.py`, `app/rag/kg/repository.py`

---

## Gap 10: 解析 → 分块 → KG 端到端质量仪表盘

**现状**: 解析诊断 (`parsing/diagnostics.py`)、分块预览 (`chunk-preview/`)、KG 诊断 (`kg-diagnostics-page.tsx`) 分散在三个独立 UI 中。无法在一个视图中看到一个文档从原始文件到最终 KG 的完整质量链路。

**行业标杆**:
- 企业级数据管线必须有端到端 observability
- 每个文档应有 "health card"：解析质量 → 分块质量 → KG 覆盖 → 检索命中率

**建议方案**:
- 新增 `/knowledge/[id]/health` 页面（Document Health Card）
- 展示：
  - 解析阶段：解析器、质量评分、是否扫描件、解析耗时
  - 分块阶段：分块策略、chunk 数量、覆盖率、重叠浪费率、质量评分分布
  - KG 阶段：抽取的实体/关系数量、实体覆盖率、孤立实体比例
  - 检索阶段：该文档的 chunk 被检索命中的历史频率
- 整合到文档列表页，低质量文档标记告警

**涉及文件**: `web/app/knowledge/`, `app/api/v1/documents.py`, `app/api/v1/evaluations.py`

---

## 影响评估矩阵

| Gap | 实现复杂度 | 检索质量提升 | 行业差距 |
|-----|-----------|------------|---------|
| Gap 1 Contextual Retrieval | 中 | 高 (+49% recall) | 大 |
| Gap 2 Proposition Chunking | 中 | 高 (精确检索场景) | 中 |
| Gap 3 分块质量评分 | 低 | 中 (数据治理) | 中 |
| Gap 4 语义缓存 | 中 | — (延迟/成本) | 大 |
| Gap 5 Embedding 热切换 | 高 | 高 (零停机) | 大 |
| Gap 6 KG 去噪评分 | 中 | 高 (图质量) | 大 |
| Gap 7 Embedding Drift 监控 | 低 | 中 (预防退化) | 中 |
| Gap 8 Pipeline Perf Bench | 低 | — (可观测性) | 中 |
| Gap 9 数据保留策略 | 中 | — (治理) | 中 |
| Gap 10 端到端质量仪表盘 | 中 | — (可观测性) | 中 |

---

## 建议实施顺序

**Phase 1 — Quick Wins (1-2 周)**:
- Gap 3: 分块质量评分（低复杂度，立即可见数据治理价值）
- Gap 7: Embedding Drift 监控（低复杂度，预防隐性退化）
- Gap 8: Pipeline Perf Bench（低复杂度，建立性能基线）

**Phase 2 — 检索质量跃升 (2-4 周)**:
- Gap 1: Contextual Retrieval（中复杂度，recall +49% 的最高 ROI）
- Gap 4: 语义缓存（中复杂度，直接降低成本和延迟）
- Gap 6: KG 去噪评分（中复杂度，KG 检索质量提升）

**Phase 3 — 基础设施成熟 (3-5 周)**:
- Gap 2: Proposition Chunking（新分块策略，丰富精确检索能力）
- Gap 5: Embedding 热切换（高复杂度，但对长期运维至关重要）
- Gap 9: 数据保留策略（治理完善）

**Phase 4 — 可观测性闭环**:
- Gap 10: 端到端质量仪表盘（前端整合）
