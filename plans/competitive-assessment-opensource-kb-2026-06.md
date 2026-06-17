# MimirQ vs 市面开源知识库项目 — 客观对标评估（2026-06）

> 立场：**纯客观自我认知**。强项与短板均如实呈现，不为融资/销售/任何场景做包装。
> 数据原则：凡涉及 MimirQ 的论断，均以代码库实测（`wc -l` / `ls` / `grep`）为据，附文件路径；
> 凡涉及竞品的数字，均标注来源与时间（2026 年），量级估计明确标"约/未精确核实"。

---

## 0. 评估方法与数据来源

- **自身核查**：2026-06-15 对 `/data/temp34/MimirQ` 全量只读核查（6 大子系统 + 细节复核），非依赖历史记忆。
- **竞品刷新**：英文 WebSearch（中文搜索 MCP 套餐到期不可用），关键 star 取自 daily GitHub ranking（2026-06-01/06-12 缓存）。
- **盲区声明**：① 部分竞品 star 仅拿到量级（MaxKB/QAnything/Kotaemon/Haystack/R2R 等未逐一精确核实）；② 竞品"是否实现某能力"以官方描述为准，未逐一读其源码，深度对比以 MimirQ 实测为锚。

---

## 1. 一页结论（TL;DR）

**MimirQ 是什么**：一套 **61 万行级**（后端 31.7 万行 Python / 1089 文件 / **1359 个测试文件**，前端 29.6 万行 TS / 94 页面）的**企业级 RAG 研发与数据治理平台**。它不是"5 分钟搭个客服机器人"的轻量工具，而是把"解析→切块→检索→KG→Agentic→评测→治理→可观测"全链路做到研发级深度的重型系统。

**一句话定位**：
> 在**RAG 核心引擎深度 + 数据治理/评测闭环**这两个维度上，MimirQ 已达到或超过所有主流开源知识库项目；但在**社区生态、品牌心智、可视化应用编排、轻量化开箱即用**这四个维度上，与 Dify/RAGFlow 存在数量级差距。

**最尖锐的客观事实**：
- ✅ 工程深度：**第一梯队**，解析栈广度（32 parser）、内建评测/治理闭环（完整治理前端）、KG agentic 深度，**单项能力普遍强于** Dify/FastGPT/MaxKB/AnythingLLM，与 RAGFlow 互有胜负。
- 🔴 生态品牌：**接近于零**。Dify 143k★、RAGFlow 82k★ 是社区/插件/集成/心智的护城河；MimirQ 私有项目、0 star、0 第三方插件、0 公开 benchmark 奖牌。这是**最大且最难追**的差距。
- 🟡 产品形态：**偏研发平台、偏重**。缺面向业务用户的可视化工作流编排画布（Dify/FastGPT/Coze 的核心卖点），学习与部署成本显著高于轻量竞品。

### 1.1 小畅政务 200 题四链路复测（2026-06-15）

本节记录同一批 Golden 问题集对四条链路的完整复测结果，用于判断 MimirQ 作为 Dify 知识库替换/增强层的实际收益。

**测试输入与边界**：
- Golden 集：`/tmp/dify_compare_200_cases_with_area.json`，200 条，覆盖 `01政务服务事项知识`、`02高效办成一件事`、`03常州市常见问题`、`04专题常见问答`、`05业务部门常见问题`、`06各区常见问题`。
- 时间：2026-06-15 19:38 起（Asia/Shanghai）。
- 本地服务：`http://127.0.0.1:8000`，评测期间临时提高本地 API rate limit，评测后已恢复默认启动并通过健康检查。
- Dify App：
  - 原生 Dify 知识库：`00000000-0000-0000-0000-000000000001`
  - Dify HTTP 请求 MimirQ：`00000000-0000-0000-0000-000000000002`
  - Dify 外部知识库接 MimirQ：`00000000-0000-0000-0000-000000000003`

| 链路 | 接口成功 | grounding | 关键点召回 | 延迟 |
|---|---:|---:|---:|---:|
| MimirQ 直连检索 | 200/200 | 检索证据 `0.990` | `0.994` | 不走 Dify 生成 |
| 原生 Dify `a398` | 191/200 | `0.534` | `0.630` | avg `7.14s`, p95 `15.44s`, max `49.45s` |
| Dify HTTP -> MimirQ `a3c` | 200/200 | `0.825` | `0.899` | avg `5.71s`, p95 `11.99s`, max `14.63s` |
| Dify 外部知识库 -> MimirQ `3c1c` | 200/200 | `0.830` | `0.899` | avg `4.84s`, p95 `9.05s`, max `13.67s` |

**直接结论**：
- MimirQ 两种 Dify 接入链路均达到 `200/200` 成功，且 grounding / 关键点召回显著高于原生 Dify 知识库。
- `3c1c` 外部知识库链路本轮速度最好：p95 `9.05s`，max `13.67s`。
- `a3c` HTTP 请求链路在修复 Dify 结果转换节点后不再出现上下文超长问题，本轮 `200/200` 直接通过。
- 原生 Dify `a398` 剩余 9 条稳定失败，错误均为 `Model bge-reranker-large credentials is not initialized.`，属于 Dify 原生知识库 reranker 模型凭据配置问题，不是 MimirQ 检索问题。

**证据文件**：
- MimirQ 直连评测：`/tmp/mimirq_direct_200_full_20260615_193802_eval.json`
- 原生 Dify 合并结果：`/tmp/dify_a398_native_full_merged_20260615_193802_answers.json`
- 原生 Dify 评测：`/tmp/dify_a398_native_full_merged_20260615_193802_eval.json`
- Dify HTTP -> MimirQ 结果：`/tmp/dify_a3c86554_full_20260615_193802_answers.json`
- Dify HTTP -> MimirQ 评测：`/tmp/dify_a3c86554_full_20260615_193802_eval.json`
- Dify 外部知识库 -> MimirQ 结果：`/tmp/dify_3c1c_full_20260615_193802_answers.json`
- Dify 外部知识库 -> MimirQ 评测：`/tmp/dify_3c1c_full_20260615_193802_eval.json`

### 1.2 小畅政务额外 300 题压力复测（2026-06-15）

本节是在 200 题之后额外生成并运行的 300 条问题，用于验证长尾问题、Dify 接入稳定性和慢查询修复是否成立。

**测试输入与覆盖**：
- Golden 集：`/tmp/dify_compare_extra300_cases_20260615_202337.json`，300 条。
- 覆盖分布：`01政务服务事项知识` 120、`02高效办成一件事` 33、`03常州市常见问题` 52、`04专题常见问答` 15、`05业务部门常见问题` 40、`06各区常见问题` 40。
- 本轮先跑 MimirQ 直连检索，再跑 Dify HTTP -> MimirQ、Dify 外部知识库 -> MimirQ、原生 Dify 知识库三条 Dify 链路。

| 链路 | 接口成功 | 检索 hit@1 / hit@5 | 生成答案 grounding | 生成答案关键点召回 | 延迟 |
|---|---:|---:|---:|---:|---:|
| MimirQ 直连检索 | 300/300 | `0.923` / `0.953` | 不走生成 | 不走生成 | 检索日志 p95 `1.99s`, max `8.88s`, >10s `0` |
| Dify HTTP -> MimirQ `a3c` | 300/300 | `0.923` / `0.953` | `0.840` | `0.840` | avg `10.74s`, p95 `20.31s`, max `40.26s` |
| Dify 外部知识库 -> MimirQ `3c1c` | 300/300 | `0.923` / `0.953` | `0.833` | `0.833` | avg `18.14s`, p95 `44.13s`, max `59.08s` |
| 原生 Dify `a398` | 293/300 | 对照同一 MimirQ 复检集 | `0.519` | `0.519` | avg `15.39s`, p95 `44.55s`, max `59.50s` |

**慢查询根因与修复证据**：
- 本轮复测前暴露出一个真实长尾：问题 `公积金账户有挂账余额的情况下，怎么退回资金？` 触发 metadata DB fallback 的 JSON 文本扫描，单次检索曾到 `52-66s`。
- 修复方式不是加 timeout，而是默认禁用未索引的 metadata JSON 文本扫描，并让“问题型 query”在 question 字段无命中时停止宽泛 fallback。
- 修复后同类 metadata fallback 单测从 `26.2s` 降到约 `0.764s`；完整 Dify/MimirQ 检索日志累计 1863 条，avg `448.54ms`、p95 `1986.23ms`、max `8882.39ms`、`>10s=0`。

**直接结论**：
- MimirQ 检索层这轮没有 10 秒以上慢查询，说明核心慢点已经从检索层移出。
- Dify HTTP -> MimirQ 的端到端速度明显好于 Dify 外部知识库接法；外部知识库接法虽然成功率和质量接近，但 Dify 侧链路 p95/max 明显更高。
- 原生 Dify 仍有 7 条失败，错误为 `Model bge-reranker-large credentials is not initialized.`，属于 Dify 原生知识库链路配置问题。
- 300 题比 200 题更难，MimirQ 两条 Dify 接入生成答案指标仍显著高于原生 Dify；剩余质量短板主要集中在路由/范围选择和部分问法的期望来源不一致，而不是检索服务不可用。

**证据文件**：
- 300 题问题集：`/tmp/dify_compare_extra300_cases_20260615_202337.json`
- MimirQ 直连评测：`/tmp/mimirq_direct_extra300_20260615_2042_after_anchor_fix_eval.json`
- Dify HTTP -> MimirQ 结果：`/tmp/dify_a3c_http_extra300_20260615_2042_after_anchor_fix_w8_isolated_answers.json`
- Dify HTTP -> MimirQ 评测：`/tmp/dify_a3c_http_extra300_20260615_2042_after_anchor_fix_eval.json`
- Dify 外部知识库 -> MimirQ 合并结果：`/tmp/dify_3c1c_external_extra300_20260615_2042_after_anchor_fix_merged_answers.json`
- Dify 外部知识库 -> MimirQ 评测：`/tmp/dify_3c1c_external_extra300_20260615_2042_after_anchor_fix_eval.json`
- 原生 Dify 合并结果：`/tmp/dify_a398_native_extra300_20260615_2042_after_anchor_fix_merged_answers.json`
- 原生 Dify 评测：`/tmp/dify_a398_native_extra300_20260615_2042_after_anchor_fix_eval.json`

---

## 2. MimirQ 真实现状体检（按子系统，全部有据）

### 2.1 总规模（实测）
| 维度 | 实测值 | 命令证据 |
|---|---|---|
| 后端 Python | **317,114 行 / 1089 文件** | `find app -name '*.py' \| xargs wc -l` |
| 测试文件 | **1359 个 `test_*.py`** | `find tests -name 'test_*.py' \| wc -l` |
| 前端 TS/TSX | **295,881 行 / 94 page.tsx** | `find web -name '*.tsx' -o -name '*.ts'` |
| API 面 | **91 个 `app/api/v1/*.py` 模块** | `ls app/api/v1` |
| 配置项 | `config.py` **3237 行** | `wc -l app/core/config.py` |

> 测试与代码近 1:1 的比例（1359 测试文件）在开源知识库项目里属于**罕见的高工程纪律**。

### 2.2 文档解析 — **客观强项**
- **32 个 parser**（`app/parsing/parsers/`），覆盖几乎全部 2025-2026 SOTA：
  `mineru` / `docling` / `marker` / `mathpix` / `olmocr` / `paddle_vl` / `textin` / `tcadp`（腾讯）/ `qianfan_ocr`（百度）/ `glm_ocr`（智谱）/ `deepseek_ocr` / `colpali`（视觉）/ `magic_pdf` / `markitdown` / `etl4llm` + 自研 `deepdoc_parser`。
- 自研 **deepdoc vision 栈**（layout/ocr/recognizer/table）。解析子系统合计 **29,837 行**。
- 含 `service_url_fallback.py` 降级链。
- **客观判断**：解析广度（"全 SOTA 同台 + 可对照 + 国产全覆盖"）**市面少见**。RAGFlow 强在自研 DeepDoc 单线打磨，MimirQ 是"全都要 + 可切换 + 可质量对比"。

### 2.3 切块 — **客观强项**
- **79 个切块策略**（`app/rag/chunking/strategies/`），合计 **21,931 行**。
- 高级技术已落地：`contextual_enrichment.py`（Anthropic 式）、late chunking、parent-child、RAPTOR、hierarchy（均在 `factory.py`/`strategy_matrix.py` 注册）。
- **客观判断**：策略丰富度**远超**所有竞品（竞品通常 3-8 种）。风险是"79 种"可能存在重叠/维护负担，且**未见对外公开的切块质量 benchmark 分数**。

### 2.4 检索与重排 — **客观强项**
- 核心：`engine.py` 4455 / `retriever.py` **9082** / `orchestrator.py` 6075 / `pipelines/langgraph.py` 1849（合计 21,461 行）。
- 召回融合：Vector + BM25 + SPLADE + ColBERT，RRF + 加权融合（`retriever.py`）。
- **高级策略全部已落地**（旧记忆标 P0 的均已完成）：CRAG（`workflows/crag_streaming.py`）、Self-RAG（`workflows/self_rag.py`）、FLARE（`workflows/flare.py`）、Adaptive/复杂度路由（`engine.py`）、HyDE、multi-query、MMR、Web Search 工具（`tools/web_search.py`）。
- **Reranker 13+ 种**（`app/rag/reranker/`）：cross_encoder / bge_v2 / local_bge_v2_m3 / colbert / llm_based / long_context_rerank / ltr（learning-to-rank）/ mmr / parent_child / kg / hybrid / dashscope / openai。
- **Embedding 8 个 provider**：openai / dashscope / cohere / jina / voyage / bedrock / ollama / local（旧记忆"4 个"已过时）。
- **客观判断**：检索栈的**通道数 + 高级策略 + reranker 种类**为对标项目中最全之一。短板同样是"未见公开 benchmark 量化"。

### 2.5 知识图谱 — **客观强项（含对旧记忆的重大修正）**
- KG 子系统 **20,067 行 / 41 文件**：`extraction/extractor.py` 2879、`kg/api/routes.py` 4304、`repository.py` 1309、`manual_import.py` 1366、`community.py` 597（LLM 社区摘要）、`search/recall.py` 966。
- **Agentic 图搜索已落地**：`search/agentic_beam_search.py`（143）+ `search/path_verbalizer.py`（199）+ `search/plan_on_graph.py`（37，**偏薄**）。
- **PPR 召回**：`search/pprank.py` + `search/ranking/pagerank.py`（HippoRAG 式）。
- **网络分析**：`api/v1/network_analysis.py`（208）实现 k-hop / shortest_path / centrality。
- **快照不再是"假快照"**（重大修正）：`kg/snapshot.py`（202）含 `_append_exact_detail_diff` —— node/edge 的 added/removed/changed **精确 diff** + `props_hash` 属性级比对 + canonical hash + v1/v2 schema。
- **客观判断**：indexer 侧已达 GraphRAG 级，agentic searcher 侧（beam+verbalizer）已补齐，**整体比 RAGFlow GraphRAG / LightRAG / 微软 GraphRAG 更工程化、更全**（它们多止步于"索引+社区摘要"）。`plan_on_graph` 37 行偏薄是局部短板。

### 2.6 Agentic / 工作流 — **客观强项（开发者向）**
- `workflows/` 17 文件 3106 行：CRAG / Self-RAG / FLARE / critic / react / planner_worker / evaluator_optimizer / routing / parallelization / rerank_expand_rerank / self_route / chain / system_router。
- `agents/` 1670 行：`rag_agent.py` 775 / `multi_agent.py` 426 / `prebuilt.py` 397。
- `tools/` 2952 行：`web_search` 264 / `mcp_tools` 1244 / `mcp_client` 574 / `hierarchical_retrieval_tools` 95 / `simple_kb_search` / **`pre_poc_scanner/` 全套** / `mcp_server`。
- **客观判断**：Agentic 模式覆盖完整且**已接入 MCP（client+server+tools）**。但**形态是代码态**（开发者编排），**无可视化拖拽编排画布**——这是与 Dify/FastGPT/Coze 的产品形态根本差异。

### 2.7 评测与治理 — **客观护城河（最独特）**
- `app/rag/evaluation/` **12,158 行**：`ragas.py` **2293**（`ragas==0.4.3` 真依赖）、`agent_evals.py` 765、`regression_sample_builder.py` 1066、`kg_search_diagnostics.py` 1085、`test_generator.py` 662、`redteam_suite.py` + `agent_redteam.py`、`multihop.py`、`calibration.py`、`multimodal_slices.py`、`embedding_bench/` / `graphrag_bench.py` / `ragcap_bench_runner.py`、**`poc_runner/` 全套**（attribution_classifier / out_of_scope_verifier / query_pattern_miner / telemetry / reports{html,png,umap}）。
- 治理前端页面：`/evaluations` `/evaluations/ablations` `/graph/diagnostics` `/graph/snapshots` `/datasets/[id]/precheck` `/knowledge/feedback` `/knowledge/quarantine` `/knowledge/similarity` `/data-governance` `/governance/industry-rules` `/audit`。
- 行业落地实证：`scripts/changzhou_gov_dify_full_gate.py` + `changzhou_gov_golden_eval.py`（常州政务知识库 golden eval + Dify gate）。
- **客观判断**：**所有主流开源竞品都没有可比的内建评测/消融/归因/治理闭环**。这是 MimirQ 最难被复制、也最独特的能力。短板：仍未见对外**公开**的 benchmark 榜单成绩（"有能力、没奖牌"）。

### 2.8 安全与合规 — **中等，部分薄壳**
- `safety/` 598 行：`input_guard.py` 157（role hijack/instruction override/delimiter/HTML entity/zero-width/base64/indirect injection）、`output_guard.py` 123（**真接入 LlamaGuard**，`from app.rag.safety.llama_guard import LlamaGuard`）、`llama_guard.py` 55、`prompt_guard.py` 36、`retrieval_rail.py` 47、`rules.py` 71。
- **真实短板**：`output_guard` 的 PII 仍是**正则硬编码分数**（`pii_phone 0.72 / pii_id_card 0.9`），**Presidio 未真正接入**（依赖与 import 均为空）。
- 企业合规特性齐全：`rbac.py` / `scim.py` / `groups.py` / `rtbf.py`（被遗忘权）/ `audit.py` / `lineage.py` / `usage.py`。
- **国密 SM2/SM4 未实现**（grep 无命中）；国产化离线包未见。
- **客观判断**：Guard 框架完整（Llama Guard + Prompt Guard + retrieval rail），但 **PII/Presidio 是真实未完成项**；合规特性（RBAC/SCIM/RTBF/审计/血缘）反而**强于绝大多数开源竞品**。

### 2.9 连接器与数据源 — **功能丰富但抽象不统一（架构隐患）**
- **真实实现的连接器**（`app/api/v1/connectors_*`）：Jira **2604** / Confluence **2030** / GitHub 755 / Google Drive 716 / MinIO 615 / Web Crawl 436（合计 7156 行）+ DB Catalog（`connectors/db/` 1276 行，唯一走 `ConnectorBase` 抽象）。
- **真实短板**：连接器主体在 **API 层重实现**，**未走统一 `ConnectorBase` 抽象**（仅 db catalog 走了）；外部 SDK（atlassian/PyGithub/boto3）未在依赖中，疑用 httpx 直连 REST → 维护性与一致性隐患。
- **客观判断**：连接器覆盖度（Jira/Confluence/GitHub/Drive/MinIO/Web）已不弱，但**架构治理欠账**；相比之下 Onyx/LlamaHub 的连接器是"标准化插件生态"，MimirQ 是"逐个硬编码"。

### 2.10 / 2.11 / 2.12 工程化 / 前端 / 部署
- **前端**：~29.6 万行，可视化全家桶 echarts6 / plotly3.5 / recharts3.8 / force-graph 2d+3d / tanstack-query+virtual / comlink；国际化（`[locale]` 路由）；企业控制台覆盖 graph/chunk-preview/parsing/evaluations/ablations/precheck/feedback/quarantine/similarity/observability/governance/rbac/scim/audit。**前端工程化与可视化深度在知识库赛道属顶级**。
- **可观测**：OTel 真接入（`opentelemetry-sdk==1.40.0` 全套 + `app/core/otel.py`）。
- **后端栈**：FastAPI + SQLAlchemy 2 + Milvus（`pymilvus 2.6.11`）+ Chroma + Redis + PostgreSQL；LLM 层有 `fallback.py` 降级链 + `structured_output.py` + `prompt_cache.py`。
- **部署**：7 个 docker-compose（web/parsers/lite/retrieval-dev/infra + 主）+ Dockerfile，含 **lite 版**。
- **真实短板**：向量后端较单一（Milvus 主，Qdrant/ES/Infinity 未落地；RAGFlow 用 Infinity/ES 可选更灵活）。

---

## 3. 竞品全景（2026，按形态分三类）

### 3.1 开箱即用平台（与 MimirQ 同赛道）
> **全平台总览**（开箱即用知识库/RAG 平台，按 GitHub star 降序；✅强 / 🟡中 / 🔴弱·缺）。MimirQ 行置顶为锚。star 来源见 §9。

| 项目 | Star(2026) | 形态/定位 | 解析 | 知识图谱 | 可视化编排画布 | 内建评测/治理 | 企业合规 | 中文/国产 | 开箱/轻量 |
|---|---|---|---|---|---|---|---|---|---|
| **MimirQ**（本项目） | 私有·0★ | 企业 RAG 研发+治理平台（重型） | ✅ 32 parser+自研 | ✅ agentic+网络分析 | 🔴 无 | ✅ 完整内建 | ✅ RBAC/SCIM/RTBF/审计 | ✅ 政务实测 | 🔴 重 |
| **Dify** | **143k** | LLM 应用/Agent 工作流平台（一站式） | 🟡 调三方 | 🔴 | ✅ 核心卖点 | 🔴 | 🟡 商业版 | ✅ | ✅ |
| **Open WebUI** | **141k** | 自托管 LLM 前端（带 RAG） | 🟡 | 🔴 | 🟡 pipelines | 🔴 | 🟡 | 🟡 | ✅ |
| **RAGFlow** | **82k** | 深度文档理解 RAG 引擎+Agent | ✅ 自研 DeepDoc | ✅ GraphRAG | 🟡 Agent 流 | 🟡 | 🟡 | ✅ | 🟡 |
| **AnythingLLM** | **54k** | 全能本地优先 AI 应用 | 🟡 | 🔴 | 🟡 | 🔴 | 🟡 | 🟡 | ✅ |
| **Quivr** | **39k** | "第二大脑"可嵌入 RAG | 🟡 | 🔴 | 🔴 | 🔴 | 🟡 | 🟡 | ✅ |
| **Onyx**(原 Danswer) | **30k** | 企业搜索+40+ 连接器 | 🟡 | 🔴 | 🟡 | 🟡 连接器/权限 | 🟡 | 🟡 | 🟡 |
| **FastGPT** | **27k** | 知识库优先+可视化 Flow | 🟡 | 🔴 | ✅ 核心卖点 | 🔴 | 🟡 | ✅ | ✅ |
| **Kotaemon** | **25k** | 干净可定制 RAG UI（含 GraphRAG） | 🟡 | 🟡 部分 GraphRAG | 🔴 | 🔴 | 🔴 | 🟡 | ✅ |
| **MaxKB** | **20k** | 企业 Agent 平台+RAG（GPL v3） | 🟡 | 🔴 | ✅ 工作流+MCP | 🔴 | 🟡 | ✅ | ✅ |
| **QAnything** | **14k** | 有道，本地化知识库问答 | 🟡 | 🔴 | 🔴 | 🔴 | 🟡 | ✅ | ✅ |

### 3.2 开发框架/库（不同形态：给开发者拼装，非开箱平台）
| 项目 | Star（2026） | 定位 |
|---|---|---|
| **LangChain/LangGraph** | **~120k** ([src](https://www.firecrawl.dev/blog/best-open-source-rag-frameworks)) | 最大生态，500+ 集成，agent 编排 |
| **LlamaIndex** | **~45k** ([src](https://github.com/run-llama/llama_index)) | 数据框架，检索策略最讲究，300+ connector |
| **Haystack** | ~20k（估） | deepset，企业生产级 pipeline（"为通过审计而生"） |
| **R2R** | ~7k（估） | 轻量端到端 RAG，低延迟，SciPhi Cloud |
| **txtai / Cognita / Verba** | 4-12k（估） | 嵌入式/编排/Weaviate 官方示例 |

> **关键区别**：框架/库是"零件"，需开发者自己拼成产品；Dify/RAGFlow/MimirQ 是"整机"。两者不直接可比。
> **行业风向**：[LlamaIndex 创始人承认"框架时代"正被 Agent SDK / MCP / coding agent 取代](https://www.mindstudio.ai/blog/llm-frameworks-replaced-by-agent-sdks)——这对"整机平台"是利好。

### 3.3 图谱/研究类
| 项目 | Star（2026） | 定位 |
|---|---|---|
| **LightRAG** | **36.5k** ([src](https://github.com/hkuds/lightrag)) | HKU，EMNLP 2025，轻量图谱 RAG，可跑 CPU |
| **微软 GraphRAG** | ~25k（估） | 图谱索引器 + 社区摘要（多跳问答），偏"索引器/研究原型" |
| **nano-graphrag** | ~3k（估） | 极简 GraphRAG 复现，研究/教学用 |

> **客观判断**：图谱类项目多为**索引器或研究原型**，非完整产品。MimirQ 的 KG 栈（agentic searcher + 网络分析 + 精确快照 + provenance）在工程完整度上**超过**这一类。

---

## 4. 多维对标矩阵（客观，✅强 / 🟡中 / 🔴弱·缺）

| 维度 | MimirQ        | Dify | RAGFlow | FastGPT | AnythingLLM | LangChain |
|---|---------------|---|---|---|---|---|
| 文档解析深度 | ✅ 32 parser+自研 | 🟡 | ✅ DeepDoc | 🟡 | 🟡 | 🔴(靠插件) |
| 切块策略 | ✅ 79 种        | 🟡 | 🟡 | 🟡 | 🔴 | 🟡 |
| 检索/重排深度 | ✅ 13 reranker+全策略 | 🟡 | ✅ | 🟡 | 🟡 | ✅(靠拼装) |
| 知识图谱 | ✅ agentic+网络分析 | 🔴 | ✅ GraphRAG | 🔴 | 🔴 | 🟡 |
| Agentic 模式 | ✅ 代码态全覆盖+MCP  | ✅ 可视化 | ✅ | ✅ 可视化 | ✅ | ✅ |
| **可视化工作流编排** | 🔴 **无画布**    | ✅ **核心卖点** | 🟡 | ✅ **核心卖点** | 🟡 | 🔴 |
| 内建评测/治理闭环 | ✅             | 🔴 | 🟡 | 🔴 | 🔴 | 🔴 |
| 安全 Guard | 🟡 框架全/PII薄   | 🟡 | 🟡 | 🟡 | 🟡 | 🔴 |
| 企业合规(RBAC/SCIM/RTBF/审计) | ✅ 齐全          | 🟡 商业版 | 🟡 | 🟡 | 🟡 | 🔴 |
| 连接器生态 | 🟡 6+种/抽象不统一  | 🟡 | 🟡 | 🟡 | ✅ 标准化 | ✅ LlamaHub |
| 可观测(OTel) | ✅ 真接入         | 🟡 | 🟡 | 🟡 | 🟡 | 🟡 |
| 前端/可视化 | ✅ 顶级(29.6万行)  | ✅ | 🟡 | ✅ | ✅ | 🔴 |
| 轻量/开箱即用 | 🔴 **重**      | ✅ | 🟡 | ✅ | ✅ | 🟡 |
| **社区/生态/品牌** | 🔴 **0 star/私有** | ✅ 143k | ✅ 82k | ✅ 27k | ✅ 54k | ✅ 120k |
| **公开 benchmark 成绩** | 🔴 **无奖牌**    | 🟡 | 🟡 | 🔴 | 🔴 | 🟡 |
| 中文/政务垂直 | ✅ 实测落地        | ✅ | ✅ | ✅ | 🟡 | 🟡 |

---

## 5. MimirQ 的真实强项（有据）

1. **数据治理/评测闭环**：内建评测栈 `evaluation/` 12158 行 + RAGAS（真依赖）+ redteam + 多 benchmark runner + 完整治理前端（precheck/feedback/quarantine/ablations/diagnostics）。在开源知识库竞品中少见同等内建闭环。
2. **解析栈广度**：32 parser 全 SOTA 同台 + 国产全覆盖 + 可质量对照。
3. **KG 工程完整度**：indexer + agentic searcher + PPR + 网络分析 + 精确快照 diff + provenance，超过纯图谱类项目。
4. **企业合规特性**：RBAC/SCIM/RTBF/审计/血缘/usage 计量齐全，强于绝大多数开源竞品。
5. **工程纪律**：1359 测试文件、OTel 真接入、LLM fallback 链 + structured output + prompt cache。
6. **中文 + 政务可落地**：常州政务实测，国产解析/LLM 全接入。
7. **可作为 Dify 后端互补**：`integrations_dify.py`（3457 行）实现 Dify 外部知识库适配——**可做 Dify 的"检索大脑"而非纯零和竞争**。

## 6. MimirQ 的真实短板（不回避）

1. 🔴 **生态/品牌/star = 0**：最大且最难追。竞品的 30k-143k star = 社区贡献 + 插件市场 + 集成生态 + 招聘/信任心智，这些无法靠堆代码补齐。
2. 🔴 **无可视化工作流编排画布**：Dify/FastGPT/Coze 的核心卖点缺失，把"非技术业务用户"这一最大客群挡在门外。
3. 🔴 **无公开 benchmark 奖牌**：能力强但缺对外可引用的客观成绩（OmniDocBench/CRUD-RAG/GraphRAG-Bench 等），销售与信任建立缺硬证据。
4. 🟡 **偏重、学习/部署成本高**：61 万行、91 API、47+ 页面——对中小客户"过重"，上手曲线远陡于 Dify/FastGPT。
5. 🟡 **若干真实薄壳/欠账**：Presidio 未接（PII 靠正则）、`plan_on_graph` 37 行偏薄、连接器未统一抽象、向量后端单一（仅 Milvus/Chroma）、国密/离线政务包未落地。
6. 🟡 **定位过宽**："研发平台 + 治理平台 + 引擎"三位一体，对外讲清楚"它到底是什么"比竞品困难。

## 7. 护城河 vs 快被追平

**真护城河（难复制）**：
- 数据治理/评测/消融/归因闭环（★★★★★）—— 竞品基本空白，且需长期工程积累。
- 行业规则库 + POC 运营方法论（`industry_rules` + `poc_runner`，★★★★★）—— 数据资产 + 销售确定性。
- KG 影响分析 + 精确快照治理（★★★★）—— 杀手级 B 端场景。
- 中文政务/合规垂直可落地（★★★★）—— 海外/纯开源进不来。

**快被追平（别当壁垒）**：
- 解析栈：Reducto/Mistral OCR/RAGFlow DeepDoc 在持续追赶。
- Agentic：随 OpenAI Agents SDK / MCP 标准化，门槛在下降。
- 检索高级策略：CRAG/Self-RAG 等已是公开方法，竞品迟早跟进。

## 8. 客观结论与定位判断

- **技术体检结论**：MimirQ 在**纯工程深度**上处于开源知识库的**第一梯队**，在**评测/治理**这一细分维度上是**事实上的领先者**。这不是包装，是 61 万行代码 + 1359 测试 + 实测能力支撑的客观结论。
- **市场体检结论**：MimirQ 在**生态、品牌、产品轻量化、可视化编排**上**显著落后**于 Dify/RAGFlow。技术领先 ≠ 市场领先，这两者目前是**割裂**的。
- **核心矛盾**：MimirQ 把资源压在了"深度"（治理/评测/KG），而主流市场用脚投票的是"广度心智 + 易用编排"（Dify/FastGPT）。**这不一定是错——但必须清楚：MimirQ 走的是"深耕 B 端治理/合规/垂直"的路，不是"开源社区争霸"的路。** 用错赛道的标尺（比 star）会得出错误的悲观结论；用对赛道的标尺（比治理深度/垂直落地）会得出过度乐观结论。两者都要看。

> **一句话**：MimirQ 是"技术上被低估、市场上未被认知"的重型选手。它的问题不在"能力不够"，而在"能力没有被赛道化、产品化、可信化（benchmark）地表达出来"。

## 9. 附录

**自身核查命令**（可复现）：
```
find app -name '*.py' | grep -v __pycache__ | xargs wc -l | tail -1   # 317114
find tests -name 'test_*.py' | wc -l                                   # 1359
ls app/rag/reranker/*.py ; ls app/rag/embedding/providers/*.py
ls app/rag/chunking/strategies/*.py | wc -l                            # 79
ls app/parsing/parsers/*.py | wc -l                                    # 32
find app/rag/kg -name '*.py' | xargs wc -l | tail -1                   # 20067
find app/rag/evaluation -name '*.py' | xargs wc -l | tail -1           # 12158
wc -l app/rag/safety/*.py ; wc -l app/api/v1/integrations_dify.py      # 3457
```

**竞品数据来源**：
- [GitHub-Ranking-AI Top100 RAG（daily）](https://github.com/yuxiaopeng/Github-Ranking-AI/blob/main/Top100/RAG.md) — Dify 143,366 / RAGFlow 81,634（2026-06-01）
- [RAGFlow 官方仓库](https://github.com/infiniflow/ragflow)
- [15 Best Open-Source RAG Frameworks 2026 (firecrawl)](https://www.firecrawl.dev/blog/best-open-source-rag-frameworks)
- [FastGPT vs Dify (dev.to)](https://dev.to/victorjia/fastgpt-vs-dify-the-chinese-rag-platform-battle-youre-missing-18eo)
- [AnythingLLM 仓库](https://github.com/Mintplex-Labs/anything-llm) ~54k / [Onyx 仓库](https://github.com/onyx-dot-app/onyx) 30.3k / [LightRAG](https://github.com/hkuds/lightrag) 36.5k / [LlamaIndex](https://github.com/run-llama/llama_index) ~45k / [MaxKB](https://github.com/1Panel-dev/maxkb)
- [框架时代被 Agent SDK 取代 (MindStudio)](https://www.mindstudio.ai/blog/llm-frameworks-replaced-by-agent-sdks)

> 注：MaxKB/QAnything/Kotaemon/Haystack/R2R/Cognita/Verba/txtai/nano-graphrag 的 star 为量级估计，未逐一精确核实；竞品能力以官方描述为准，未逐一读源码。
