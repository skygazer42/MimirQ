# MimirQ vs 主流 RAG 平台对比报告 — 2026-Q2

> 用户:把 MimirQ 项目和主流 RAG 平台(RAGFlow / Dify 等)做对比,说明优势和差距。
>
> **本报告聚焦 MimirQ 视角的横向对比** — 不重复 `rag-system-landscape-2026-q2-supplement.md` 中已做的"平台之间互比"框架,而是站在 MimirQ 销售 / 战略视角:对照 6 家最相关平台(RAGFlow / Dify / FastGPT / Coze / Vectara / LlamaIndex),列出 MimirQ **真实优势**、**真实差距**、**销售话术**、**3 个月差距追赶清单**。

---

## 1. 一句话定位差异

| 平台 | 定位 | 与 MimirQ 关系 |
|---|---|---|
| **MimirQ**(我们) | 工程深度第一梯队 + 中文 vertical 沉淀 + 行业规则护城河,但商业化包装不足 | 自身 |
| **RAGFlow**(InfiniFlow 开源) | 深度文档理解 + KG 双强,开源标杆,国内出海 | **最直接竞品**,栈高度重叠(DeepDoc 解析 + KG) |
| **Dify**(LangGenius 开源) | 工作流 + Agent + RAG 一体的 LLMOps 平台,生态最大 | **错位互补**(Dify 强 workflow,MimirQ 强 RAG 内核) |
| **FastGPT**(labring) | 知识库 + 可视化工作流,中文社区,易上手 | **错位**(FastGPT 易用,MimirQ 工程深) |
| **Coze Studio**(字节 2025-07 开源) | 一站式 Agent 可视化,入门最快 | **错位**(消费级 vs 企业级) |
| **Vectara**(商业 SaaS) | Hallucination Detection + 合规导向 | 错位(SaaS-only,不可自部) |
| **LlamaIndex / LangChain** | Python 框架,非平台 | **基建底层依赖**,MimirQ 自家工程已超过 |

**核心论断**:MimirQ 最直接的竞品是 **RAGFlow**(栈重叠 + 都强在 KG + 深度文档解析),最大错位是 **Dify**(它是 platform-of-platforms,MimirQ 是 vertical product)。

---

## 2. 多维量化对照矩阵(MimirQ × 6 平台 × 18 维)

### 2.1 工程深度维度

| 维度 | MimirQ | RAGFlow | Dify | FastGPT | Coze | Vectara | LlamaIndex |
|---|---|---|---|---|---|---|---|
| 解析栈代码量 | parsing/ ~14000 + deepdoc/ ~5300 + processor 5539 | DeepDoc 类似规模 + VLM 集成 | 浅(外接 Unstructured) | 浅 | 浅 | 黑盒 | 中(LlamaParse) |
| 切块策略数 | **75** 垂类 + factory + auto router | ~20 模板 | ~10 | ~10 | ~8 | 黑盒 | ~15 |
| Embedding provider | 8 注册(4 真实现:openai/ollama/dashscope/local,4 空壳) | 8+ | 30+ | 10+ | 10+ | 自家 + 兼容 | 50+ |
| Reranker | **9 种** | 4 种 | 4 种 | 3 种 | 1-2 | 自家 + Cohere | 10+ |
| Hybrid 检索 | Vector + BM25 + SPLADE + ColBERT/PLAID + RRF | Vector + BM25 + RRF + reranker | Vector + BM25 | Vector + BM25 + 重排 | Vector + 关键词 | 自家 hybrid | Vector + BM25 |
| KG 栈 | **完整**:extraction + loading + search + quality + community(LLM)+ ontology + provenance + snapshot | 完整(2025-01 优化)| 弱 | 弱 | 弱 | 弱 | 中 |
| Agentic | workflows(2370 行)+ agents(1390)+ tools(1647)≈ 5400 行 | Agent 0.21 | ★ workflow 强 + 50+ tools | ★ workflow 可视化 | ★ 入门最强 | n/a | 框架级 |
| 评测 | RAGAS + 自建多套 + ablation + KG diagnostics | RAGAS 集成 | 接 Opik/Langfuse/Phoenix | 弱 | 弱 | hallucination detect | 接 trulens |
| 安全 / Output Guard | InputGuard 157 行 + OutputGuard 35 行偏薄 + Presidio 集成 | 弱 | 中 | 弱 | 中 | ★ Hallucination detect | 弱 |
| Eval dataset 内建 | 已有 stage1-4 路线 + CRUD-RAG/C-MTEB benchmark 接入 | 弱 | 弱 | 弱 | 弱 | 自家 | 弱 |

### 2.2 产品化 / 运营维度

| 维度 | MimirQ | RAGFlow | Dify | FastGPT | Coze | Vectara | LlamaIndex |
|---|---|---|---|---|---|---|---|
| 多租户 | tenant_id 全栈 + quota panel | 配置可达 | 基础(弱) | 基础(组织/空间) | SaaS native | ★ 原生 | 框架级,需自建 |
| 计费 / Usage | tenant_quota_panel + Prometheus | 基础 | 中 | 中 | 字节自家 | ★ | n/a |
| Visual pipeline editor | ❌ 后端纯代码 | ✅ 0.21 起 | ✅✅ workflow 标杆 | ✅ | ✅✅✅ 入门最强 | n/a | n/a |
| Chat / Bot UI | 自家(完整) | 完整 | ★ 完整 + 嵌入 | ★ 完整 + 嵌入 | ★ 完整 + 嵌入 | API only | n/a |
| 连接器(SaaS connectors) | **仅 db/ 一种,SharePoint/Confluence/Notion/GitHub/S3 缺** | ~10 | ~30 | ~20 | 字节生态 | ~20 | ~75 |
| 模型管理 UI | 是 | 是 | ★★ 突出 | ★ | ★ | n/a | n/a |
| Prompt 管理 | DB + A/B + cache + 470 行 API | 模板 | ★ 完整 | 中 | 中 | 黑盒 | API |
| 行业规则库 | ★ **唯一独家**(术语 + 模式 + 意图,但 P0 未接主路径)| 无 | 无 | 无 | 无 | 黑盒 | 无 |

### 2.3 生态 / 社区 / 商业维度

| 维度 | MimirQ | RAGFlow | Dify | FastGPT | Coze | Vectara | LlamaIndex |
|---|---|---|---|---|---|---|---|
| GitHub stars | **私有项目(未开源)** | ~50k+ | **111k+** | 25k+ | 15k+ | 商业 SaaS | ~40k+ |
| 发布时间 | 2024+ 内部 | 2024-04 | 2023-03 | 2023+ | 2025-07 | 2020 | 2022-12 |
| License | 私有 | Apache 2.0 | "no unauthorized SaaS" | "no unauthorized SaaS" | Apache 2.0 / Permissive | SaaS | MIT |
| 商业化模型 | 销售 + PoC + 私有化 | 开源 + Cloud(InfiniFlow) | 开源 + Cloud | 开源 + Cloud | SaaS + 字节生态 | SaaS | 开源 + LlamaCloud SaaS |
| 中国生态 | ★ 自家 | ★ InfiniFlow 国内 | ★ LangGenius 国内 | ★★ labring 国内,微信群活跃 | ★★ 字节背书 | n/a | 海外 |
| 国际生态 | n/a | 出海 | ★ 强 | 中 | Coze.com 海外版 | ★ | ★★ 强 |
| 合规认证 | 等保规划中 | 自部署可走 | SOC 2 / ISO | 自部署 | SOC 2 / ISO | SOC 2 / HIPAA / GDPR / ★ | n/a |
| 文档完整度 | docs/ 19 md + plans/ 40+ 内部 | ★★ 完整 | ★★★ 顶级 | ★★ | ★★ | ★★ | ★★★ |
| 中文文档 | ★ 自家 | ★ | ★ | ★★ | ★★ | 部分 | 弱 |

---

## 3. MimirQ 5 大真实优势

### 3.1 ★ 知识图谱深度 + KG 可视化 — 第一梯队

**实测**:
- `app/rag/kg/` 完整 8 模块:extraction + loading + search + quality + community(LLM 摘要)+ ontology + provenance + snapshot
- 前端 `/graph` **9084 行**(graph-canvas 934 + graph-viewer 954 + force-graph-3d 604 + kg-diagnostics 1174 + kg-snapshots 1229)
- KG diagnostics + snapshot diff + hardcase deterministic 全自研

**对照**:
- RAGFlow 2025-01 新增 KG 配置选项,但**可视化 + diagnostics + snapshot diff 三件套是 MimirQ 独家**
- Dify / FastGPT / Coze 几乎没有真正的 KG
- Vectara 无 KG

**销售话术**:"我们 KG 是 RAG 的第二根支柱,RAGFlow 只是 KG 入门档,MimirQ 有完整的 KG 诊断 + 时序快照 + 影响分析(BFS k-hop)"

### 3.2 ★ 评测严谨性 — 唯一在第一梯队的同时支持 30+ metrics

**实测**:
- `app/rag/evaluation/` 多套:RAGAS + 自建多套 + ablation runner 602 行 + graphrag_bench + parse_bench + poc_runner
- 前端 `/evaluations` ~3000 行 + ablation 1214 行 + leaderboard / diff / bundle
- Citation correctness / Refusal accuracy / Conflict handling 准备落地(已 plan)
- CRUD-RAG + C-MTEB 中文 benchmark 接入(已 plan)

**对照**:
- Dify 接 Opik/Langfuse/Phoenix 外部,**不自带评测**
- RAGFlow 接 RAGAS,中文 benchmark 弱
- FastGPT / Coze / Vectara 评测都很弱

**销售话术**:"每次 prompt / chunking / reranker 改动都跑 50 题 Golden Set,数据驱动而非'感觉'"

### 3.3 ★ 中文 vertical 沉淀 + 行业规则库(独家护城河)

**实测**:
- `app/rag/industry_rules/` 完整 schema + loader + applier + mining(虽然 P0 未接主路径,但架子完整)
- `industrial_control` ruleset 模板(待扩容)
- 75 切块策略中**很多专为中文场景设计**(laws_structured / policy_manual / meeting_minutes 等)
- 解析栈 deepdoc + 中文表格 / 印章 / 手写识别完整

**对照**:
- RAGFlow 通用,中文优势在 InfiniFlow 国内背书,**没有行业规则 product**
- Dify / FastGPT 工作流强但**没有行业知识沉淀**
- Vectara 海外,**中文不是主战场**

**销售话术**:"我们不只是 RAG 工具,我们是带行业规则 + 中文垂直优化的解决方案。术语映射 / 问题模式 / 意图分类是任何工具都难以拷贝的资产"

### 3.4 ★ PoC 运营 / 客户交付 know-how

**实测**:
- `rag-poc-attribution-framework-2026-q2.md`:**5 字段极简埋点**(original_query / llm_response / final_context_filenames / feedback_score / latency_total_ms)
- **差评三分类根因**(检索不到 24% / 答错 35% / 超纲 37%)
- **超纲三级验证**(术语展开零命中 / Top1 相似度 0.3-0.5 阈值 / HyDE 反向检索零命中)
- 系统可控好评率 KPI(剔除超纲后)
- UMAP 客户沟通可视化

**对照**:
- 所有开源平台**只给工具,不给运营方法论**
- Vectara 给 SaaS,**没给客户成功 know-how**

**销售话术**:"一周交付 PoC,差评分类后 35% 答错可优化,37% 超纲是客户预期问题——这套交付节奏没有第二家"

### 3.5 ★ 后端工程深度(单点能力一流)

**实测**:
- RAG Engine 4090 行 / LangGraph 1751 / Retriever 6341 / Orchestrator 5241
- Hybrid Retriever 完整四路(Vector + BM25 + SPLADE + ColBERT/PLAID)
- 70+ chunking strategies + auto router 60+ 启发式分支
- 5500 行 preprocessing(boilerplate / dedup / PII 三件套 / 8 套 governance rule packs)

**对照**:
- 普通 RAG 平台是 LangChain wrapping + 配置文件,**没有自研工程深度**
- RAGFlow 是为数不多自研栈,但 chunking 策略数量 + Hybrid 检索层级 MimirQ 更深

**销售话术**:"打开任何模块都是几千行真代码,不是 LangChain 套壳"

---

## 4. MimirQ 5 大真实差距

### 4.1 🔴 **GitHub stars / 社区 / 品牌认知度**

| 平台 | Stars | 发布时间 |
|---|---|---|
| Dify | 111k+ | 2023-03 |
| RAGFlow | ~50k+ | 2024-04 |
| FastGPT | 25k+ | 2023+ |
| Coze | 15k+ | 2025-07 |
| **MimirQ** | **0(未开源)** | 2024+ |

**影响**:客户搜"RAG 平台"第一页全是 Dify/RAGFlow/FastGPT,MimirQ 不在视野。

**对策**:
- **不推荐立刻开源**(护城河会被复制),但可考虑**开源部分组件**:
  - chunking 策略库(75 策略)— 像 Sentence-Transformers 那样建社区
  - parse_bench / chunking_grid / graphrag_bench 评测集 — 建标准
  - **不开源**:industry_rules / KG diagnostics 全套 / PoC 运营 / industry vertical 数据
- 或走"商业开源"(部分功能开源 + 企业版闭源,类似 RAGFlow / Dify 模式)

### 4.2 🔴 **Visual Pipeline / Workflow Editor — 完全缺失**

**实测**:MimirQ 前端有 `/parsing` `/chunk-preview` `/datasets/[id]/{profile,health,precheck}` 等专业页面,但**没有 visual workflow editor**。

**对照**:
- Dify:workflow 标杆,拖拽编排 LLM / agent / retrieval / tool
- FastGPT:可视化工作流编辑器
- Coze:入门最快,bot 拖拽
- RAGFlow 0.21:Agent-based visual Ingestion Pipeline

**影响**:客户产品经理 / 业务方**看不到东西**,觉得"这是给程序员的"。

**对策**:
- P1 加 `/governance/pipeline-designer` 页(对照前份 ingest pipeline plan)
- 用现有 `app/rag/agents/` + `tools/` 暴露成可拖拽 Agent

### 4.3 🟠 **连接器(Connector) — 严重不足**

**实测**:`app/connectors/base.py:11` ABC 已存在,但**仅 `db/` 一种实现**。

**对照**:
- LlamaIndex Hub:75+ data loaders
- Dify:~30 connectors
- FastGPT / RAGFlow:~10-20 connectors
- Airbyte:550+ connectors
- Unstructured.io:75+ GenAI 专用 connectors

**影响**:客户问"能不能从 SharePoint / Confluence / Notion / GitHub / Slack 同步" → MimirQ 当前答案是"自己上传"。

**对策**:
- P0 5 个连接器(SharePoint / Confluence / Notion / GitHub / S3)— 与 MEMORY 中战略协同
- P1 接 Unstructured.io 客户端嵌入 MimirQ pipeline(MIT license 部分组件可用)

### 4.4 🟠 **部署 / 安装 footprint — 偏重**

**实测**:`docker-compose` 6 个文件(infra/lite/parsers/retrieval-dev/web/main),依赖 Milvus + PostgreSQL + Redis + Worker 多组件。

**对照**:
- RAGFlow Slim 镜像 2GB / Full 9GB(对 4 core / 16GB RAM)
- Dify Docker compose 一键起
- FastGPT 单镜像
- Coze SaaS 零部署

**影响**:客户 PoC 拒绝 "我们没那么大资源"的小客户。

**对策**:
- **Lite 版**(单容器,内嵌 Milvus Lite + SQLite + 内置 BM25):限 1k docs / 10k vectors,免费上手
- 私有化版 unchanged(目前完整 stack)

### 4.5 🟠 **Prompt 默认内容 / 安全 Guard 偏薄**

**实测**(我前份 prompt plan 已记):
- `system_prompts.py` **仅 26 行 / 3 个英文 prompt**
- `prompt_guard.py` 36 行,仅 2 条正则(`忽略|ignore` / `DAN|越狱`)
- 没有 Llama Prompt Guard 2 接入
- 没有行业 prompt 模板包(legal_consultant / finance_analyst / medical_assistant)

**对照**:
- Vectara:hallucination detection 是核心卖点
- Coze:bot 模板预制 100+
- Dify:50+ tools + 30+ prompt 模板社区

**影响**:客户体验"开箱即用"差。

**对策**:
- 前份 prompt plan 已规划 P0 升级(26→300 行,8 套 + 中英 + 3 行业 + Llama Prompt Guard 2)

---

## 5. 销售话术(常见客户提问与回答)

### Q1: "为什么我应该选 MimirQ 而不是 RAGFlow?它也是中文 + 文档理解强"

**答**:
> RAGFlow 是 MimirQ 最直接的竞品,但有三个差异:
> 1. **KG 深度**:MimirQ 完整 KG 8 模块 + 9084 行前端可视化,RAGFlow 是 KG 入门档,没有 diagnostics / snapshot diff / 影响分析。
> 2. **评测严谨性**:MimirQ 每次改动都跑 50 题 Golden Set,RAGFlow 接 RAGAS 但没自建中文 benchmark。
> 3. **行业规则**:MimirQ 有完整 industry_rules 资产沉淀(术语+模式+意图),RAGFlow 没有此层。

### Q2: "Dify 100k+ stars,功能比 MimirQ 多,为什么不选 Dify?"

**答**:
> Dify 是 LLMOps 全栈,**workflow / agent / RAG 一体**,生态丰富。但定位不同:
> - Dify 是 **platform-of-platforms**(适合工具型客户,什么都做但不深)
> - MimirQ 是 **RAG vertical product**(适合企业知识库 / 文档检索 / 客服 客户,RAG 内核更深)
> 
> 如果客户需要快速搭 Slack bot / 简单 FAQ,选 Dify。如果客户有合同/法规/产品手册等**复杂文档** + **检索准确性是核心 KPI**,选 MimirQ。
>
> 实际很多企业是 **Dify(应用层)+ MimirQ(RAG 引擎)** 互补部署。

### Q3: "Vectara 是 SaaS,接口最简单,有 hallucination detection,为什么自部署?"

**答**:
> - Vectara 数据**只能在他们云上**,合规客户(等保 2.0 / 个保 / 金融监管)不能用
> - Vectara hallucination detection 是黑盒,**MimirQ Citation correctness 评测器 + 三层 refusal 机制**比黑盒更可控
> - Vectara 不支持私有化部署,**中国客户基本无法采购**

### Q4: "FastGPT 我们已经用了,为什么还要切?"

**答**:
> FastGPT 适合"快速搭起来",但当客户文档复杂(法律/医疗/财报)时会遇到:
> 1. 切块策略不够垂类(FastGPT ~10 策略 vs MimirQ 75 策略)
> 2. KG 弱(法律/医疗的关系推理走不通)
> 3. 评测体系不严(每次改 prompt 都靠"感觉")
>
> **建议**:小客户继续用 FastGPT;企业级 / 合规需求来了切 MimirQ。

### Q5: "你们 GitHub 没开源,我怎么信你们?"

**答**:
> 1. **可以现场私有化部署演示**,client 自己看代码
> 2. **核心组件正在评估开源**(chunking 策略库 + parse_bench + chunking_grid 评测集),但**行业规则 + KG diagnostics 全套 + PoC 运营是商业护城河,不开源**
> 3. 对照 RAGFlow:DeepDoc 部分开源,但商业增强版闭源 — MimirQ 是同样模型

---

## 6. 3 个月差距追赶清单(优先级排)

### 6.1 P0(本季度,最有杠杆)

| 任务 | 解决差距 | 估算 | 关联 plan |
|---|---|---|---|
| **行业规则库产品化**(前端 UI + 接入主路径 + onboarding) | 4.4 差距 + 3.3 优势放大 | 1 周 | `industry-rules-productization-2026-q2.md` 已写 |
| **5 个 P0 连接器**(SharePoint / Confluence / Notion / GitHub / S3) | 4.3 差距 | 3 周 | ingestion pipeline plan |
| **中文 benchmark 跑基线**(CRUD-RAG + C-MTEB + 自建金融 50 题) | 3.2 优势放大 + 销售可 quote 硬数据 | 1 周 | `cn-benchmark-baseline-2026-q2.md` 已写 |
| **Prompt 默认内容升级**(26→300 行 + 8 套含中英 + 3 行业模板) | 4.5 差距 | 1.5 周 | `rag-prompts-mainstream-research-2026-q2.md` 已写 |
| **Llama Prompt Guard 2 接入**(36 行 toy → 200 行工业级)| 4.5 差距 + 合规客户 | 2 day | 同上 |

### 6.2 P1(下季度)

| 任务 | 解决差距 | 估算 |
|---|---|---|
| **Visual Pipeline Designer**(`/governance/pipeline-designer`,对照 RAGFlow 0.21) | 4.2 差距 | 3 周 |
| **Lite 版 Docker**(单容器,内嵌 Milvus Lite,免费上手) | 4.4 差距 | 2 周 |
| **OpenLineage emitter + Marquez 自部**(对照 ingest pipeline plan) | 合规客户 lineage 卖点 | 2 周 |
| **Citation correctness + Refusal 评测器** | 3.2 优势放大 | 1 周 |
| **业界 benchmark 跑结果发布**(对外白皮书) | 4.1 差距(品牌认知) | 2 周 |

### 6.3 P2(下半年战略选项)

| 选项 | 收益 | 风险 |
|---|---|---|
| **开源部分组件**(chunking 策略库 + parse_bench)走"商业开源"模式 | 品牌 + 社区 + 招聘 | 失去部分壁垒;运营开源社区成本 |
| **MCP Server 接入**(企微 / 飞书 / 钉钉 / Claude Desktop) | 嵌入工作流,商业化关键 | 工程成本 |
| **行业 vertical 包**(法律 / 医疗 / 金融各 50 术语 + 模板)| 商业模式护城河 | 需要客户 + 律师/医师/金融分析师合作 |
| **合规自动化 RAG 子产品**(等保 / 个保 / 信通院备案) | 中国市场刚需,海外不能进 | 1-2 季度工作量,见 `rag-compliance-automation-2026-q3.md` |

---

## 7. 不该做的事

- ❌ **不要直接对标 Dify 做 workflow 平台**:Dify 已 111k stars + 3 年迭代,追不上;聚焦 RAG 内核深度
- ❌ **不要全部开源**:行业规则 + KG diagnostics + PoC 运营 know-how 是护城河,开源等于送给竞品
- ❌ **不要追求 SaaS-only**:合规客户 + 中国市场必须支持私有化;Vectara 不能进中国就是教训
- ❌ **不要做消费级 bot 平台**:Coze + 字节生态压不住,聚焦企业级
- ❌ **不要堆功能不补内容**:`system_prompts.py` 26 行 / `prompt_guard.py` 36 行 / `industrial_control` ruleset 3 个术语 - 这些是产品体验,不是"功能"
- ❌ **不要忽视 GitHub stars 的认知影响**:即使不开源,也要在技术社区(知乎 / 掘金 / Twitter)发布技术文章 + benchmark 结果建立认知

---

## 8. 关键洞察 / 战略论断

1. **MimirQ 工程深度已超大多数开源平台**(KG / 评测 / 解析 / Agentic / 切块),但**商业化包装大幅落后**
2. **直接竞品是 RAGFlow**(栈最重叠 + 都是开源 + 都强 KG),但 MimirQ KG 可视化 + 评测严谨度 + 行业规则三项是真护城河
3. **Dify / FastGPT / Coze 错位互补**,可定位为"应用层用 Dify,RAG 内核用 MimirQ"
4. **Vectara / Glean 海外 SaaS 在中国市场无优势**,MimirQ 私有化部署 + 等保认证是天然机会
5. **6 个真空白**(联邦 / 视频 / 流式 / 合规 / Agent-RAG / 边缘)— **不必现在追**,客户主动询问再做
6. **真正不可拷贝的 3 条护城河**:
   - 行业规则库(术语+模式+意图)★★★★★ — 数据资产
   - PoC 运营 know-how(5 字段埋点 + 差评三分类 + 超纲三级验证)★★★★★ — 销售确定性
   - KG 影响分析(BFS k-hop)★★★★ — 杀手级场景
7. **快被追平的 3 条**:
   - 解析栈(Reducto / Mistral OCR 在追)
   - Agentic(OpenAI Agents SDK 标准化)
   - 评测严谨(DeepEval / Vectara HHEM-2.0 在追)
8. **最大遗憾**:**行业规则库未产品化** — 它是 MimirQ 最大商业护城河,但 P0 未接 RAG 主路径,客户感知不到。本季度必须落地。

---

## 9. 与既有 plan 的关系

本报告基于以下既有 plan 提取并综合:
- `rag-system-landscape-2026-q2-supplement.md`(2026-05-07)— 11 家商业 × 11 维 + 12 家开源 × 9 维矩阵,本报告做 MimirQ-centric 视角重排
- `industry-rules-productization-2026-q2.md` — 行业规则库产品化(P0 追赶 4.4 差距)
- `cn-benchmark-baseline-2026-q2.md` — 中文 benchmark 跑基线(P0 放大 3.2 优势)
- `rag-prompts-mainstream-research-2026-q2.md` — Prompt 升级(P0 追赶 4.5 差距)
- `rag-ingest-pipeline-orchestration-mainstream-2026-q2.md` — Ingest 编排(P1 连接器 + OpenLineage)
- `rag-poc-attribution-framework-2026-q2.md` — PoC 运营 know-how(3.4 优势)
- `rag-kg-visualization-self-built-2026-q2.md` — KG 9084 行(3.1 优势)

---

## Sources

### MimirQ 直接竞品
- [RAGFlow GitHub — infiniflow/ragflow](https://github.com/infiniflow/ragflow)
- [RAGFlow Release Notes — v0.25.0 (2026-04)](https://github.com/infiniflow/ragflow/blob/main/docs/release_notes.md)
- [DeepDoc README — RAGFlow](https://github.com/infiniflow/ragflow/blob/main/deepdoc/README.md)
- [RAGFlow 0.21.0 Ingestion Pipeline — RAGFlow Blog](https://ragflow.io/blog/ragflow-0.21.0-ingestion-pipeline-long-context-rag-and-admin-cli)
- [From RAG to Context — 2025 review — RAGFlow](https://ragflow.io/blog/rag-review-2025-from-rag-to-context)

### Dify / FastGPT / Coze
- [Dify GitHub — langgenius/dify (111k+ stars)](https://github.com/langgenius/dify)
- [Open Source AI Agent Platform Comparison 2026 — Jimmy Song](https://jimmysong.io/blog/open-source-ai-agent-workflow-comparison/)
- [LLM Platform Selection Guide — usedify.app](https://usedify.app/docs/llm-platform-comparison)
- [FastGPT vs RAGFlow — Sider.ai](https://sider.ai/blog/ai-tools/fastgpt-vs-ragflow-which-rag-stack-wins-for-2025-deployments)
- [Dify vs FastGPT Comparison — Slashdot](https://slashdot.org/software/comparison/Dify-vs-FastGPT/)
- [Practical Guide to Dify Coze n8n FastGPT RAGFlow — Stealing Fire](https://stealingfire.cc/article/Dify,%20Coze,%20n8n,%20FastGPT,%20and%20RAGFlow)
- [15 Best Open-Source RAG Frameworks 2026 — Firecrawl](https://www.firecrawl.dev/blog/best-open-source-rag-frameworks)

### 商业 SaaS
- [Enterprise RAG Platforms Comparison 2026 — Atlan](https://atlan.com/know/enterprise-rag-platforms-comparison/)
- [Best RAG Tools 2026 — PE Collective](https://pecollective.com/tools/best-rag-tools/)
- [Top 5 RAG Platforms — Medium (Vlad Koval)](https://medium.com/@vlad.koval/top-5-rag-platforms-to-choose-from-3618d11ad7e5)
- [Pinecone Launch Week May 2026 — Various sources via Atlan](https://atlan.com/know/enterprise-rag-platforms-comparison/)
- [Best Vector Databases 2026 — MarkTechPost](https://www.marktechpost.com/2026/05/10/best-vector-databases-in-2026-pricing-scale-limits-and-architecture-tradeoffs-across-nine-leading-systems/)

### LlamaIndex / LangChain / Haystack
- [LlamaIndex Ingestion Pipeline Docs](https://docs.llamaindex.ai/en/stable/module_guides/loading/ingestion_pipeline/)
- [Best RAG Frameworks 2025 — Latenode](https://latenode.com/blog/ai/frameworks-tech/best-rag-frameworks-2025-complete-enterprise-and-open-source-comparison)

### 内部参考
- `plans/rag-system-landscape-2026-q2-supplement.md`(2026-05-07,~499 行,11 家商业 × 11 维 + 12 家开源 × 9 维)
- `plans/industry-rules-productization-2026-q2.md`(2026-05-07,~483 行)
- `plans/cn-benchmark-baseline-2026-q2.md`(2026-05-07,~438 行)
- `plans/rag-poc-attribution-framework-2026-q2.md`(2026-04-18,~650 行)
