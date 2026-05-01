# RAG 后端深度调研报告（2026 Q2）

> **编写日期**：2026-04-18
> **定位**：上一份 `plans/rag-capability-gap-2026-q2.md` 是基于代码 + 内部知识的对标；本份是**增补深化版**，引入 2025–2026 最新 arxiv 论文、ICLR'26 / NeurIPS'25 / CVPR'25 benchmark 数据、以及主流系统的量化对比。
> **阅读价值**：读完知道"2025/2026 我们应该抄哪些论文、对哪些基准优化、规避哪些坑"。
> **体例**：每章固定四块——①业界前沿（arxiv ID / benchmark）；②本系统现状（文件:行号）；③量化 Gap；④建议（P0/P1/P2）。

---

# 第一部分　研究视角

## 1. 调研方法论

### 对标对象

| 类别 | 参照 |
|---|---|
| 系统（企业级） | RAGFlow、Dify、LlamaIndex 0.12、LangChain 0.3、Haystack 2.x、Cohere Coral、Vectara、Ragie、Verba、Cognita、nano-graphrag |
| 研究型 | Self-RAG、CRAG、FLARE、Adaptive-RAG、FILCO、Self-Route、RAPTOR、HyDE |
| KG / Graph | Microsoft GraphRAG、LazyGraphRAG、LightRAG、HippoRAG / HippoRAG2、PathRAG、OG-RAG、LinearRAG、CommunityKG-RAG |
| Agentic | A-RAG、Interact-RAG、RAGShaper、RAG-Critic、EviOmni、TreePS-RAG、Self-Reasoning |
| Multimodal | ColPali、ColQwen、VideoRAG（多种）、DrVideo、Voice-Vision RAG |
| 解析 | Unstructured、LlamaParse、Docling、MinerU、Marker、Nougat、Mathpix、NVIDIA Nemotron、Ferrules |
| Embedding / DB | BGE-M3、Voyage-3、Cohere v3、Jina v3、ColBERT v2；Milvus / Qdrant / Weaviate / Vespa / Pinecone Serverless |
| 评测 / Observ | RAGAS、TruLens、Phoenix、DeepEval、Weights & Biases、Langfuse、Portkey |
| 推理 | vLLM、SGLang、TensorRT-LLM、LMDeploy |

### 评估维度

1. **质量**：faithfulness / answer relevance / context precision / context recall / citation accuracy / NDCG / MRR
2. **成本与时延**：token 开销、P95 延迟、索引成本、缓存命中率
3. **可维护性**：模块边界、配置治理、线上调参、可解释
4. **合规**：ACL、审计、驻留、RTBF、SCIM
5. **前沿覆盖**：2023–2026 关键论文的落地程度

### 基准清单

- **GraphRAG-Bench**（ICLR 2026）—— KG-RAG 权威
- **OmniDocBench**（CVPR 2025）—— 文档解析权威
- **RAGBench / CRAG / LegalBench-RAG / WixQA / T²-RAGBench** —— 场景评测
- **MTEB**（检索 embedding 权威）
- **RAGCap-Bench**（2026）—— agentic 中间任务能力
- **Vectara NAACL 2025 (arXiv:2410.13070)** —— 25×48 切块/嵌入配置网格

---

## 2. 2025–2026 综述概览

五篇核心 survey：

1. **A Comprehensive Survey of RAG: Evolution, Current Landscape and Future Directions**（arXiv:2410.12837, Oct 2024）：提出 Naive→Advanced→Modular 三代演进、retrieval-generation-augmentation 三脚架。
2. **Architectures, Enhancements, Robustness Frontiers**（arXiv:2506.00054, May 2025）：按 retriever-centric / generator-centric / hybrid / robustness-oriented 分类；列出"自适应架构、实时检索、多跳结构化推理、隐私保留检索"为开放挑战。
3. **Agentic RAG Survey**（arXiv:2501.09136, Jan 2025）：agent cardinality / control / autonomy / knowledge representation 四维分类；四大 pattern = reflection / planning / tool use / multi-agent。
4. **SoK: Agentic RAG Taxonomy**（arXiv:2603.07379, Mar 2026）：把 agentic 检索-生成循环**形式化为 POMDP**，识别 cascading tool vulnerability、memory poisoning、compounding hallucination 等系统性风险。
5. **Reasoning RAG via System 1 or System 2**（arXiv:2506.10408, Jun 2025）：把"何时、何物、如何检索"纳入推理轨迹，分 predefined reasoning（System 1）和 agentic reasoning（System 2）。

另有 **Multimodal RAG Survey**（llm-lab-org，Feb→Jun 2025）覆盖 audio / video / ColPali / agentic 交互。

---

## 3. RAG 演进路径

```
Naive RAG (2022–2023)
  └→ retrieve-then-read，固定 chunker + 单 dense vector
Advanced RAG (2023–2024)
  └→ pre-retrieval（rewrite/expand）+ post-retrieval（rerank/compress）+ hybrid search
Modular RAG (2024)
  └→ 可插拔管线：routing、scheduling、fusion、iterative、corrective、adaptive
Agentic RAG (2024–2025)
  └→ autonomous agents：reflection / planning / tool use / multi-agent
Reasoning RAG (2025–2026)
  └→ System 2 思考：决策何时检索、检索什么、多跳规划
```

**我方位置**：已经进入 **Modular RAG + Agentic RAG 起步期**（`workflows/{react,planner_worker,evaluator_optimizer,parallelization,routing}.py`）。Reasoning RAG 层面仍缺 System 2 显式决策（如 A-RAG 的 hierarchical retrieval interfaces 暴露给 agent）。

---

# 第二部分　质量提升线

## 4. 文档解析

### 4.1 业界前沿（2025–2026）

- **OmniDocBench**（CVPR 2025，arXiv:2412.07626）：PDF 解析权威基准，含 layout、OCR、TSR、reading order、公式子任务。
- **MinerU 2.5**（2026）：OmniDocBench 得分 **86.2**（v1.5 pipeline 模式），超越自家 VLM 版（MinerU 2.0-2505-0.9B）；L4 GPU **0.21s/页**；已移除 AGPLv3 / CC-BY-NC-SA 4.0 模型，**可商用**。
- **Docling**（IBM，arXiv:2501.17887）：MIT 许可，复杂表格 **97.9%** 准确；CPU 3.1s/页，M3 Max 1.27s/页，L4 GPU 0.49s/页。DocLayNet 布局 + TableFormer。
- **Unstructured.io**：企业最流行（Fortune 500 三分之一用），简单表格 100%、复杂 75%。
- **LlamaParse**：商业 API，~6 秒/文档恒定；金融 / 法律文档强。
- **Mathpix**：中文场景 SOTA（OmniDocBench 中文第一）；GPT-4o VLM 仍落后于专用 pipeline。
- **NVIDIA Nemotron / Ferrules / GOT-OCR 2.0**：2026 新生。

### 4.2 本系统现状

25 个 parser：`app/parsing/parsers/{deepdoc,mineru,marker,magic_pdf,docling,textin,olmocr,deepseek_ocr,paddle_vl,qianfan_ocr,glm_ocr,tcadp,markitdown,pandoc,etl4llm,pdf,docx,excel,pptx,html,email,image,csv,json,text}_parser.py`；自研 `app/deepdoc/vision/{layout_recognizer,table_structure_recognizer,ocr}.py`；`app/parsing/quality/{document_quality,text_quality,ocr_validator,reading_order,benchmark,competition}.py`。

### 4.3 量化 Gap

- **未基准化**：25 个 parser 没有统一跑 OmniDocBench 报分，**无法证明自研 DeepDoc 比社区 MinerU/Docling 好**
- **模型版本可能老**：若 `deepdoc/` 基于 RAGFlow v0.x，未跟进 MinerU 2.5 移除 AGPLv3、支持 PPTX/XLSX 的更新
- **中文 SOTA**：未见 Mathpix 适配；中文长尾文档可能落后
- **质量 fallback 未闭合**：`quality/` 有评分但未见"低分触发第二后端"的仲裁

### 4.4 建议

- **P0** 建立内部解析 benchmark：用 OmniDocBench 子集 + 500 份企业真实文档 `plans/scripts/parse_bench.py`，跑 MinerU 2.5 / Docling / DeepDoc 三家，出 accuracy × latency × cost 表
- **P0** 升级 MinerU parser 到 2.5 版本（可商用、OmniDocBench 86.2 分、支持 PPTX/XLSX）
- **P1** 质量 fallback 闭环：`routing.py` 增加"分数<阈值→切第二后端→择优"
- **P1** 新增 Mathpix parser（中文文档）
- **P2** 新增 `colpali_parser.py`（见第 16 章，多模态 RAG）

---

## 5. 切块策略

### 5.1 业界前沿（有反直觉发现）

- **Vectara NAACL 2025**（arXiv:2410.13070）：**25 切块配置 × 48 embedding 模型**实证——切块配置对质量的影响**等于或大于** embedding 选择本身；反直觉结论：真实文档集合上 **fixed-size 稳定优于 semantic chunking**（retrieval / evidence / answer 三层都是）。
- **Chroma "Context Rot"**（Jul 2025）：18 个主流 LLM 在长 context 下召回下降；2026 年 1 月后续识别 **Context Cliff ≈ 2500 tokens**。
- **Fragment size 陷阱**：Chroma 语义切块 91.9% 检索 recall，但 FloTorch 端到端仅 54%（45 tokens 太小）→ **必须设 minimum chunk size floor**。
- **默认推荐**：256–512 tokens、10–25% overlap（Microsoft Azure 推 512 + 25% = 128 overlap）。
- **Anthropic Contextual Retrieval**（2024-09）：每 chunk 前加 50–100 token 文档上下文，召回 **+35%**。
- **Jina Late Chunking**（2024）：整文档 embed 后 pool 分段，避免边界损失。
- **RAPTOR**（ICLR 2024）：递归聚类+摘要产生层级索引。

### 5.2 本系统现状

**70+ 策略**（`app/rag/chunking/strategies/`）：通用（token/recursive/semantic/sentence_window/proposition/parent_child/markdown_hierarchy/pdf_layout/paper）+ 垂类（docker_compose/ansible/github_actions/gitlab_ci/jira_ticket/git_commit_log/subtitles/stacktrace/latex_sections/postmortem/prd_spec/sop_steps/policy_manual/meeting_minutes/resume 等），`contextual_enrichment.py` 已 Anthropic 风格，`chunking/quality_scorer.py` + `services/chunk_quality_gate.py`。

### 5.3 量化 Gap

- **Vectara 反直觉结论未验证**：我方 70+ 策略丰富，但没有内部基准证明这些策略比 512+128-overlap fixed-size 好多少
- **RAPTOR 完整闭环缺**：有 hierarchical，但未见"聚类→LLM 摘要→父节点重新进索引→查询多层匹配"
- **Late Chunking 未落**：当前都是先切再嵌
- **Contextual Enrichment 成本未优化**：全量入库都跑 LLM，缺"惰性增量"策略
- **Minimum chunk size floor 是否默认**：语义切块实现中是否强制最小长度？

### 5.4 建议

- **P0** 内部切块基准：选 3 数据集（中英企业 / 法律 / 技术手册），跑 fixed-size 512/128 + semantic + contextual + RAPTOR 四组，出 recall / end-to-end accuracy / cost 对比
- **P0** 实现 **Minimum chunk size floor**：`semantic.py` 强制 256 tokens 下限
- **P1** 新增 `strategies/raptor.py`：完整 RAPTOR；metadata 加层号
- **P1** Contextual Enrichment 惰性增量：仅对 `evidence_gap` 报警的 chunk 补上下文（而非全量）
- **P2** `strategies/late_chunking_jina.py`：Jina v3 long-context + boundary pooling

---

## 6. 预处理与数据治理

### 6.1 业界前沿

- **Data-centric RAG**（来自 Comprehensive Survey 2024）：prepare-then-rewrite-then-retrieve-then-read 范式；metadata、合成 QA、Meta Knowledge Summaries
- **Presidio**（Microsoft）：结构化 PII
- **KenLM perplexity 过滤**（C4 / RefinedWeb 配方）
- **trafilatura / jusText**：网页正文抽取
- **SimHash / MinHash LSH**：语料去重

### 6.2 本系统现状

`app/rag/preprocessing/` 27 文件覆盖 boilerplate / cleaning / html_canonical / language / near_dedup / normalization / pii_anonymizer / quality_filters / secrets / segmentation / simhash / stopwords / tables / tokenization / urls；`app/services/dataset_precheck_*`（6 个：near_dup_summary / risk_buckets / ingestion_suggestion / diff / scan_runner / service）；`app/services/dataset_profile_*`。

### 6.3 量化 Gap

- **KenLM perplexity 过滤缺**：无"低信息度过滤"
- **Data-centric 合成 QA / Meta Knowledge 缺**：入库时未生成"文档摘要 + 假设问题"作为 side-index
- **Presidio 深度集成缺**：`pii_anonymizer` 规则为主，未用 Microsoft Presidio analyzer + LLM 兜底
- **语言→模型路由缺**：`language.py` 标签未驱动 embedding provider / LLM 选择

### 6.4 建议

- **P1** Data-centric 入库增强：`preprocessing/synthetic_qa.py`，为每文档生成 3–5 条假设问题 + 1 条摘要，作为独立 side-index（contextual retrieval 的增强变体）
- **P1** 接入 Presidio：`preprocessing/pii_presidio.py`，抽样跑
- **P2** KenLM / small-LM perplexity 过滤：低质进隔离区
- **P2** 语言感知路由：`embedding/factory.py` 根据 `language.py` 标签选 provider

---

## 7. Query 理解与路由

### 7.1 业界前沿

- **Adaptive-RAG**（NAACL 2024）：query complexity classifier → no-retrieval / single-hop / multi-hop 分流
- **Self-Route**（EMNLP 2024）：让 LLM 自省选 long-context or RAG，**accuracy↑ + cost↓**
- **Step-Back Prompting**（2023）：抽象化查询再检索
- **HyDE**（2022）：伪答案 embed
- **Multi-Query / RAG-Fusion**：多查询 + RRF
- **Clarification Agent**：主动反问
- **IRCoT / Decomposition**：复杂问题分解

### 7.2 本系统现状

`app/rag/policy/{intent_router,intent_router_model,modality_router,must_recall,must_recall_auto,recall_obligation,query_expansion,clause_refs}.py`；`app/rag/retrieval/decomposition_chain.py`；`app/rag/core/query_rewrite_strategy.py`；`app/rag/query_expansion.py`；`app/rag/workflows/routing.py`；`app/rag/reranker/ltr.py:57,177` 含 `role_hyde` 角色（HyDE 通道存在）。

### 7.3 量化 Gap

- **Adaptive-RAG 完整路由缺**：`intent_router` 存在但未见"complexity → no-retrieval / single-hop / multi-hop"的明确分流；当前几乎所有查询都走完整 orchestrator
- **Self-Route 缺**：长/短 context 路由未交给 LLM 自决
- **Step-Back Prompting** 未独立通道
- **Clarification agent**：confidence 低时不主动澄清

### 7.4 建议

- **P0** `policy/complexity_classifier.py`：小模型或规则判定 simple / single-hop / multi-hop → 分别跳过检索 / 单通道 / 完整 orchestrator；**预计简单查询省 70% token**
- **P1** `workflows/step_back.py`：抽象化问题与原问题双通道召回，结果合并
- **P1** `workflows/self_route.py`：LLM 自决 RAG vs long-context
- **P2** Clarification agent：confidence < 0.6 返回结构化反问

---

# 第三部分　检索与重排线

## 8. 混合检索与融合

### 8.1 业界前沿

- **BGE-M3**（arXiv:2402.03216）：同模型产 dense + sparse + multi-vector；省一次 embedding 调用
- **LinearRAG**（ICLR 2026，GraphRAG-Bench 同期）：线性复杂度 graph retrieval
- **Learned RRF / LTR fusion**：不是常数 k，而是数据驱动
- **Sparse retrieval**：SPLADE++、unicoil
- **Late interaction**：ColBERT v2 + PLAID 压缩

### 8.2 本系统现状

`app/rag/retriever.py:85 HybridRetriever`（5940 行）= 向量 + BM25 + SPLADE + ColBERT ANN；`app/rag/retrieval/orchestrator.py:1264 run_retrieval`（5188 行）多通道编排；`retrievers/multi_vector.py`（summary/HyDE/parent）；`retrieval/colbert_ann.py`；`retrieval/sparse.py` + `sparse_prometheus_metrics.py`。

### 8.3 量化 Gap

- **BGE-M3 一体化未用**：当前 dense / sparse / colbert 是独立管线，没复用 BGE-M3 单模型三输出
- **RRF 权重是常数**：未 per-tenant learned
- **LinearRAG 类方案**（ICLR 2026）未跟进

### 8.4 建议

- **P0** BGE-M3 一体化索引：`embedding/bge_m3_triplet.py`，同 passage 一次产 dense + sparse + colbert；预计 embedding 阶段 **时延 ↓40–50%**
- **P1** Learned RRF：基于 feedback + ragas 的 per-tenant 权重微调
- **P2** 跟进 LinearRAG（ICLR'26 代码一般 4–5 月放出）

---

## 9. 重排层

### 9.1 业界前沿

- **BGE Reranker v2** 系列：v2-m3 / v2-gemma / v2-minicpm（长文本）
- **RankGPT / RankZephyr / RankLLaMA**：listwise LLM reranker
- **Cohere Rerank v3 / Voyage Rerank-2**：商业 API 顶级
- **MMR**：多样性
- **Calibration**：Platt / isotonic 校准

### 9.2 本系统现状

9 个 reranker：`app/rag/reranker/{cross_encoder,colbert,llm_based,ltr,kg,parent_child,dashscope,openai,hybrid}.py`；LTR v3 feature spec（`ltr.py:90`）含 fusion/field-aware。

### 9.3 量化 Gap

- **Listwise 模式**：`llm_based.py` 是 pointwise 还是 listwise？未确认
- **MMR 独立**：未见 `mmr.py` diversity reranker
- **BGE v2 专用**：有 cross_encoder，未见 bge_v2 适配（不同长度预算）
- **Rerank 分数 calibration**：LTR 输出是否是校准概率未确认

### 9.4 建议

- **P0** 确认 `llm_based.py` 实现：若非 listwise 则新增 RankGPT listwise 变体（一次性看全部候选）
- **P0** 新增 `reranker/mmr.py`：MMR diversity；λ 可配（当前 top-k 可能挤占相似答案）
- **P1** `reranker/bge_v2.py`：BGE v2 专用（m3/gemma/minicpm 三变体）
- **P2** Calibration：Platt / isotonic（用历史 ground-truth）

---

## 10. Long-Context vs RAG

### 10.1 业界前沿（量化）

- **Gemini 1.5 Pro needle-in-haystack 99.7%**，但**多事实检索平均 60% recall**（40% miss 是系统静默失败）
- **Long-context 延迟 30–60× / 成本 1250×**（vs RAG pipeline）
- **欧洲银行案例 Q3 2025**：简单查询 long-context +34%，跨时期合成 RAG +67%、延迟 1/8、成本 1/16
- **Chroma Context Rot**（Jul 2025）：18 个模型长 context 下质量下降
- **Context Cliff ≈ 2500 tokens** 质量陡降
- **Self-Route**（EMNLP 2024）：路由架构收益显著
- **规模下限**：10M token ≈ 40MB ≈ ~70 份 10-K 报告；企业 TB 级语料必须 RAG
- **市场**：Pinecone 2025 Q4 收入 YoY **+340%**，Weaviate C 轮 $163M，MongoDB Atlas Vector Search 增速第一——RAG 远未过时

### 10.2 本系统现状

- `app/rag/core/retrieval_profiles.py` 检索画像
- `app/rag/core/context_compression.py`、`context_denoise.py` —— context 压缩
- 未见显式 long-context 管线和 Self-Route 风格路由

### 10.3 量化 Gap

- **无 "long_context" profile**：当前 chunk_size 默认 RAG 1.0 时代参数，未提供"大 chunk 4096 + top_k 8 + long-context LLM"的替代
- **Self-Route 缺**：没有 LLM 自决 RAG vs long-context 的路由
- **Context Cliff 监测**：未对"context > 2500"触发质量降级告警

### 10.4 建议

- **P0** 加 long_context profile：`retrieval_profiles.py` 预置"chunk=4096 / top_k=8 / rerank=4"
- **P1** `workflows/self_route.py`：LLM 自决；metrics 记路由决策分布
- **P2** Context Cliff 守护：context 总 tokens > 2500 时自动触发 `context_compression`

---

# 第四部分　Agentic 与推理线

## 11. Agentic RAG

### 11.1 业界前沿

- **Agentic RAG Survey**（arXiv:2501.09136）四 pattern：reflection / planning / tool use / multi-agent
- **SoK Agentic RAG**（arXiv:2603.07379）：POMDP 形式化；风险清单：cascading tool vulnerability / memory poisoning / compounding hallucination / retrieval misalignment
- **A-RAG**（arXiv:2602.03442, Feb 2026）：**向 agent 暴露 3 种检索工具（keyword / semantic / chunk-read）**，性能提升且 token 更省
- **Interact-RAG**：LLM 主动操纵检索过程（active manipulator）
- **RAG-Critic**（ACL 2025）：自动批评家引导
- **Self-Reasoning RAG**（AAAI 2025）
- **RAGCap-Bench**：中间任务能力细粒度评测

### 11.2 本系统现状

`app/rag/workflows/{react,planner_worker,evaluator_optimizer,parallelization,routing}.py`（5 种 workflow）；`app/rag/agents/{rag_agent,multi_agent,prebuilt}.py`；`app/rag/tools/{mcp_client,mcp_tools,simple_kb_search}.py`；`app/rag/memory/{short_term,long_term}.py`（765+552 行）；`app/rag/checkpointer/{memory,sqlite,time_travel}.py` —— LangGraph checkpointer 完整。

### 11.3 量化 Gap

- **A-RAG hierarchical tools 未暴露**：agent 只有 `simple_kb_search` 单 tool，没有 keyword / semantic / chunk-read 三粒度接口
- **Interact-RAG 主动操纵**：agent 无法调整检索参数（top_k / threshold）
- **RAG-Critic 批评家**：有 `evaluator_optimizer` 但未见独立 critic agent
- **SoK 风险防御**：cascading tool vuln / memory poisoning 未见专项测试

### 11.4 建议

- **P0** **`tools/hierarchical_retrieval_tools.py`**：暴露 `keyword_search` / `semantic_search` / `chunk_read` 三 tool 给 agent，对齐 A-RAG（arXiv:2602.03442）
- **P1** Agent 可调参：`tools/retrieval_config_tool.py` 让 agent 按需调 top_k、rerank_n
- **P1** `workflows/critic.py`：独立 critic agent（RAG-Critic）
- **P2** Memory poisoning 红队测试：`evaluation/agent_redteam.py`

---

## 12. Self-RAG / CRAG / FLARE

### 12.1 业界前沿

- **Self-RAG**（NeurIPS 2023）：reflect tokens `[Retrieve]` `[IsRel]` `[IsSup]` `[IsUse]`
- **CRAG**（2024）：retrieval evaluator → correct / ambiguous / incorrect；incorrect 触发 **web search fallback**
- **FLARE**（EMNLP 2023）：生成过程 token 置信度低时主动再检索
- **Self-Reasoning RAG**（AAAI 2025）

### 12.2 本系统现状

`app/rag/evaluation/evidence_retrieve_gate.py` 检索门控；`app/rag/retrieval/evidence_gap.py` 证据缺口；`app/rag/policy/must_recall*.py` 检索义务；`app/rag/workflows/evaluator_optimizer.py` 评估器-优化器；**无 web search tool**。

### 12.3 量化 Gap

- **CRAG 未接入 streaming 主路径**：`evidence_gap` 有检测，但 incorrect → web search 分支未闭合
- **无 web search tool**：`tools/` 缺 Serper / Tavily / Brave / Exa
- **Self-RAG reflect tokens 完整形态缺**：无生成-解析-再检索闭环
- **FLARE token-level confidence 主动检索** 缺

### 12.4 建议

- **P0** **`tools/web_search.py`**：Serper + Tavily fallback，接入 streaming；**CRAG 闭环**
- **P0** `workflows/crag_streaming.py`：retrieval evaluator → correct/ambig/incorrect；incorrect 走 web search
- **P1** `workflows/self_rag.py`：prompt-based reflect tokens 先跑，后续微调专用模型
- **P2** `workflows/flare.py`：token confidence → 主动再检索

---

## 13. Reasoning RAG

### 13.1 业界前沿

- **Reasoning RAG Survey**（arXiv:2506.10408）：System 1（predefined）vs System 2（agentic）
- **TreePS-RAG**（2026）：tree-based process supervision
- **EviOmni**（2026）：RL 学习抽取 rational evidence
- **RAGShaper**（2026）：auto data synthesis 诱导 agentic skills

### 13.2 本系统现状

`app/rag/workflows/planner_worker.py`（362 行）—— planning pattern；`app/rag/evaluation/hard_negative_mining.py`；`regression_sample_builder.py`；`test_generator.py` —— 合成能力齐。

### 13.3 量化 Gap

- **RL 训练检索策略** 未见（EviOmni 思路）
- **Process supervision** 未见树型
- **RAGShaper** 级 skill 合成未用于 fine-tune 内部模型

### 13.4 建议

- **P2** `evaluation/ragshaper_synthesizer.py`：按 RAGShaper 思路合成 agentic 训练数据
- **P3** RL 检索策略（EviOmni）：投入大，观察开源代码放出后再跟进
- **P3** TreePS 树型 process supervision：研究型项目，暂缓

---

# 第五部分　KG 与结构化

## 14. GraphRAG 家族对比（含 ICLR'26 基准）

### 14.1 业界量化对比（来自 arXiv:2506.05690v3 GraphRAG-Bench）

| 方法 | 典型指标 | 成本 / 延迟 | 适用场景 |
|---|---|---|---|
| **Microsoft GraphRAG** | 企业基准 **86% vs baseline 32%**；大数据集索引 **$33K** | 高 | 深度关系推理、合规 QA |
| **LazyGraphRAG** | GraphRAG 变体，延迟降 | 中 | 折中 |
| **LightRAG** | 省 **6000× token**（$0.15 vs $4–7/doc）、延迟 **-30%**（80ms vs 120ms） | 低 | 成本敏感、动态 KB |
| **HippoRAG / HippoRAG2** | L2-L3 Evidence Recall **87.9–90.9%** / Context Relevance **85.8–87.8%** | 比 GraphRAG 便宜 **10–30×** | 多跳推理、长时记忆 |
| **PathRAG** | context 砍 **44%**，准确稳定 | 中 | pruning 敏感 |
| **OG-RAG** | 减幻觉 **40%**（ontology-grounded） | 中 | 结构化领域 |
| **Vanilla RAG** | 简单事实 Evidence Recall **83.2%**（L1 最佳） | 低 | 简单 QA |
| **LinearRAG**（ICLR'26） | 线性复杂度 | 低 | 新生，观察 |

**关键结论（GraphRAG-Bench）**：**没有单一方法通吃**，最优架构**依查询复杂度而定**。简单事实 vanilla RAG 胜；多跳 / 综合摘要 HippoRAG2 胜；深度关系 GraphRAG 胜。

### 14.2 本系统现状

完整 KG 管线（`app/rag/kg/`）：
- `extraction/{extractor,hybrid_extractor,gliner_extractor,alias,entity_verifier,relation_processor,relation_verifier,skill_processor}.py`
- `loading/processor.py`
- `search/{recall,expand,graph_embeddings,ranking,query_mode,searcher,cache,tracker,relation_scoring}.py`
- `quality/{kg_completeness_scorer,kg_denoiser}.py`
- `community.py`（**LLM community reports 已实现**，对齐 Microsoft GraphRAG）
- `provenance.py`、`ontology.py`、`snapshot.py`、`pipeline.py`

### 14.3 量化 Gap

- **成本未量化**：我方 community 抽取对大数据集的 token 成本 vs LightRAG 的 6000× 节省，未测
- **无 DRIFT search**：GraphRAG 的 query→community match→local expand 未显式实现
- **无 PPR 召回（HippoRAG 核心）**：`graph_embeddings.py` 有图嵌入但未见 Personalized PageRank
- **Temporal KG 弱**：`snapshot.py` 有快照但时间敏感查询路由未见
- **Query 复杂度 → KG 方法选择**：当前走固定管线，未按复杂度选 vanilla / light / hippo / graphrag

### 14.4 建议

- **P0** 内部 GraphRAG-Bench 小跑：`evaluation/graphrag_bench.py`，在 2 个真实语料跑 vanilla / 我方 KG / LightRAG 三家，出 Recall × Cost 图
- **P0** `kg/search/pprank.py`：Personalized PageRank 召回（HippoRAG 核心，10–30× 成本优势）
- **P1** `kg/search/drift_search.py`：community 摘要匹配 → 内部展开
- **P1** Query 复杂度 → KG 方法路由
- **P2** Temporal KG：time-aware snapshot 自动选
- **P3** 评估是否引入 LightRAG 双层检索（作为 KG 的轻量 fallback）

---

## 15. GraphRAG-Bench 实证要点

| Level | 场景 | 最强方法 | 关键数字 |
|---|---|---|---|
| L1 | 单事实 / 简单 QA | **Vanilla RAG** | Evidence Recall 83.2% |
| L2 | 多跳推理 | **HippoRAG** | Evidence Recall 87.9–90.9% |
| L3 | 跨段深度关系 | **Microsoft GraphRAG** | 企业 86% vs 32% |
| 摘要 | 查询式摘要 | **RAG + HippoRAG2**（原文更贴 GT） | — |

**工程结论**：自建 KG 栈的价值在 L2/L3 得到印证；但 L1 场景应该**回退到 vanilla RAG 以省成本**。这需要在 intent_router 层决策。

---

# 第六部分　多模态与新形态

## 16. Multimodal RAG

### 16.1 业界前沿

- **ColPali**（ICLR 2025）：**跳过 OCR**，直接 patch-level 向量 + late interaction；注意代价：**向量数膨胀 100×**（10M → 1B），vector DB 规模挑战 + LLM 消费图像问题
- **ColQwen**：ColPali + Qwen2-VL 变体
- **Voice-Vision RAG**（AI Engineer World's Fair 2025）：voice + vision 端到端
- **VideoRAG 系列**：
  - *VideoRAG: Retrieval-Augmented Generation over Video Corpus*
  - *VideoRAG with Extreme Long-Context Videos*
  - *Video-RAG: Visually-aligned Retrieval-Augmented Long Video Comprehension*
  - *DrVideo: Document Retrieval Based Long Video Understanding*
- **CommunityKG-RAG**：zero-shot KG social 结构
- **Multimodal RAG Survey**（llm-lab-org, Feb→Jun 2025）

### 16.2 本系统现状

`app/rag/embedding/clip_embedder.py`、`app/rag/core/vision_reader.py`、`app/parsing/enrich/vlm_image_caption.py`。**无视频 / 音频 parser**。

### 16.3 量化 Gap

- **ColPali / ColQwen 未接入**：当前仍走 OCR→文本→embed 路径，丢失视觉排版/表格/图表信息
- **视频 RAG 缺**：无 `video_parser.py`、无关键帧抽取、无 ASR
- **音频 RAG 缺**：无 Whisper + diarization + alignment
- **多模态 query**：用户上传图片作为查询未见完整链路
- **向量 DB 应对 ColPali 100× 膨胀**：Milvus 支持但参数需调；PLAID 压缩未见

### 16.4 建议

- **P0** `parsers/colpali_parser.py`：patch 级向量入独立子集合，检索时与文本通道融合（参考 HuggingFace cookbook + Milvus ColPali 博文）
- **P0** `parsers/video_parser.py`：ffmpeg 分段 + Whisper + 关键帧（CLIP）；chunk = {text_from_ASR, vision_embedding, timestamp}
- **P1** `parsers/audio_parser.py`：Whisper + diarization（pyannote）+ timestamp
- **P1** API 加 `query_image` 字段，retriever 路由到 CLIP / ColPali 子集合
- **P2** PLAID 压缩 ColPali 向量存储

---

## 17. 结构化数据 / NL2SQL

### 17.1 业界前沿

- **TaPas / TAPEX**：表格理解
- **NL2SQL** 新版：Vanna / DIN-SQL / C3-SQL / DAIL-SQL
- **Chart-to-Table / DePlot**：图表→结构化数据点

### 17.2 本系统现状

`app/rag/chunking/strategies/{csv_rows,markdown_table,spreadsheet_sheet,sql_schema}.py`；`app/parsing/enrich/table_markdown.py`；`app/api/v1/dataset_tables.py`、`app/api/v1/db_catalog.py`、`app/connectors/db/{catalog_connectors,catalog_runner,introspection,profile_privacy}.py`（**catalog 能力齐**）。

### 17.3 量化 Gap

- **NL2SQL 链路缺**：有 catalog 能力但未见"用户问题→生成 SQL→执行→结果摘要"工具
- **Chart-to-Data 缺**：图表只有 caption，无数据点抽取

### 17.4 建议

- **P1** `tools/nl2sql.py`：结合 `db_catalog` 做 text-to-SQL（DAIL-SQL 风格 + schema linking）
- **P2** `enrich/chart_to_data.py`：DePlot / UniChart；产物作独立 chunk type

---

# 第七部分　工程与企业线

## 18. Embedding 与向量栈

### 18.1 业界前沿

- **BGE-M3**：中英多语 + 多粒度 + 三态
- **Voyage-3 / Voyage-code-3**：商业 SOTA，代码向量强
- **Cohere Embed v3**：quantization-aware
- **Jina v3**：long context + Matryoshka
- **Matryoshka Representation Learning**（NeurIPS 2022）：同向量支持 128/256/512/1024 维
- **ColBERT v2 / PLAID**：late interaction + 压缩
- **Vector DB**：Milvus、Qdrant（轻便）、Weaviate（多模态）、Vespa（超大规模 + streaming ACL）、Pinecone Serverless

### 18.2 本系统现状

`app/rag/embedding/providers/` 仅 **4 个**（dashscope / local / ollama / openai），默认 BGE-M3；`app/storage/vector/milvus.py` 唯一实现；`factory.py` 抽象存在。

### 18.3 量化 Gap

- **Provider 不足**：缺 Voyage / Cohere / Jina / Bedrock / Azure
- **Matryoshka 未用**：BGE-M3 有但未切片
- **代码向量无专用通道**：Voyage-code-3 未用
- **向量 DB 单一**：缺 Qdrant / PGVector 等轻量替代；企业选型受限

### 18.4 建议

- **P0** `embedding/providers/{voyage,cohere,jina,bedrock}.py`：扩容商业级
- **P0** `storage/vector/{qdrant,pgvector}.py` + factory 路由；Milvus 仍默认
- **P1** `embedding/matryoshka.py`：复杂查询用 1024 维，简单用 256 维（预计时延 ↓30%）
- **P1** `embedding/code_embedder.py`：Voyage-code-3 或 CodeBERT 专用通道
- **P2** PLAID ColBERT 压缩

---

## 19. 评测与 Observability

### 19.1 业界前沿（含重要坑）

- **基准**：RAGBench / CRAG / LegalBench-RAG / WixQA / T²-RAGBench
- **关键研究发现（2025–2026）**：**5 个主流评测工具（WandB / TruLens / RAGAS / Phoenix / DeepEval）在 1460 问 / 14600 打分下都无法区分"实体对但事实错"的 hard negative vs "正确上下文"** —— RAG 可以拿 0.95 faithfulness 但给错业务答案
- **量化**：WandB Top-1 **94.5%**（最高 accuracy）；TruLens NDCG@5 **0.932** / Spearman ρ **0.750** / MRR **0.594**（最高）；WandB 用二元分粗糙，TruLens 4 分更细
- **Phoenix**：原生 OpenTelemetry、交互式 trace、集成 prompt management UI
- **Online shadow eval**：生产流量 sample → 离线对比
- **Langfuse**：OSS、多租户、cost tracking 强

### 19.2 本系统现状

`app/rag/evaluation/ragas.py`（1753 行）+ 13 个评测模块；`app/rag/tracing/langsmith.py`；`app/rag/trace_schema.py`（145 行自研）；`app/rag/metrics_sli.py`（102 行）；Milvus / authz / connector ACL / sparse Prometheus metrics 齐。

### 19.3 量化 Gap

- **"事实错 vs 事实对"盲点**：我方 ragas 也有同样限制，未见主动针对 hard negative 的对抗测试
- **Online shadow eval 缺**：有 replay_capture 但未形成"生产双跑 + 离线 diff"闭环
- **A/B 实验框架**：缺 tenant/user hash 切流 + 统计显著性
- **单一 tracing**：仅 LangSmith，缺 Phoenix 交互式 / Langfuse OSS 多租户备份
- **Cost breakdown 缺**：token / provider / model / tenant 归因未聚合

### 19.4 建议

- **P0** `evaluation/hard_negative_stress.py`：专门对抗 hard negative（实体对但事实错），定期 regression
- **P0** `core/cost_tracker.py`：统一打点 provider / model / tokens / cost / tenant，落 Prometheus + DB
- **P1** `evaluation/online_shadow.py`：sample 生产流量，离线双跑 diff
- **P1** 接入 **Phoenix** 作为 LangSmith 的互补（交互式 span trace + prompt management）
- **P2** 接入 **Langfuse**（OSS + 多租户 cost tracking）
- **P2** `evaluation/ab_experiment.py`：tenant hash 切流 + 统计显著性

---

## 20. 企业级

### 20.1 业界前沿

- **连接器生态**：LlamaHub **160+ loaders**；Unstructured Serverless、Airbyte、Fivetran
- **Haystack 监管路线**：欧盟委员会、英国经济学人、牛津出版社、德国联邦国防军
- **Vespa streaming mode**：group_id ACL 过滤
- **LangGraph**：agentic workflow de facto
- **DSPy / Pathway / LangChain**：programmatic opt / real-time / orchestration

### 20.2 本系统现状

`app/connectors/base.py:11` ABC 存在；`app/connectors/db/` **只有 DB catalog** 实现（catalog_connectors / runner / introspection / profile_privacy）；`app/api/v1/{scim,rbac,groups,governance,observability,retrieval_explain,retrieval_profiles,rag_config_templates,retrieval_config_hash,audit}.py`；`app/services/connector_{registry,reconcile_service,sync_state,source_acl_mapping,acl_prometheus_metrics}.py`；`app/services/audit_log_{retention,service}.py`；`app/services/access_graph_diff_service.py`。

### 20.3 量化 Gap

- **连接器生态空心**：框架齐（ABC + registry + sync_state + ACL mapping）但**只有 DB 一种实现**；对比 LlamaHub 160+ 实现差距巨大；SharePoint / Confluence / Notion / Slack / GitHub / GDrive / S3 / OneDrive / Dropbox / Web / Mail 全缺
- **Chunk-level ACL**：有 `connector_source_acl_mapping`，但向量 DB query 时是否强过滤 partition 未全部验证
- **Lineage 端到端**：有 `provenance` 但未见 doc→chunk→embedding→retrieval→answer→citation 全链 API
- **RTBF 级联**：有 audit_log_retention，用户级跨 vector/KG/cache/object 级联撤销是否自动未确认
- **多区域**：`core/config.py` 无 region / data residency 配置

### 20.4 建议

- **P0** 连接器前 5：SharePoint / Confluence / Notion / GitHub / S3（按企业画像排序）；每个模板 ~400 行 + 测试
- **P0** Chunk-level ACL 端到端审查：`retriever.py` 强制注入 tenant / group filter + 写"ACL escape"红队测试
- **P1** `services/lineage_service.py` + `/api/v1/lineage`：chunk_id ↔ doc_id ↔ connector_source ↔ user_acl ↔ retrieval_run ↔ citation 全链查询
- **P1** `services/rtbf_cascade.py`：跨 vector / KG / cache / object storage 级联删除工作流 + 审计
- **P2** 多区域 PoC：`core/config.py` `DATA_REGION`，storage/provider 按 region 路由

---

# 第八部分　总览

## 21. 优先级矩阵（Impact × Effort，引论文 ID）

### Quick Wins（高 Impact / 低 Effort / 1–3 周）

| 项 | 论文 / 基准锚点 | 对标 gap 章节 |
|---|---|---|
| CRAG 接入 streaming + Web search tool | CRAG (Yan 2024) | §12 |
| Output guard 扩容 + Presidio + Llama Guard 3 | Meta Prompt Guard-86M | §(上版 §13) |
| Semantic cache | GPTCache | §(上版 §12) |
| BGE-M3 三态一体化 | arXiv:2402.03216 | §8 |
| MMR diversity reranker | 经典 | §9 |
| Adaptive-RAG 复杂度路由 | Jeong NAACL 2024 | §7 |
| Minimum chunk size floor | Chroma / FloTorch | §5 |
| A-RAG hierarchical tools | arXiv:2602.03442 | §11 |
| Per-trace cost tracker | OpenLLMetry | §19 |
| Long-context profile | Self-Route EMNLP 2024 | §10 |
| Contextual Enrichment 惰性增量 | Anthropic 2024 | §5 |

### 战略投入（高 Impact / 高 Effort / 1–3 月）

| 项 | 论文 / 基准锚点 | 对标 gap 章节 |
|---|---|---|
| 连接器生态前 5 | LlamaHub | §20 |
| 多模态 RAG（视频+音频+ColPali） | arXiv:2407.01449 ColPali + VideoRAG 系列 | §16 |
| 向量 DB 多后端（Qdrant + PGVector） | — | §18 |
| RAPTOR 完整 | Sarthi ICLR 2024 | §5 |
| Self-RAG workflow | Asai NeurIPS 2023 | §12 |
| HippoRAG PPR 召回 | Gutiérrez NeurIPS 2024 | §14 |
| Chunk-level ACL 闭环 + 红队 | Vespa 实践 | §20 |
| Online shadow eval infra | 业界最佳实践 | §19 |
| MinerU 2.5 升级 + 内部 OmniDocBench | CVPR 2025 | §4 |
| Internal GraphRAG-Bench 小跑 | ICLR 2026 | §14 |

### 补强（中 Impact / 低 Effort / 并行）

| 项 | 锚点 | 章节 |
|---|---|---|
| Embedding provider 扩容（Voyage/Cohere/Jina） | — | §18 |
| Listwise LLM rerank（RankGPT 确认） | RankGPT / RankZephyr | §9 |
| BGE Reranker v2 专用 | — | §9 |
| Late Chunking | Jina 2024 | §5 |
| Step-Back Prompting 独立通道 | — | §7 |
| Data-centric 合成 QA | Comprehensive Survey 2024 | §6 |
| Presidio 集成 | Microsoft | §6 |
| Phoenix / Langfuse 接入 | — | §19 |
| Hard negative stress | 2025 研究 | §19 |

### 延后 / 观望

- RA-DIT 联合微调（Meta 2023）：ROI 不足
- 自建 vLLM 分布式集群：看 LLM 成本曲线
- Tree-of-Thoughts 通用化：难通用
- LinearRAG（ICLR'26）：等代码放出
- TreePS-RAG / EviOmni RL：观察
- 多区域部署：合规驱动才做

---

## 22. 6–12 月路线图

### 2026 Q2（6 周，5–6 月）

**主线**：Quick Wins 全量 + 连接器 3 个 + 内部 benchmark 建设

- 第 1–2 周：
  - `core/cost_tracker.py` + Prometheus 落地
  - `reranker/mmr.py` + `tools/web_search.py`
  - Minimum chunk size floor + long_context profile
- 第 3–4 周：
  - `tools/hierarchical_retrieval_tools.py`（A-RAG）
  - `embedding/bge_m3_triplet.py`（三态一体化）
  - Output guard 扩容（Presidio + Llama Guard 3）
  - Semantic cache
- 第 5–6 周：
  - SharePoint / Confluence / Notion 连接器
  - `evaluation/parse_bench.py`（OmniDocBench 子集）
  - `evaluation/graphrag_bench.py`（ICLR'26 子集）
  - MinerU 2.5 升级

**里程碑**：Quick Wins 全清；拥有内部 OmniDocBench / GraphRAG-Bench 报分基线。

### 2026 Q3（12 周，7–9 月）

**主线**：多模态 RAG + 向量 DB 多后端 + Self-RAG / HippoRAG + Chunk-level ACL

- 月 1：
  - ColPali parser + Milvus 100× 向量应对
  - Qdrant 第二后端 + factory 路由
  - `embedding/voyage,cohere,jina.py`
- 月 2：
  - `video_parser.py` + `audio_parser.py`
  - `workflows/self_rag.py` + `crag_streaming.py`
  - `kg/search/pprank.py`（HippoRAG 核心）
- 月 3：
  - Chunk-level ACL 红队 + 修复
  - Online shadow eval
  - GitHub / S3 连接器

**里程碑**：多模态 RAG 可用；KG 层具备 HippoRAG 级性价比；ACL 通过红队。

### 2026 Q4（9 周，10–12 月）

**主线**：Reasoning RAG + 运营优化 + 合规

- 跟进 LinearRAG / RAGShaper 代码放出
- `evaluation/hard_negative_stress.py` 常态化
- RTBF 级联工作流
- Mathpix parser（中文）+ NL2SQL tool
- Matryoshka embedding 上线

**里程碑**：2026 Q1 业界前沿主要条目全部有对标实现或对抗测试覆盖。

---

## 23. 参考资料清单

### Survey

- A Comprehensive Survey of RAG (arXiv:2410.12837) — https://arxiv.org/abs/2410.12837
- Architectures, Enhancements, Robustness (arXiv:2506.00054) — https://arxiv.org/abs/2506.00054
- Agentic RAG Survey (arXiv:2501.09136) — https://arxiv.org/abs/2501.09136
- SoK Agentic RAG (arXiv:2603.07379) — https://arxiv.org/abs/2603.07379
- Reasoning RAG System 1/2 (arXiv:2506.10408) — https://arxiv.org/abs/2506.10408
- Multimodal RAG Survey — https://github.com/llm-lab-org/Multimodal-RAG-Survey
- RAG for LLMs (arXiv:2312.10997) — https://arxiv.org/abs/2312.10997

### 核心算法论文

- Self-RAG (Asai, NeurIPS 2023)
- CRAG (Yan 2024)
- RAPTOR (Sarthi, ICLR 2024) — https://arxiv.org/abs/2401.18059
- HippoRAG / HippoRAG2 (Gutiérrez, NeurIPS 2024)
- Adaptive-RAG (Jeong, NAACL 2024)
- LongRAG (Jiang 2024)
- FLARE (Jiang, EMNLP 2023)
- FILCO (Wang, NeurIPS 2023)
- Self-Route (EMNLP 2024)
- Step-Back Prompting (2023)
- HyDE (2022)
- Dense X Retrieval / Proposition (2023)
- A-RAG (arXiv:2602.03442) — https://arxiv.org/abs/2602.03442
- ColPali (arXiv:2407.01449) — https://arxiv.org/abs/2407.01449
- Matryoshka Representation Learning (NeurIPS 2022)
- BGE-M3 (arXiv:2402.03216)
- Anthropic Contextual Retrieval (2024-09)
- Jina Late Chunking (2024)
- RA-DIT (Meta 2023)
- RAG-Critic (ACL 2025)
- Self-Reasoning RAG (AAAI 2025)
- Interact-RAG / RAGShaper / EviOmni / TreePS-RAG / LinearRAG (2026)
- Vectara NAACL 2025 (arXiv:2410.13070) — https://arxiv.org/abs/2410.13070

### GraphRAG 家族

- Microsoft GraphRAG — https://github.com/microsoft/graphrag
- LightRAG — https://openreview.net/forum?id=bbVH40jy7f
- HippoRAG / HippoRAG2
- PathRAG / OG-RAG / CommunityKG-RAG
- GraphRAG-Bench (ICLR 2026) — https://github.com/GraphRAG-Bench/GraphRAG-Benchmark
- When to use Graphs in RAG (arXiv:2506.05690v3) — https://arxiv.org/html/2506.05690v3
- RAG vs GraphRAG Systematic Eval (arXiv:2502.11371) — https://arxiv.org/html/2502.11371v2
- Awesome-GraphRAG — https://github.com/DEEP-PolyU/Awesome-GraphRAG

### 文档解析

- OmniDocBench (CVPR 2025, arXiv:2412.07626) — https://arxiv.org/html/2412.07626v1
- MinerU — https://github.com/opendatalab/MinerU
- Docling (arXiv:2501.17887) — https://arxiv.org/html/2501.17887v1
- PDF-Extract-Kit — https://github.com/opendatalab/PDF-Extract-Kit
- 2025 Parse Benchmark — https://procycons.com/en/blogs/pdf-data-extraction-benchmark/

### 多模态

- Multimodal RAG with ColPali (HuggingFace Cookbook) — https://huggingface.co/learn/cookbook/en/multimodal_rag_using_document_retrieval_and_vlms
- ColPali + Milvus — https://huggingface.co/blog/saumitras/colpali-milvus-multimodal-rag
- VideoRAG / DrVideo（见 Multimodal RAG Survey 仓库）

### 评测工具

- RAGAS (arXiv:2309.15217) — https://arxiv.org/abs/2309.15217
- Awesome-RAG-Evaluation — https://github.com/YHPeter/Awesome-RAG-Evaluation
- RAG Eval Frameworks 2026 — https://atlan.com/know/llm-evaluation-frameworks-compared/
- TruLens / Phoenix / DeepEval / Langfuse / Portkey 官网

### 系统 / 平台

- LlamaIndex 0.12 / LangChain 0.3 / Haystack 2.x 官网
- RAGFlow — https://github.com/infiniflow/ragflow
- Dify、Cohere Coral、Vectara、Verba、Cognita、nano-graphrag、LlamaHub

### 前沿工程

- Anthropic Contextual Retrieval blog
- LlamaIndex Long-Context RAG blog
- Chroma Context Rot 研究（2025-07）
- LongRAG 实证对比（Gemini 1.5 Pro 99.7% / 60% benchmarks）
- 企业 RAG 2026 — https://www.techment.com/blogs/rag-in-2026/
- Atlan 企业对比 — https://atlan.com/know/enterprise-rag-platforms-comparison/

### 安全 / 合规

- Meta Llama Guard 3 / Prompt Guard-86M 模型卡
- Microsoft Presidio
- NeMo Guardrails
- Vespa streaming mode（chunk-level ACL 最佳实践）

---

> **核心结论**：
> 1. 我方解析（25 parser）/ 切块（70+ 策略）/ KG（完整管线含 LLM community）/ 评测（1753 行 RAGAS+ 13 模块）在**功能覆盖**上已接近或超过业界头部开源；
> 2. 最大短板在 **Agentic tool 粒度**（A-RAG）、**多模态 RAG**（ColPali/Video/Audio）、**连接器生态**（仅 DB）、**Output guard**（35 行薄）、**在线评测与成本治理**；
> 3. 具"功能—基准—成本"三角缺失：**没有把我方已实现的能力用业界 benchmark 量化**，导致投入难以向外证明价值；
> 4. 最关键的一次投入是：**先建内部 benchmark（OmniDocBench / GraphRAG-Bench / Hard-Negative stress）**，再按数据决定下一步迭代方向，而不是继续堆功能。

> **下一步**：Quick Wins 全部拆独立 plan 单独实施；战略项先出 RFC 再拆 plan；季度开始前更新本报告。

---

## 12. 2026-05-01 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口.

已落地:
- Quick Wins 中对产品闭环有直接价值的项已吸收到现有实现:Agentic retrieval、context expansion、rerank profiles、semantic cache、cost/quota、precheck scanner、POC attribution、KG diagnostics/snapshot/visualization、safety guardrails.
- 评测闭环已覆盖 ablation、evaluation API、bad case/feedback、POC attribution、redteam 和 KG diagnostics,可以支撑后续真实问题定位.
- 入库前到问答后的主要链路已连成产品路径:解析/预检/入库监控/隔离/反馈/评测/KG/RAG trace 均有前后端入口.

暂缓:
- 暂缓 OmniDocBench、GraphRAG-Bench、Hard-Negative stress 的全量 benchmark runner 常驻化;没有稳定真实样本池时榜单维护成本高于收益.
- 暂缓 ColPali、Video/Audio RAG、商业 parser/provider 矩阵和连接器生态扩张,这些属于新产品线级投入.

Directive: 本文作为季度研究归档;后续不要继续按大而全清单推进,只从真实客户缺口拆小任务.
