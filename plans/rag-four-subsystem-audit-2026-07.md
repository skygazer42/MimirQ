# MimirQ RAG 四大子系统审查报告（2026-07-10）

> 方法：4 路并行代码审计（解析切块 / 入库管线 / 治理安全 / 召回重排），逐项核对 2026-Q2 各调研 plan 中 P0 建议的落地状态，结合业界研究（截至 2026-05 的调研沉淀）输出增量建议。
> 背景：2026-05-01 以来 663 个提交，主线为 **Dify 外部检索插件化 + 常州政务垂直交付**（retrieval audit 证据链、plugin chunk readiness 门禁、QA anchor 保护）。
> 联网搜索本次不可用（WebSearch 限流 / 备用搜索套餐到期），业界引用基于 `plans/` 既有调研 + 模型知识（cutoff 2026-01）。

---

## 一、总体判断

**工程深度已在业界第一梯队。当前最大的问题不是"缺功能"，而是三件事：**

1. **安全侧存在"名不符实"的桩实现**（llama_guard / prompt_guard / pii_presidio 均为正则桩，非真模型/真库）；
2. **能力已堆到位但没有可跑的量化 harness 来证明**（parse_bench 空壳、chunking_grid 缺网格打分）；
3. **5 个巨型文件正在侵蚀可维护性**（integrations_dify 7616 / processor 6676 / ingestion page-client 6115 / quarantine page 3026 / retriever 9082）。

**重要修正**：2026-04/05 各 plan 中标记"缺失/待建"的 P0 能力**绝大多数已经落地**（CRAG/Self-RAG/FLARE、rerank-expand-rerank、KG agentic beam search、PPR、统计显著性全套、pre_poc_scanner、Context Cliff 监测、min chunk floor、parent-child 连坐、行业规则库前后端+检索链打通、RTBF 级联、LLM tagger、cost tracker 等）。**引用旧 plan 的"现状/缺口"结论前必须以本报告为准。**

| 子系统 | 规模 | 一句话评价 |
|---|---|---|
| 文档解析 | 30 parser 6364 行 + deepdoc vision 10161 行 + enrich 26 模块 | 覆盖面超过单家开源产品，MinerU(VLM)/Docling/MD+DOCX 双输出/三档 PDF 判定俱全 |
| 切块 | 79 策略 18118 行 | late chunking、parent-child、min floor、Context Cliff 都有，业界叫得上名的都在 |
| 入库 | 阶段类编排 + arq 队列 + dead letter 归因 + 双层去重 + BGE-M3 三态 + 影子迁移 | 架构健康，缺阶段级可观测与分阶段重试 |
| 治理安全 | output_guard 122 行、industry_rules 全链打通、RTBF/lineage/审计齐全 | 骨架完整，但模型级 Guard 是桩 |
| 召回重排 | retriever 9082 行四通道 + 16 reranker + 17 agentic workflow + 统计显著性全套 | 第一梯队，缺统一 LLM-Judge |

---

## 二、四份审计明细

### 2.1 文档解析 + 切块

解析侧：
- **Parser 清单**：`app/parsing/parsers/` 共 30 个 parser，6364 行。头部：deepdoc_parser 708 / deepseek_ocr 666 / base_parser 447 / magic_pdf 426 / paddle_vl 419 / etl4llm 382 / docling 317 / mineru 125 / marker 204 / textin 202 / olmocr 153 / glm_ocr 160 / mathpix 77 / colpali 36 等。
- **deepdoc vision 栈** `app/deepdoc/vision/` = 10161 行；`app/parsing/enrich/` 26 个富化模块（跨页表格 linker、公式 OCR、印章、水印、caption linker、reading order fixer、section tree、VLM caption 等）。
- **MinerU** 已集成（parser 125 行 + `app/services/mineru_service.py` ~910 行，cloud+local，`MINERU_MODEL_VERSION` 默认 `vlm`）；**Docling** 已集成（317 行）但无 JsonReportProcessor 式统一装配。
- **三档 PDF 判定已接主管线**：`pre_poc_scanner/pdf_page_classifier.py`（scan/text/low_density，0.7 阈值）+ `processors/processor.py` `drop_if_low_density`。pre_poc_scanner 全套齐全（格式分布/长度分位/MD5/SimHash/敏感信息/dashboard）。
- **双重输出已实现**：`app/parsing/output/{markdown,docx}_writer.py`；图片两阶段经 `artifact_normalizer.py` + `zip_processor.py`。

切块侧：
- **79 策略 18118 行**：late_chunking(+jina)、semantic(319)、parent_child(201，两级+sibling links)、token(101，token_300_50)、raptor(208)、agentic_chunker + 大量垂类（laws/policy_manual/meeting_minutes/qa_pairs/sop_steps/openapi/terraform 等）。
- **min chunk floor 已实现**（semantic.py 默认 256 + 小块合并）；**Context Cliff 已实现**（quality_scorer.py `CONTEXT_CLIFF_DANGER=2500`，分级 none/low/medium/high）。
- **Contextual 双路**：规则式 `contextual_enrichment.py`(198) + LLM 式 `llm_tagger.py`(213，summary+8 类标签，已挂 factory)。**三字段之 questions 缺失**。
- **chunking_grid 名义缺失**：近似物 `strategy_matrix.py`(1013 行) 偏"策略选择矩阵"而非"多策略网格打分"。
- **PageIndex TOC tree 维持不做**（`markdown_hierarchy.py` 193 行 overlay 路线，与 plan 决策一致）。

| 项目 | 状态 | 位置 |
|---|---|---|
| Parser 30 个 / deepdoc 10161 / enrich 26 模块 | 已实现 | `app/parsing/` + `app/deepdoc/vision/` |
| MinerU(VLM) / Docling 集成 | 已实现 | `mineru_parser.py` + `mineru_service.py` / `docling_parser.py` |
| Docling JsonReportProcessor 统一装配 | 缺失 | — |
| 解析 benchmark（TEDS/GriTS/edit dist/NID） | 部分（指标有、harness 无） | `app/parsing/quality/`（`parse_bench/` 空壳） |
| PDF 三档判定（0.7）+ pre_poc_scanner 全套 | 已实现（接主管线） | `app/rag/tools/pre_poc_scanner/` + `processors/processor.py:1204` |
| MD+DOCX 双输出 / 图片两阶段 | 已实现 | `app/parsing/output/` + `utils/` |
| 79 切块策略 / late chunking / parent-child / token_300_50 / raptor | 已实现 | `app/rag/chunking/strategies/` |
| min chunk floor / Context Cliff@2500 | 已实现 | `semantic.py` / `quality_scorer.py` |
| LLM 元数据 summary+keywords | 已实现 | `llm_tagger.py` + `metadata_enrichment.py` |
| LLM 三字段之 questions（HyDE 用） | 缺失 | — |
| chunking_grid 网格打分 | 部分 | `strategy_matrix.py`（选择矩阵） |
| PageIndex TOC tree | 维持不做 | `markdown_hierarchy.py` overlay |

### 2.2 入库管线

- **主流程**：`app/parsing/processors/processor.py`（6676 行，`process_document` 自 :2577），显式阶段类：Parsing→InlineAsset→Normalize→Governance→Chunking→ChunkDedup→ChunkAsset→Index→KG(:4505，队列开启则 `extract_kg_job` 独立入队)。
- **队列**：**arq（Redis）非 Celery**（`app/tasks/{queue,worker,jobs,locks}.py`；`TASK_QUEUE_ENABLED=false` 回退 BackgroundTasks；Redis 锁 + 租户/数据集信号量）。
- **失败归因完善**：`IngestDeadLetter`（failed_stage/error_code/retry_count/original_payload + `infer_failed_stage()`）+ `document_dead_letters.py` API。
- **去重双层**：文件级 SHA-256 content_hash；chunk 级 SimHash64（`simhash.py`+`near_dedup.py`，ChunkDedupStage）。
- **BGE-M3 三态**（`bge_m3_triplet.py` dense/sparse/colbert）；**双写防护**：影子 collection 蓝绿嵌入迁移（`indexer.py:116-244`）。
- **Dify 是检索侧非入库侧**：`integrations_dify.py`(7616 行) 为 Dify External Knowledge 检索协议端点；"plugin chunk readiness 门禁"在 `app/rag/pipeline_plugins/reports.py`（chunks_present + governance/chunk/kg metadata 契约校验）。

| 项目 | 状态 | 位置 |
|---|---|---|
| 阶段类编排 + arq 队列 + KG 两段式 | 已实现 | `processor.py` + `app/tasks/` |
| 分阶段重试 | **缺失**（reprocess 全量删重跑） | `api/v1/document_processing.py:179` |
| 文档级增量 toggle | **缺失**（连接器侧有 source_manifest 增量） | `connectors_runs.py:387` |
| 断点续传 | 部分（parse-cache stage=parsed 复用） | `processor.py:3101` |
| 进度粒度 | per-stage 百分比（15/33/66/80%），非 per-page | `processor.py` |
| 前端 page-client 拆分 | **未拆且膨胀**（6115 行，原 3720） | `web/app/knowledge/ingestion/page-client.tsx` |
| 失败归因 dead letter | 已实现 | `models/ingest_dead_letter.py` |
| OTel 阶段级 span | **偏薄**（仅 `app/core/otel.py` 100 行通用；`app/observability/` 不存在） | — |
| 速度异常告警 | **缺失**（stage_durations_ms 已记录未接告警） | — |
| SHA-256 + SimHash64 双层去重 | 已实现 | `indexer.py:286` + `preprocessing/simhash.py` |
| BGE-M3 三态 + 影子迁移 | 已实现 | `bge_m3_triplet.py` + `indexer.py:116` |
| 文档级 ACL | 已实现 | `models/document.py:58` + permission services |
| chunk-level ACL | **缺失**（搜索零命中） | — |
| quarantine 五类来源归因 | **缺失**（仅单一 governance-drop 状态） | `document_mutations.py:236` |
| plugin chunk readiness 门禁 | 已实现 | `pipeline_plugins/reports.py:225` |

### 2.3 治理 + 安全 Guard

- **output_guard 已扩容 35→122 行**（PII 正则 + 伪造引用检测 + 中文实体一致性 + 融合 + warn/block 三态）；input_guard 156、rules 70、retrieval_rail 46（含间接注入拦截 + PII 掩码，即 NeMo retrieval rail）。
- **⚠️ 最重要发现**：`llama_guard.py`(54)、`prompt_guard.py`(35)、`llm_guard.py`(51)、`pii_presidio.py`(131) **全部是同名正则桩**——未加载任何真实模型/权重，pyproject 无 presidio 依赖。中文 PII（手机/身份证/车牌/社保/信用卡）靠 `pii_anonymizer.py`(218) 正则 + `pii_llm_discover.py`(59) LLM 发现路径。
- **行业规则库全链已打通**（旧 plan"前端 0%/router 接入 0%"已过时）：`app/rag/industry_rules/` 413 行 + API 192 行；`orchestrator.py:2177` 调用 `apply_industry_rules_query_expansion`；前端 `industry-rules-workbench.tsx` 1222 行 + `/governance/industry-rules` 页面。
- **自动打标 LLM 路径已落地**：`llm_tagger.py` + GLiNER 暴露（`pipeline.py` `_collect_gliner_entity_annotations`）；provider 全集 cpu/llm/keyword/regex/gliner/pii/secret。
- **红队**：`redteam_suite.py`(82，含 ASR 计算) + `agent_redteam.py`(132)，**无内置攻击数据集**。
- **RTBF 已实现**：`rtbf.py`(64) + `rtbf_cascade.py`(273)，级联 documents/chunks/kg/vectors/object_assets/cache。
- **审计日志** 43 个文件调用（`audit.py` 1058 行）；**文档级 lineage** `lineage_service.py`(453) + provenance services。
- **quarantine 前端 3026 行未拆**（原 plan 记 2114，反而膨胀）；data-annotator 596 行仍 4 类标签 + 4 档 auto-tag provider。

| 项目 | 状态 | 位置 |
|---|---|---|
| output_guard 扩容 | 已修复 35→122 行 | `app/rag/safety/output_guard.py` |
| Llama Guard / Prompt Guard / Presidio | **桩实现（正则，非真模型/真库）** | `safety/llama_guard.py` 等 + `preprocessing/pii_presidio.py` |
| retrieval rail | 已实现 | `safety/retrieval_rail.py` |
| 中文 PII 正则 + LLM 发现 | 已实现 | `pii_anonymizer.py` + `pii_llm_discover.py` |
| LLM 打标 + GLiNER 治理暴露 | 已实现 | `llm_tagger.py` + `api/v1/pipeline.py:692` |
| industry_rules 全链（后端+检索接入+前端） | 已实现 | `industry_rules/` + `orchestrator.py:2177` + workbench 1222 行 |
| 红队评测 | 骨架（无内置数据集/无 ASR 基线数字） | `evaluation/redteam_suite.py` + `agent_redteam.py` |
| 审计日志 / RTBF / lineage | 已实现 | `audit.py` / `rtbf_cascade.py` / `lineage_service.py` |
| quarantine 前端拆分 | **未拆，3026 行** | `web/app/knowledge/quarantine/page.tsx` |

### 2.4 召回 + 重排 + 评测闭环

- **retriever.py 9082 行 / orchestrator.py 6128 行**；四通道 Vector+BM25+SPLADE(`sparse.py` 573)+ColBERT(`colbert_ann.py` 468 + plaid 105)；RRF（`retriever.py:8390`，rrf_k 可配）与加权（vector_weight=0.6）并存，另有 budgeted_rrf。
- **16 个 reranker 3712 行**：cross_encoder/colbert/llm_based(472，`0.7×llm+0.3×vector` 且按 tenant/query_type 动态)/ltr(457 含夜间训练)/hybrid/mmr/parent_child/kg/long_context_rerank(102 骨架)/bge_v2/dashscope/openai 等。
- **上下文扩展全套**：hierarchy_expand(394)/contextual_followup(283)/neighbor_expand(46，0.7/0.4 分档 span)/sibling_expand(110)/context_expansion(241)；`workflows/rerank_expand_rerank.py`(44) 完整两次重排管线；parent_child(72) 连坐。
- **17 个 agentic workflow 3099 行**：Self-RAG(88)/CRAG streaming(94 含 web search fallback)/FLARE(77)/react(435)/planner_worker(362)/evaluator_optimizer(431)/critic(145) 等；`tools/web_search.py`(263) + `hierarchical_retrieval_tools.py`(94)。
- **KG 检索侧全落地**：agentic_beam_search(142)/plan_on_graph(36，薄)/path_verbalizer(198)/pprank(125 HippoRAG 式)+pagerank(249)+method_router。
- **评测**：`regression_run_significance.py`(271，t-test/Wilcoxon/McNemar/Bootstrap/BH/Cohen's d 全套)；`evaluation/metrics/` NDCG/MRR/Recall@k/citation_coverage 已补全；`cost_tracker.py`(178) 已接各 runner。**统一 llm_judge.py 未独立**（散在 `ragas.py:868-1022`，缺 G-Eval/self-consistency/position-bias）。
- **Dify 插件**：`integrations_dify.py`(7616 行超大) 复用主检索路径；evidence/anchor 在 `plugin_policy.py`(472)+`planner.py`(884)+`evidence_gap.py`(74)；audit snapshot 经 `rag_trace_service.py`(1089)。

| 项目 | 状态 | 位置 |
|---|---|---|
| 四通道混合 + RRF/加权 | 已实现 | `retriever.py`(9082) + `retrieval/` |
| 16 reranker 含 LLM 动态加权 | 已实现 | `app/rag/reranker/`(3712) |
| neighbor_expand + rerank-expand-rerank + parent-child 连坐 | 已实现 | `retrieval/` + `workflows/rerank_expand_rerank.py` |
| MMR / query rewrite / multi-query / HyDE | 已实现 | orchestrator + workflows |
| Self-RAG / CRAG streaming / FLARE / web_search / A-RAG tools | 已实现 | `workflows/` + `tools/` |
| KG agentic（beam/verbalizer/PPR） | 已实现 | `kg/search/` |
| complexity_classifier / plan_on_graph | **薄实现**（27 行 / 36 行） | `policy/` + `kg/search/` |
| 统计显著性全套 + metric 补全 + cost tracker | 已实现 | `regression_run_significance.py` + `evaluation/metrics/` |
| 统一 llm_judge.py | **未独立** | 散在 `evaluation/ragas.py:868-1022` |
| Dify 插件（复用主路径） | 已实现但 7616 行过重 | `api/v1/integrations_dify.py` |

---

## 三、建议（按优先级）

### P0（杠杆最高，2-3 周量级）

**P0-1 安全 Guard "去桩化" + 红队 ASR 基线** — 全场最需正视。
政务/合规交付下宣称"已集成 Llama Guard/Presidio"与代码不符是宣称风险。二选一：
- 路线 A（推荐）：引入真实 Presidio（库很轻）+ 中文 recognizer 挂载现有正则；Llama Guard 3 需 GPU，可先用现有 LLM client 做 LLM-as-guard（¥0.005/次级别）替代；
- 路线 B：文件改名 `*_rules.py` + 文档如实标注"规则式"。
同时给 `redteam_suite.py` 内置中文攻击集（JailbreakBench/AdvBench 中文子集 + 政务注入样例），跑出 ASR 基线数字（目标 <5%）。**安全能力没有 ASR 数字等于没有。**

**P0-2 把"评测指标"组装成"可跑的 benchmark harness"**。
TEDS/GriTS/NID 已在 `app/parsing/quality/` 实现，只缺组装：
- `parse_bench`：golden set × parser × 指标 → 单文件 HTML（FILE_A023 三原则）；
- `chunking_grid`：token_300_50/semantic/late/parent-child × Recall@k/NDCG 网格。
业界提示（Vectara NAACL 2025 fixed-size 常胜 semantic；FloTorch 54% 假提升陷阱）：**不跑网格对照，79 个切块策略只是选择负担而非资产**。常州政务 golden set 可作第一个 fixture。

**P0-3 统一 `llm_judge.py`**。
从 ragas.py 抽出，补 G-Eval 结构化评分 + self-consistency（3×majority）+ position-bias 消除（换序双评）。不做的话 judge 波动会吃掉已认真算出的统计显著性。顺势把 citation_coverage 深化为句级引用 P/R——citation 评测是对政务客户最有说服力的"真护城河"。

**P0-4 OTel 阶段级 span + 入库速度告警**。
`stage_durations_ms` 已记录，只差 parse/chunk/embed/KG span + 历史分位数告警规则。量小杠杆大：排障从"看日志猜"变"看 trace 定位"。

### P1（1-2 月量级）

- **P1-1 入库运营短板**：分阶段重试（dead letter 已有 failed_stage，embed 失败不应重新解析整个 PDF）；quarantine 五类来源归因（output_guard/parse_risk/pii/acl_unclear/user_flag，直接决定隔离区审核效率）。
- **P1-2 巨文件拆分**（按交付关键路径排序）：`integrations_dify.py` 7616（当前主线，最优先）→ ingestion `page-client.tsx` 6115 → quarantine `page.tsx` 3026 → `processor.py` 6676 → `retriever.py` 9082。前两个尽快，否则 Dify 主线每个改动回归面都在扩大。
- **P1-3 薄实现补厚**：`complexity_classifier.py`(27 行) 用 query 日志训 TF-IDF+SVM（调研验证可达 93%）；`plan_on_graph.py`(36 行) 补 PoG（WWW'25，比 ToG +18.9% acc / token -50%）的 planning/reflection 主体。
- **P1-4 chunk-level ACL**：文档级已完整，chunk 级零命中。政务多部门（同一文件不同科室可见段落不同）是天然买单方。
- **P1-5 两个便宜增量**：LLM 元数据补 questions 字段（llm_tagger 通道现成，配 HyDE 反向检索，服务 POC"超纲验证"）；知识冲突整合（Astute RAG prompt 版 training-free，`components/knowledge_consolidation.py` 接 engine 生成前——6 月调研确认这是最大纯 RAG 空白）。

### P2（按需）

- PageIndex TOC tree：维持"不做，等 router 有真实需求再按决策门槛（<5pt 且 >3× cost 不引入）跑对照"。
- Docling JsonReportProcessor 统一装配：下次动解析装配层时顺手做。

---

## 四、如果只做三件事

1. **Guard 去桩化 + 红队 ASR 基线**（合规交付的诚实性问题）；
2. **parse_bench / chunking_grid harness 跑通出数**（把已建能力变成可 quote 的硬数据）；
3. **统一 llm_judge**（让所有评测数字可信）。

三件都不新增大依赖，且直接服务当前政务交付主线。
