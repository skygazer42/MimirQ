# RAG 后端 × 业界顶尖系统 Gap 分析（2026 Q2）

> **编写日期**：2026-04-18
> **范围**：`app/rag/`、`app/parsing/`、`app/deepdoc/`、`app/connectors/`、`app/storage/`、`app/core/`、`app/services/`
> **目标**：以论文前沿、优化角度、企业级三条线对标主流顶尖 RAG 栈（LlamaIndex 0.12 / LangChain 0.3 / RAGFlow / Dify / Haystack 2.x / AutoRAG / Microsoft GraphRAG / LightRAG / HippoRAG / Verba / Cognita / Unstructured / LlamaParse / Docling / Vespa / Qdrant Cloud / LangSmith / Arize Phoenix / Portkey），定位下一轮优化的高价值方向。

---

## 1. 能力全景与方法论

### 对标对象与维度

| 维度 | 主流参照 |
|---|---|
| RAG 框架 | LlamaIndex 0.12、LangChain 0.3、Haystack 2.x、RAGFlow、Dify、Verba、Cognita |
| 专项系统 | Microsoft GraphRAG、LightRAG、HippoRAG、AutoRAG（自动调优）、Self-RAG、CRAG |
| 解析管线 | Unstructured.io、LlamaParse、Docling（IBM）、MinerU、Marker、Nougat、Firecrawl、Chunkr |
| 嵌入 / 向量栈 | BGE-M3、Voyage-3、Cohere-v3、Jina v3、ColBERT v2、Qdrant/Vespa/Weaviate/Pinecone |
| 可观测 | LangSmith、Arize Phoenix、OpenLLMetry、Langfuse、Portkey |
| 安全 / Guard | Llama Guard 3、Prompt Guard-86M、NeMo Guardrails、Protect AI Rebuff |
| 推理 | vLLM、SGLang、TensorRT-LLM、LMDeploy |

### 评估视角

1. **质量**：answer faithfulness、citation precision、retrieval recall、rerank NDCG
2. **成本 / 时延**：P95 端到端、token 开销、缓存命中率
3. **可维护性**：模块边界清晰度、配置治理、线上调参
4. **企业合规**：多租户 ACL、审计、数据驻留、RTBF、SCIM
5. **前沿覆盖**：是否复现 2023–2025 顶会关键工作

### 本次评估总结

后端 RAG 栈在**解析多样性、切块细粒度、检索-重排层复杂度、评测完备性、KG 管线**五个维度已达到或超过业界头部开源方案。主要短板集中在**多模态输入、连接器生态、向量 DB 后端单一、输出侧安全、在线评测与成本治理**。大量前沿论文已在项目中有"影子"实现（HyDE role、community reports、contextual enrichment、多通道融合），但尚未形成"论文-默认开启-在线验证"的完整闭环。

---

## 2. 文档解析质量

### 业界标杆

- **Unstructured.io**：统一 element model（Title/NarrativeText/Table/Image），layout-aware PDF，表格 HTML 输出
- **LlamaParse**（LlamaIndex）：GPT-4o 级 VLM 驱动解析，金融/法律文档强
- **Docling**（IBM）：PDF→DoclingDocument，原生支持 reading order、TableFormer
- **MinerU / Marker / Nougat**：学术文档公式 + 排版
- **Firecrawl / Chunkr**：网页解析 + 智能切块组合

**关键论文 / 技术**：Nougat（2023，学术 PDF→Markdown）、MinerU（2024 PDF-Extract-Kit）、GOT-OCR 2.0（2024 通用 OCR）、DeepSeek-OCR（2025 超长文档）、ColPali（ICLR 2025，页面级视觉检索取代 OCR+布局分析）。

### 本系统现状

- `app/parsing/parsers/` 包含 **25 个后端**：DeepDoc / MinerU / Marker / Magic-PDF / Docling / TextIn / olmOCR / DeepSeek-OCR / PaddleVL / Qianfan OCR / GLM OCR / TCADP / markitdown / pandoc / ETL4LLM / csv / docx / excel / pptx / html / email / image / json / text / pdf base
- `app/deepdoc/vision/{layout_recognizer,table_structure_recognizer,ocr}.py` 提供自研 layout + TSR + OCR
- `app/parsing/enrich/`：`formula_ocr`、`image_caption`、`image_ocr`、`vlm_image_caption`、`table_markdown`、`seal_recognition`、`ocr_redaction`
- `app/parsing/processors/`：`cross_page_merge`、`vlm_correction`、`parse_cache`
- `app/parsing/quality/`：`document_quality`、`text_quality`、`ocr_validator`、`reading_order`、`benchmark`、`competition`
- `app/parsing/preprocess/`：`deskew`、`handwriting_cleanup`、`orientation`、`watermark`、`paddle_doc_preprocess`
- `app/parsing/routing.py`：多后端动态路由

### Gap

1. **页面级视觉检索（ColPali/ColQwen）缺失**：当前链路仍是 OCR→文本→embedding，未覆盖"跳过 OCR 直接用 VLM patch embedding 检索"这条新范式。
2. **表格深度理解**：有 `table_markdown` / `table_structure_recognizer`，但未看到"表格→结构化 schema→NL2SQL 查询"的闭环（TaPas / TAPEX 思路）。
3. **解析质量反馈环路未闭合**：`quality/` 有评分器但未见"低分→自动切换备选后端→再评估"的 fallback 仲裁，实际生产中会受低质 PDF 拖累。
4. **图表内容结构化**：有 `image_caption`/`vlm_image_caption`，但缺"图表→数据点抽取"（Chart-to-Table，DePlot 思路）。
5. **公式→LaTeX 的召回友好性**：`formula_ocr` 产物是否进入独立子索引、是否被语义检索 reachable 不明。

### 建议优化

- **P1** 新增 `app/parsing/parsers/colpali_parser.py`：接入 ColPali/ColQwen 做页面级视觉 embedding，输出 page-image + embedding 到独立子集合，检索时与文本通道融合
- **P1** 闭合 quality fallback：`routing.py` 增加 "分数 < 阈值自动触发第二后端 + 择优" 的仲裁策略
- **P2** 新增 `app/parsing/enrich/chart_to_data.py`：图表→结构化数据点，产物作为独立 chunk 类型（`chart_data`）入库
- **P2** 公式/表格/代码"三态索引"：每类给独立字段或子集合，检索时按 query 类型加权

---

## 3. 切块策略

### 业界标杆

- **Anthropic Contextual Retrieval**（2024）：为每个 chunk 生成 50–100 token 的文档上下文前缀，召回率 +35%
- **RAPTOR**（ICLR 2024）：自底向上聚类+摘要，形成树状索引，支持跨粒度检索
- **Late Chunking**（Jina AI 2024）：先对整文档 embedding，再按 chunk 边界做 mean pooling，避免边界信息损失
- **Proposition Indexing / Dense X Retrieval**（2023）：把文档拆成原子命题
- **Agentic Chunking / Semantic Double Merging**：LLM 判断边界
- **Small-to-Big / Parent-Document**：切小粒度索引，召回后扩父

### 本系统现状

- `app/rag/chunking/strategies/` 含 **70+ 垂类策略**：通用（token / recursive / semantic / sentence_window / proposition / parent_child / markdown_hierarchy / html_sections / pdf_layout / paper / outline）+ 垂类（docker_compose / ansible_playbook / github_actions / gitlab_ci / jira_ticket / git_commit_log / subtitles / stacktrace / latex_sections / postmortem_report / prd_spec / sop_steps / policy_manual_structured / meeting_minutes / resume_structured / openapi_spec / proto_schema / graphql_schema / terraform_hcl / junit_xml / log_events / http_trace ...）
- `contextual_enrichment.py` — Anthropic 风格已实现
- `chunking/utils/hierarchical.py` + `strategies/parent_child.py` — 层级结构
- `chunking/ragflow/` + `integrated_pipeline/` — RAGFlow 桥接
- `chunking/quality_scorer.py`、`app/services/chunk_quality_gate.py`、`chunk_quality_scoring.py`

### Gap

1. **RAPTOR 完整形态缺失**：虽有 hierarchical，但未见"聚类→LLM 摘要→父节点重新进索引→查询时多层匹配"的标准 RAPTOR 闭环。
2. **Late Chunking** 未实现：现有嵌入都是先切再嵌，未看到整文档 embedding→分段 pooling 的变体。
3. **Agentic Chunking** 偏弱：`semantic.py` 多为阈值法或句子相似度，缺 LLM-as-judge 做语义边界仲裁的实现。
4. **切块质量闭环未反传**：`quality_scorer` 仅打分不反向调整切块参数，缺"离线评测发现某数据集召回差→自动回退 / 提升 chunk_size"的自动调参。
5. **Contextual Retrieval 成本问题**：每 chunk 都要调 LLM 生成上下文，缺"仅对首次入库或失败召回样本生成"的增量策略。

### 建议优化

- **P1** 新增 `strategies/raptor.py`：递归聚类+摘要，输出多层 chunk（层号作为 metadata），检索时 orchestrator 可按层聚合
- **P1** 为 `contextual_enrichment.py` 增加"惰性增量"模式：仅对命中召回失败（evidence_gap 报警）的 chunk 反向补上下文
- **P2** 新增 `strategies/late_chunking_jina.py`：对接 Jina v3 long-context embedding，整文档 pass + boundary pooling
- **P2** 自动 chunker 调参：读取 `evaluation/` 的召回样本，根据失败模式（过大/过小/边界）微调默认 `chunk_size` / `overlap`
- **P3** Agentic chunker：LLM-as-judge 做边界决策，离线批处理高价值文档

---

## 4. 预处理与数据质量

### 业界标杆

- **去重**：SimHash / MinHash LSH 局部去重；Sentence-level near-dup（Data-Juicer / Dolma）
- **语言识别**：fastText / langdetect，多语文档分段处理
- **脱敏**：Presidio（Microsoft）、Scrubadub、Private-AI
- **Boilerplate 清理**：jusText / trafilatura（网页）、docstring 去除
- **Quality filter**：KenLM perplexity（C4/RefinedWeb 配方）
- **规范化**：Unicode NFC、空白合并、零宽字符剥离、CJK 全半角

### 本系统现状

- `app/rag/preprocessing/` 已覆盖：`boilerplate`、`cleaning`、`code_blocks`、`diagnostics`、`frontmatter`、`html_canonical`、`html_xpath`、`images`、`keyword`、`language`、`markdown_canonical`、`near_dedup`、`normalization`、`paragraph_dedup`、`pii_anonymizer`、`processor`、`quality_filters`、`references`、`rule_packs`、`rules`、`secrets`、`segmentation`、`simhash`、`stopwords`、`tables`、`tokenization`、`urls`
- `app/core/pii_redaction.py`、`app/rag/middleware/pii.py`
- `app/services/dataset_precheck_*`（6 个，含 near_dup_summary / risk_buckets / ingestion_suggestion / diff）
- `app/services/dataset_profile_*` — 数据集画像

### Gap

1. **KenLM perplexity 质量过滤缺失**：有 `quality_filters.py` 但未见困惑度级别的"低质低信息文档"过滤。
2. **跨文档全局去重**：`near_dedup`/`simhash` 偏局部，缺数据集间相似度矩阵 + 合并策略。
3. **Presidio / 大模型 PII 发现**：`pii_anonymizer` 基于规则，对新型 PII（账号 ID、内部编号）识别不足；缺 LLM 辅助 PII discovery。
4. **语言识别未驱动模型路由**：有 `language.py` 但未看到"中文→中文强 embedding，英文→英文强 embedding"的自动路由。
5. **Boilerplate 网页清理弱**：`html_canonical` 偏正规化，缺 trafilatura 级别的"正文抽取"。

### 建议优化

- **P1** 接入 **Presidio + LLM 双层 PII 发现**：规则侧仍保留，加一层 LLM-based PII classifier 抽样跑
- **P1** 新增 KenLM / 小模型 perplexity 过滤器：离线扫数据集，低质样本进"隔离区"待人工审
- **P2** 跨数据集全局去重：`dataset_precheck` 增加"候选合并" + "跨数据集近重复文档"报表
- **P2** 语言感知路由：语言标签→embedding provider 选择，落到 `embedding/factory.py`
- **P3** 引入 trafilatura 作为 HTML 正文抽取 fallback

---

## 5. 查询理解

### 业界标杆

- **Adaptive-RAG**（NAACL 2024）：query complexity classifier → 简单直答/单跳检索/多跳 agentic 分流
- **Step-Back Prompting**（2023）：抽象化查询再检索
- **HyDE**（2022）：生成伪答案再 embedding 检索
- **Multi-Query / RAG-Fusion**（2023）：多查询 + RRF
- **Query Decomposition**（IRCoT 等）：复杂问题分解
- **Clarification agent**：歧义问题主动反问

### 本系统现状

- `app/rag/policy/intent_router.py` + `intent_router_model.py` + `modality_router.py` + `must_recall.py` + `must_recall_auto.py` + `recall_obligation.py`
- `app/rag/retrieval/decomposition_chain.py` — 查询分解
- `app/rag/core/query_rewrite_strategy.py` — 重写策略
- `app/rag/query_expansion.py` + `app/query/expand.py` + `app/query/normalize.py`
- `app/rag/reranker/ltr.py` 中已见 `role_hyde`（`ltr.py:57,177`）→ HyDE 生成路径存在
- `app/rag/workflows/routing.py` — 工作流路由

### Gap

1. **Adaptive-RAG 完整路由器缺失**：有 `intent_router` 但未见"复杂度分类 → 走不同管线"的明确映射表；当前所有查询似都走 full orchestrator。
2. **Step-Back Prompting 未独立**：虽 decomposition_chain 有分解，但没有显式抽象化子问题通道。
3. **澄清/反问 agent** 未见：歧义查询直接走召回，无交互澄清。
4. **Multi-Query + RRF fusion 显式度**：orchestrator 层面的 RRF 系数是否可观测 / 可学习不明。

### 建议优化

- **P1** 新增 `app/rag/policy/complexity_classifier.py`：小模型（或规则）判定 simple / single-hop / multi-hop → 分别跳过检索 / 单通道 / 全 orchestrator
- **P1** 显式 `workflows/step_back.py`：抽象化问题与原问题双通道召回，结果合并
- **P2** 澄清 agent：confidence 低时返回结构化澄清问题（前端可展示选项卡）
- **P2** RRF 权重线上可观测 + LTR 学得

---

## 6. 检索层

### 业界标杆

- **Hybrid Search**：dense + sparse（BM25/SPLADE）+ RRF，已成基线
- **LongRAG**（2024）：长 chunk（4K+）配长上下文 LLM，减少 chunk 数量
- **Small-to-Big / Sentence-Window / Parent-Doc**：多粒度召回
- **Multi-Vector Late Interaction**：ColBERT / PLAID
- **Dense+Sparse co-training**：SPLADE++ / unicoil
- **BGE-M3**：一个模型同时产 dense/sparse/multi-vector 三态

### 本系统现状

- `app/rag/retriever.py:85 HybridRetriever`（5940 行）—— 向量 + BM25 + SPLADE + ColBERT ANN
- `app/rag/retrieval/orchestrator.py:1264 run_retrieval`（5188 行）—— 多通道编排
- `app/rag/retrieval/colbert_ann.py` — ColBERT ANN
- `app/rag/retrieval/sparse.py` + `sparse_prometheus_metrics.py`
- `app/rag/retrievers/multi_vector.py` — MultiVector（summary/HyDE/parent refs）
- `app/rag/retrieval/decomposition_chain.py` / `hierarchy_expand.py` / `contextual_followup.py` / `evidence_gap.py`
- `app/rag/core/retrieval_profiles.py` + `retrieval_config_fingerprint.py` — 检索画像

### Gap

1. **LongRAG 模式缺**：没有显式"超长 chunk + 长上下文 LLM"的配套 profile，当前 chunk_size 仍偏 RAG 1.0 时代参数。
2. **BGE-M3 一体化未用**：只有单独 dense / 单独 sparse，未利用 BGE-M3 单模型三态输出的效率红利。
3. **检索 fusion 学得**：RRF 常数 k 是否随数据集微调、是否有 per-tenant 学到的权重，未见。
4. **检索可解释性**：`retrieval_explain.py` API 存在，但是否在前端还原"为什么这个 chunk 进 top-k"的特征贡献，取决于 LTR 是否暴露。

### 建议优化

- **P1** 加一个 `retrieval_profiles.py` 预置："long_context"：chunk_size=4096、top_k=8、rerank_top_n=4，配合长上下文 LLM
- **P1** 接入 **BGE-M3 三态索引**：同一 passage 同步产 dense + sparse + colbert 向量，省一次 embedding 开销
- **P2** RRF 权重 per-tenant 学习：基于 feedback / ragas 评分线上微调
- **P3** 检索可解释性前端：retrieval_explain API 产出 LTR 特征权重，暴露到 UI 供调试

---

## 7. 重排层

### 业界标杆

- **BGE Reranker v2-m3 / v2-gemma / v2-minicpm**：多语言、长文本 reranker
- **RankGPT / RankZephyr / RankLLaMA**：listwise LLM reranker
- **Cohere Rerank v3 / Voyage Rerank-2**：商业 API 顶级
- **LTR 在线学习**：pairwise / listwise LambdaMART
- **MMR / Diversity**：结果多样性
- **Calibration**：分数校准成概率

### 本系统现状

- `app/rag/reranker/{cross_encoder,colbert,llm_based,ltr,kg,parent_child,dashscope,openai,hybrid}.py` —— **9 个实现**
- `app/rag/rerank_result_cache.py`
- `app/rag/reranker/ltr.py` feature spec v3（`ltr.py:90`）含 fusion/field-aware signals

### Gap

1. **Listwise LLM rerank**：有 `llm_based.py`，但不确定是否是 RankGPT 风格的 listwise（一次性看所有候选排序）还是 pointwise（逐个打分）。
2. **Diversity / MMR**：未见独立 MMR 实现，相似答案可能挤占 top-k。
3. **BGE Reranker v2 系列专用适配**：有 cross_encoder，但 BGE v2 系列（尤其 gemma/minicpm 长文变体）未单独优化。
4. **Rerank 分数校准**：LTR 输出是否是校准概率不明。

### 建议优化

- **P1** 确认 `llm_based.py` 为 listwise 模式，若非则新增 RankGPT listwise 变体
- **P1** 加独立 **MMR reranker**：top-k 后做多样性去冗，λ 可配置
- **P2** 新增 `reranker/bge_v2.py` 专用适配（支持 v2-m3 / gemma / minicpm 不同长度预算）
- **P3** Rerank score calibration：用历史 ground-truth 做 Platt scaling / isotonic regression

---

## 8. 生成与 Agent 模式

### 业界标杆

- **Self-RAG**（NeurIPS 2023）：reflect tokens（`[Retrieve]`, `[IsRel]`, `[IsSup]`, `[IsUse]`）
- **CRAG**（2024）：retrieval quality evaluator → correct/ambiguous/incorrect 分流，incorrect 触发 web search
- **FLARE**（EMNLP 2023）：生成中低置信度段落触发再检索
- **Plan-Execute / Plan-and-Solve**：先规划再执行
- **ReAct / Reflexion**：思考-行动-反思
- **AutoGen / CrewAI / LangGraph**：多智能体协作
- **Tree-of-Thoughts / Graph-of-Thoughts**

### 本系统现状

- `app/rag/engine.py:188 RAGEngine`（4090 行）+ `app/rag/pipelines/langgraph.py`（1751 行）
- `app/rag/workflows/{chain,evaluator_optimizer,parallelization,planner_worker,react,routing}.py`
- `app/rag/agents/{rag_agent,multi_agent,prebuilt}.py`
- `app/rag/tools/{mcp_client,mcp_tools,simple_kb_search}.py`
- `app/rag/memory/{short_term,long_term}.py`
- `app/rag/checkpointer/{memory,sqlite,time_travel}.py` — LangGraph checkpointer 完整

### Gap

1. **Self-RAG reflect tokens 完整实现缺**：`evidence_retrieve_gate.py` 有检索门控，但未见 Self-RAG 四种特殊 token 的生成+解析闭环。
2. **CRAG 未接入 streaming 主路径**：`evidence_gap.py` + `must_recall.py` 有 gap 检测，但 incorrect→web search fallback 未落实（连接器没 web search）。
3. **FLARE 主动检索**：生成过程中基于置信度再检索，未见实现。
4. **Web search tool 缺**：`tools/` 只有 `simple_kb_search` + MCP，没有 Serper/Tavily/Brave/Exa。
5. **ToT / GoT reasoning**：planner_worker 已有，但 tree/graph 结构推理未见。

### 建议优化

- **P1** 新增 `tools/web_search.py`（Serper + Tavily + Brave fallback），作为 CRAG incorrect 分支的兜底；接入 streaming 管线
- **P1** `workflows/self_rag.py`：实现 reflect tokens 生成-解析-再检索闭环（可先用 prompt-based，后续可微调专用模型）
- **P2** `workflows/flare.py`：token-level confidence → 低置信触发再检索
- **P3** 探索 ToT/GoT reasoning 用于多跳分析类查询

---

## 9. KG / GraphRAG

### 业界标杆

- **Microsoft GraphRAG**（2024）：entity+relation 抽取 → Leiden 社区检测 → 层级 community report → global/local/DRIFT search
- **LightRAG**（2024）：双层检索（low-level 实体 + high-level 关系），简化 GraphRAG 成本
- **HippoRAG**（NeurIPS 2024）：Personalized PageRank 在实体图上，神经生物启发
- **Temporal KG**：时间敏感 RAG（Zep / Graphiti）
- **nano-graphrag**：轻量复刻

### 本系统现状

- `app/rag/kg/` 完整管线：
  - `extraction/{extractor,hybrid_extractor,gliner_extractor,alias,entity_verifier,relation_processor,relation_verifier,skill_processor,evidence,parser,backend_router}.py`
  - `loading/processor.py`
  - `search/{recall,expand,graph_embeddings,ranking,query_mode,searcher,cache,tracker,relation_scoring}.py`
  - `quality/{kg_completeness_scorer,kg_denoiser}.py`
  - `community.py`（LLM community reports，`community.py:23` 导入 BaseLLMClient）
  - `provenance`、`ontology`、`snapshot`、`pipeline`
- `app/rag/reranker/kg.py` — KG reranker
- `app/rag/evaluation/kg_search_diagnostics*.py`、`kg_hardcase_*.py`

### Gap

1. **Global/DRIFT search 完整度**：`community.py` 有报告，但"query 先路由到相关社区→仅在该社区内展开"的 DRIFT search 路径未见显式实现。
2. **HippoRAG PPR**：`graph_embeddings.py` 有图嵌入，但未见 Personalized PageRank 召回。
3. **Temporal KG**：`snapshot.py` 有快照，但时间敏感查询（"X 在 2024 年是什么状态"）是否路由到 snapshot 不明。
4. **Community 层级迭代**：Microsoft GraphRAG 有 C0/C1/C2/C3 多层，我们的 community 生成层级深度未见。
5. **LLM 抽取成本**：完整抽取对大数据集成本高，缺"采样抽取 + 冷启动"策略。

### 建议优化

- **P1** `kg/search/drift_search.py`：查询→社区摘要匹配→选 top 社区→内部展开
- **P2** `kg/search/pprank.py`：实体启动 + PPR 分布作为召回分
- **P2** 引入温度敏感节点 → 查询时自动选择 snapshot 版本
- **P2** Community 多层级：L0 细粒度 / L1 中粒度 / L2 全局，查询按复杂度选层

---

## 10. 多模态 RAG

### 业界标杆

- **ColPali / ColQwen**（ICLR 2025）：PDF 页面视觉 patch embedding，跳过 OCR
- **VideoRAG / VideoAgent**（2024）：视频分段 + 关键帧 + ASR + 视觉 embedding 联合检索
- **音频 RAG**：Whisper 转录 + 说话人 diarization + timestamp alignment
- **表格深度 QA**：TaPas / TAPEX / NL2SQL pipeline
- **图文混合**：CLIP-based + multi-modal LLM 直接消费

### 本系统现状

- `app/rag/embedding/clip_embedder.py` — CLIP embedder
- `app/rag/core/vision_reader.py` — 视觉读取
- `app/parsing/enrich/vlm_image_caption.py` — VLM caption
- `app/rag/middleware/context_injection.py` — 可能注入多模态内容
- **视频 / 音频 parsers 未见**（`parsers/` 列表里无 video/audio）

### Gap

1. **视频 RAG 缺失**：无视频分段、关键帧抽取、ASR 集成
2. **音频 RAG 缺失**：无 Whisper 接入、无说话人 diarization
3. **ColPali 级页面视觉检索** 未实现（见第 2 节）
4. **表格深度 QA**：有 table 切块，缺 NL2SQL/TaPas 组件
5. **多模态 query**：用户上传图片作为查询未见完整链路

### 建议优化

- **P1** 新增 `app/parsing/parsers/video_parser.py` + `audio_parser.py`：分段 + Whisper + 关键帧；产出多模态 chunk
- **P1** 多模态 query：`app/api/v1/rag.py` 增加 `query_image` 字段，`retriever` 路由到 CLIP 子集合
- **P2** `app/rag/tools/nl2sql.py` + 表格子集合：结构化表格→NL2SQL→执行
- **P2** 接入 ColPali（见第 2 节）

---

## 11. Embedding / 向量栈

### 业界标杆

- **BGE-M3**：中英多语、同模型产 dense+sparse+multi-vector
- **Voyage-3 / Voyage-code-3**：商业顶级，代码向量尤其强
- **Cohere Embed v3**：quantization-aware
- **Jina v3**：long-context + Matryoshka
- **Matryoshka Representation Learning**：同一向量支持 128/256/512/1024 维度自适应
- **ColBERT v2 / PLAID**：late interaction
- **向量 DB**：Qdrant（简单高效）/ Weaviate（多模态）/ Vespa（超大规模）/ Pinecone Serverless

### 本系统现状

- `app/rag/embedding/providers/{dashscope,local,ollama,openai}.py` — **仅 4 个 provider**
- `app/rag/embedding/{adapter,base,config,factory,utils}.py`
- `app/rag/embedding/clip_embedder.py`
- `app/storage/vector/milvus.py` + `factory.py` — **仅 Milvus**
- 默认模型记忆显示 BGE-M3（配置侧）

### Gap

1. **Provider 覆盖不足**：缺 Voyage / Cohere / Jina / Bedrock / Azure / BGE 专用（HF Endpoint）
2. **Matryoshka 未用**：即使用 BGE-M3 也没利用其 Matryoshka 维度裁剪特性（高查询截 256 维，低查询用 1024）
3. **向量 DB 单一**：Milvus 强但部署重；Qdrant 轻便、Vespa 大规模、PGVector 省运维，抽象层薄
4. **代码向量专用通道缺**：代码查询与自然语言共用 embedder，Voyage-code-3 级优化未引入
5. **Multi-vector 存储**：ColBERT ANN 有实现，但存储是否按 late interaction 优化（PLAID 压缩）不明

### 建议优化

- **P1** `embedding/providers/{voyage,cohere,jina,bedrock}.py` 扩容
- **P1** `storage/vector/{qdrant,pgvector}.py` + factory 路由；保留 Milvus 默认
- **P2** `embedding/matryoshka.py`：BGE-M3 输出多维度切片；orchestrator 根据查询复杂度选维度
- **P2** 代码向量子通道：`embedding/code_embedder.py` 用 Voyage-code-3 或 CodeBERT
- **P3** PLAID 压缩 ColBERT 存储

---

## 12. LLM 栈与路由

### 业界标杆

- **vLLM / SGLang / TensorRT-LLM / LMDeploy**：高吞吐本地推理
- **LiteLLM / Portkey**：100+ provider 统一接口 + 智能路由 + fallback + semantic cache
- **Speculative decoding / Continuous batching**：推理加速
- **Prompt caching**：Claude prompt cache、OpenAI prompt caching
- **Semantic cache**：GPTCache 风格（embedding 相似度命中）

### 本系统现状

- `app/rag/llm/{base,factory,fallback,langchain_chat,models,prompt_cache}.py`
- `app/rag/middleware/{dynamic_model,dynamic_prompt}.py`
- `app/services/chat_response_cache.py`、`corpus_cache_tokens.py`
- **未见 vLLM / SGLang 直接集成**（可能通过 OpenAI 兼容接口间接使用）
- **未见 semantic cache**（cache 都是 key 精确命中）

### Gap

1. **本地推理栈缺显式封装**：如果企业版想自托管，当前对 vLLM/SGLang 的声明性支持薄弱
2. **Semantic cache 缺失**：同义查询必然 cache miss，成本浪费
3. **智能路由未见成本感知**：`dynamic_model` 可切模型，但没看到"简单查询用小模型、复杂用大"的 cost-aware 路由
4. **Prompt cache 利用率观测**：`prompt_cache.py` 存在，但命中率 / cost 节省未纳入 metrics

### 建议优化

- **P1** `llm/semantic_cache.py`：query embedding + 阈值命中缓存响应（命中记 audit + re-rank 仍跑）
- **P1** 成本感知路由：intent_router 输出复杂度 → llm factory 选型（nano/small/large），并记 per-query cost
- **P2** `llm/vllm_adapter.py` + `sglang_adapter.py`：显式 provider，暴露 TTFT / tokens/s metrics
- **P3** Prompt cache 命中率 metric 到 Prometheus + dashboard

---

## 13. 安全与合规

### 业界标杆

- **Llama Guard 3** / **Prompt Guard-86M**：Meta 轻量专用防护模型
- **NeMo Guardrails**（NVIDIA）：对话策略 DSL
- **Protect AI Rebuff**：prompt injection 专门工具
- **Presidio**：结构化 PII
- **数据驻留**：Region pinning + 跨境管控
- **RTBF 级联删除**：vector DB + KG + cache + object storage

### 本系统现状

- `app/rag/safety/input_guard.py`（157 行）—— 覆盖 role hijack / instruction override / system prompt probe / delimiter attack / HTML entity / zero-width / base64 / indirect injection via history
- `app/rag/safety/output_guard.py`（**仅 35 行**）
- `app/rag/safety/{metrics,rules}.py`
- `app/rag/middleware/pii.py`、`app/core/pii_redaction.py`
- `app/rag/preprocessing/{pii_anonymizer,secrets}.py`
- `app/services/audit_log_*` + `app/api/v1/audit.py`

### Gap

1. **Output guard 严重不对等**：35 行 vs 157 行 input guard，输出侧的 PII 泄露 / jailbreak 回传 / hallucination 检测几乎空白
2. **LLM-based guard 未引入**：当前全是正则 / 规则，Prompt Guard-86M 级的深度防御层缺失
3. **RTBF 级联自动化缺**：有 audit_log_retention 但不确定用户数据从向量 DB / KG / cache / 对象存储的级联撤销是否自动
4. **数据驻留**：未见 region 配置 / 多区域数据路由
5. **红队 / 攻击样本评测**：`evaluation/` 里未见专门的 jailbreak red-team 数据集

### 建议优化

- **P1** 扩容 `output_guard.py`：加 PII 二次检测（Presidio）+ 引用源一致性（答案实体必须在 context 中出现）+ Llama Guard 3 LLM 判定；失败→重写或拒答
- **P1** `safety/llm_guard.py`：集成 Prompt Guard-86M / Llama Guard 3 作为二层检测
- **P2** RTBF 工作流：`app/api/v1/rbac.py` 增加"delete_user_data" → 级联触发 vector/KG/cache/object storage 清理，带可追溯日志
- **P2** 红队数据集：`evaluation/redteam_suite.py`，定期跑
- **P3** 多区域支持：`core/config.py` 引入 `DATA_REGION`，storage/provider 按 region 路由

---

## 14. 评测体系

### 业界标杆

- **RAGAS**：faithfulness / answer relevance / context precision / context recall
- **TruLens**：feedback functions + dashboards
- **Arize Phoenix**：开源 LLM observability + eval
- **DeepEval**：单元测试级 eval
- **Online eval**：shadow traffic + A/B 实验 + 自动回归数据集生长
- **Chunk quality 闭环**：召回质量反向驱动切块参数

### 本系统现状

- `app/rag/evaluation/ragas.py`（**1753 行**，完整）
- `evaluation/{agent_evals,chunk_diagnostics,evidence_retrieve_gate,hard_negative_mining,kg_hardcase_deterministic,kg_hardcase_generator,kg_search_diagnostics,kg_search_diagnostics_metrics,multihop,perf_bench,regression_sample_builder,replay_capture,test_generator}.py`
- `app/services/chunk_quality_gate.py` + `chunk_quality_scoring.py`
- `app/api/v1/evaluations.py`

### Gap

1. **Online shadow eval 基础设施缺**：有 replay_capture 但未见"线上流量双跑→离线比对"的完整 shadow infra
2. **A/B 实验框架**：没看到明确的 experiment_id + variant 切流 + 统计显著性
3. **Phoenix / TruLens 集成**：有 ragas，缺这两个交互式 dashboard 工具集成
4. **chunk quality 闭环自动化**：有评分器但未见"低分→自动调参→重建索引→再评测"闭环
5. **LLM-as-judge 成本优化**：ragas 等走大模型成本高，未见抽样 + 小模型初筛策略

### 建议优化

- **P1** `evaluation/online_shadow.py`：生产流量 sample → 离线双管线跑 → diff 报表（每日）
- **P1** `evaluation/ab_experiment.py`：基于 tenant/user hash 切流，记 variant 到 audit，统计 faithfulness / latency 差异
- **P2** 集成 Arize Phoenix：tracing 侧已有 LangSmith，加 Phoenix adapter
- **P2** chunk quality 闭环：评估失败样本 → 推荐切块参数 → 生成 `dataset_precheck_ingestion_suggestion`（已有文件）
- **P3** Judge 成本优化：小模型抽样初筛 + 大模型采样复核

---

## 15. 可观测与成本

### 业界标杆

- **LangSmith**：trace、eval、dataset、playground 一体化
- **Arize Phoenix**：OSS、span 级 trace、eval 内置
- **OpenLLMetry**（Traceloop）：OpenTelemetry 标准，多 provider
- **Langfuse**：OSS、多租户、cost tracking 强
- **Portkey**：AI gateway，cost + routing + cache 一体
- **SLO**：P95 延迟、引用准确率、rerank NDCG 阈值

### 本系统现状

- `app/rag/tracing/langsmith.py`（LangSmith 已接入）
- `app/rag/trace_schema.py`（145 行，自研 schema）
- `app/rag/metrics_sli.py`（102 行 SLI 指标）
- `app/core/otel.py`、`app/core/metrics.py`、`app/core/sentry.py`
- `app/api/v1/metrics.py` + `observability.py` + `ragviz.py`
- `app/storage/vector/milvus_prometheus_metrics.py`、`app/services/authz_prometheus_metrics.py`、`connector_acl_prometheus_metrics.py`、`sparse_prometheus_metrics.py`

### Gap

1. **OpenLLMetry / OpenTelemetry LLM semantic conventions 对齐** 未明确（有 otel.py 但未确认是否符合 LLM span 标准）
2. **Phoenix / Langfuse 备份** 未集成（只有 LangSmith，单点依赖）
3. **Per-trace cost breakdown**：token 消耗、API cost、按 tenant / user / dataset 归因未见聚合报表
4. **Per-tenant quota / rate limit**：未见 `app/core/` 里月度 token 预算控制（有 rate limit 基础，缺 token 维度）
5. **SLO dashboard**：P95 检索 / 引用准确率 / rerank NDCG 是否在 Grafana 打板不明

### 建议优化

- **P1** `core/cost_tracker.py`：每次调用统一记录 provider/model/input_tokens/output_tokens/cost_usd，落 Prometheus + DB；按 tenant/dataset 聚合
- **P1** Per-tenant 月度 token quota：`services/tenant_quota.py` + 超限告警/软限
- **P2** 接入 Langfuse 作为第二 tracing（OSS + 多租户原生）
- **P2** SLO dashboard：retrieval latency P95 / citation precision / faithfulness / guard rate 全量打板
- **P3** 对齐 OpenLLMetry semantic conventions（`gen_ai.*` span 属性）

---

## 16. 企业级

### 业界标杆

- **连接器生态**：Unstructured Serverless / Airbyte / Fivetran / Apache Camel Kafka connectors
- **数据血缘**：Marquez / OpenLineage
- **Chunk-level ACL**：Vespa streaming mode / Qdrant group_id filter + authz
- **多区域部署**：data residency
- **灾备**：跨区域异步复制
- **SCIM + IdP**：Okta / Azure AD / Keycloak 深度集成
- **RAG-as-a-service**：per-tenant 子租户、白标

### 本系统现状

- `app/connectors/base.py:11` ABC 基类存在；但 `app/connectors/db/` 里**只有数据库 catalog 相关**（catalog_connectors / runner / introspection / profile_privacy）
- `app/services/connector_*`（registry/reconcile/sync_state/acl_mapping/source_acl）—— 框架齐，但实现源只有 db
- `app/api/v1/{scim,rbac,groups}.py`、`app/models/{tenant,tenant_group,group_permissions}.py`
- `app/services/audit_log_retention.py`、`audit_log_service.py`
- `app/services/access_graph_diff_service.py` — ACL 差异对比
- `app/api/v1/{governance,observability,retrieval_explain,retrieval_profiles,rag_config_templates,retrieval_config_hash}.py` — 治理接口

### Gap

1. **连接器生态空心**：ABC + 注册表 + sync state 全有，**但只有 db 一种实现**。SharePoint / Confluence / Notion / Slack / GitHub / Jira / GDrive / S3 / OneDrive / Dropbox / Web 全缺
2. **数据血缘**：有 provenance 但未形成"doc→chunk→embedding→retrieval→answer→citation"的端到端 lineage API
3. **Chunk-level ACL 过滤**：`connector_source_acl_mapping.py` 有映射，但向量检索时是否用 partition/filter 强过滤未见完整落实
4. **灾备 / 多区域**：core/config 里未见 region / 多活配置
5. **RTBF 自动化**（同第 13 节）
6. **白标 / 多租户子组织**：tenant 存在，sub-tenant / workspace 层次不明

### 建议优化

- **P1** 补连接器：优先 SharePoint + Confluence + Notion + GitHub + S3，按业务画像决定第 1 批 5 个
- **P1** Chunk-level ACL 端到端审查：`retriever.py` 中强制注入 tenant/group filter，并出"ACL escape"测试用例
- **P2** `lineage/` 模块：`app/services/lineage_service.py`，把 chunk_id → doc_id → connector_source → user_acl → retrieval_run → citation 串起来，暴露 `/api/v1/lineage` 查询
- **P2** 多区域 PoC：config 引入 region，storage/provider 按 region 路由，文档对象存储选 region bucket
- **P3** Sub-tenant / workspace 模型：多层 tenant 树

---

## 优先级矩阵（Impact × Effort）

| 象限 | 优化项 | 依据 |
|---|---|---|
| **Quick Wins**（高 Impact，低 Effort，1–3 周） | CRAG 接入 streaming 主路径 + Web search tool（Serper/Tavily）；Output guard 扩容 + Presidio；Semantic cache；BGE-M3 一体化三态索引；MMR diversity rerank；Per-trace cost tracker；Adaptive-RAG complexity classifier；惰性 contextual enrichment | 这些多数已有"影子"实现或组件齐备，临门一脚 |
| **战略投入**（高 Impact，高 Effort，1–3 月） | 连接器生态 5 个（SharePoint+Confluence+Notion+GitHub+S3）；多模态 RAG（视频+音频 parser）；RAPTOR；向量 DB 多后端（Qdrant+PGVector）；Self-RAG workflow；Chunk-level ACL 闭环 + 红队测试；Online shadow eval infra；ColPali 页面视觉检索 | 需改架构或新模块，但一次投入长期红利 |
| **补强**（中 Impact，低 Effort，可并行） | Embedding provider 扩容（Voyage/Cohere/Jina）；Listwise LLM rerank 确认；BGE Reranker v2 适配；Late Chunking；KG DRIFT search；Langfuse/Phoenix 接入；Step-Back Prompting；KenLM 质量过滤 | 单点增强，不阻塞主线 |
| **延后 / 观望** | RA-DIT 联合微调；自建 vLLM 分布式集群；Tree-of-Thoughts 通用化；HippoRAG PPR；多区域部署（除非合规要求）；PLAID ColBERT 压缩 | ROI 在当前规模下不划算或路径不成熟 |

---

## 实施路线建议

**2026 Q2（6 周）**：全部 Quick Wins + 连接器前 3（SharePoint / Confluence / Notion）+ RAPTOR + Self-RAG PoC + Output guard

**2026 Q3（12 周）**：多模态 RAG（视频+音频）+ ColPali + Qdrant 作为第二后端 + Online shadow eval + Chunk-level ACL 闭环 + Listwise rerank + Embedding provider 扩容

**2026 Q4**：视实际采用情况决定 LongRAG / HippoRAG / Tree-of-Thoughts / 多区域

---

## 参考论文与工程资料

### 核心论文

- Self-RAG: Learning to Retrieve, Generate, and Critique (Asai et al., NeurIPS 2023)
- Corrective Retrieval Augmented Generation (Yan et al., 2024)
- RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval (Sarthi et al., ICLR 2024)
- HippoRAG: Neurobiologically Inspired Long-Term Memory for LLMs (Gutiérrez et al., NeurIPS 2024)
- Adaptive-RAG: Learning to Adapt Retrieval-Augmented LLMs through Query Complexity (Jeong et al., NAACL 2024)
- LongRAG: Enhancing Retrieval-Augmented Generation with Long-context LLMs (Jiang et al., 2024)
- From Local to Global: A Graph RAG Approach to Query-Focused Summarization (Edge et al., Microsoft 2024)
- LightRAG: Simple and Fast Retrieval-Augmented Generation (Guo et al., 2024)
- FILCO: On Learning to Retrieve Context for Textual Generation (Wang et al., NeurIPS 2023)
- FLARE: Active Retrieval Augmented Generation (Jiang et al., EMNLP 2023)
- ColPali: Efficient Document Retrieval with Vision Language Models (Faysse et al., ICLR 2025)
- Dense X Retrieval / Proposition Indexing (Chen et al., 2023)
- Matryoshka Representation Learning (Kusupati et al., NeurIPS 2022)
- BGE-M3: Multi-Lingual, Multi-Functional, Multi-Granularity (Chen et al., 2024)
- RankGPT / RankZephyr / RankLLaMA（listwise LLM reranker 系列）
- RA-DIT: Retrieval-Augmented Dual Instruction Tuning (Meta, 2023)
- Late Chunking: Contextual Chunk Embeddings (Jina AI, 2024)
- Nougat: Neural Optical Understanding for Academic Documents (Meta, 2023)

### 工程参考

- Anthropic Contextual Retrieval 博客（2024-09）
- Microsoft GraphRAG 官方仓库
- Unstructured.io、LlamaParse、Docling 技术文档
- Meta Llama Guard 3 / Prompt Guard-86M 模型卡
- Vespa streaming mode 文档（chunk-level ACL 最佳实践）
- OpenLineage 规范、OpenTelemetry LLM semantic conventions

---

> **下一步**：对 Quick Wins 象限的每一项，拆成独立 plan（约 500–2000 行实现粒度），按优先级单独执行；战略项先做设计 RFC 后再拆 plan。

---

## 14. 2026-05-01 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口.

已落地:
- RAG 核心短板已补齐到产品可用层:Self-RAG、CRAG streaming、web search、hierarchical retrieval、context expand、MMR、local BGE、long-context rerank、retrieval profiles 已进入 `app/rag/` 与 API/UI 路径.
- 质量与成本治理已具备闭环:semantic cache、tenant quota、cost tracker、evaluation/ablation、POC attribution、precheck scanner 已有服务和测试覆盖.
- 安全合规已覆盖输出防护、PII、redteam、RTBF、lineage、SCIM/SAML 等企业必需能力.
- 前端已经把诊断、评测、反馈、入库监控、隔离、KG 可视化等新增能力产品化,不再集中堆在诊断工作台.

暂缓:
- 暂缓商业 embedding / rerank provider 矩阵、向量数据库替换矩阵、SharePoint/Confluence/Notion 等连接器生态和多模态 parser 大扩容.
- 暂缓把所有外部 SOTA benchmark 常驻仓库,真实客户数据不足时做全量榜单没有产品收益.

Directive: 本文后续仅作为能力雷达参考;新投入必须拆独立 RFC/plan 并说明真实业务触发条件.
