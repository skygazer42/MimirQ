# MimirQ 全局能力总纲 — 12 领域代码实测 + 收敛优化地图

> 生成日期：2026-06-21
> 方法：12 个并行 Explore agent 直读真实代码（`wc -l` / `grep` 核实，不信旧记录），交叉核对 67 份既有 plan 结论是否仍成立。
> 定位：本文是**收敛地图**，不重复 67 份领域 plan，而是把它们对齐真实代码、给出跨领域优先级。MEMORY.md 已因 plan 碎片化超限——本文是那一层 meta。
> 代码规模：后端 ~32 万行 Python / 前端 ~30 万行 TS。

---

## 0. 执行摘要

**一句话结论**：MimirQ 工程深度在业界第一梯队，**普遍模式是「广度完整、深度不足、最后一公里集成断裂」**。系统性瓶颈不是缺功能，是大量能力**代码已写好却没接进主路径**（死代码 / stub / 默认关闭）。补「集成」比补「功能」ROI 高一个量级。

### 12 领域成熟度总览（对标 2025-2026 业界 SOTA）

| # | 领域 | 评分 | 核心规模（实测） | 一句话定性 |
|---|---|---|---|---|
| 1 | 文档解析 Parsing | **3.5** | ~23000 行（parsing+deepdoc+enrich） | 业界第一梯队，**未量化** OmniDocBench |
| 2 | 切块 Chunking | **3.5** | 78 策略 / ~20700 行 | 覆盖最全，3 个关键创新（Late Chunking/RAPTOR树/量化评分）实现度 65% |
| 3 | 检索 Retrieval/Embed/Rerank | **3.8** | retriever 9082 + orchestrator 6075 | 四路融合健全，embedding provider 4 真 + 4 空壳，默认模型落后 8 分 |
| 4 | 知识图谱 KG-RAG | **3.2** | ~19500 行 | indexer 级达标，**agentic search 仅框架**（plan_on_graph 65 行 stub） |
| 5 | Agentic/Workflows | **3.5** | ~14 类 workflow | Self-RAG/CRAG/FLARE 已落地，ReAct 无 CoT、Memory 三层 0% |
| 6 | 安全/合规/Guard | **2.5** ⚠️ | safety 575 行 | **最紧迫短板**：Llama/Prompt Guard 是 stub，retrieval rail 未集成，红队 0 |
| 7 | 评测/消融 | **2.5** ⚠️ | eval ~12300 行 / 37 metric | 工程骨架好，**无统计显著性**，LLM-Judge 无框架，中文 benchmark 占位 |
| 8 | 数据治理/反馈/打标 | **2.5** ⚠️ | ~8700 行 | 基建全，自动打标无 LLM 批量路径，反馈无自动 retrain，pre-poc 未集成 |
| 9 | RAG Engine 核心/LLM/Prompt | **3.8** | engine 4455 行 | 流式生产级，engine 单体过大需拆，**系统 prompt 仅 26 行** |
| 10 | 基础设施/连接器/部署 | **3.2** | API 384 端点 / config 1198 项 | 存储成熟，**连接器仅 2 个 DB catalog**，任务队列无持久保证 |
| 11 | 前端架构/页面/类型 | **3.5** | 264 组件 / ~30 万行 | **api-client 已拆分✅**，6 个页面>1500 行，useMutation 0% |
| 12 | 可视化/可观测/KG 前端 | **3.5** | ~34700 行 | 自研 Quad-tree LOD 是亮点，节点级 diff/agentic replay 缺 |

**加权均值 ≈ 3.3 / 5**。短板集中在 **6/7/8（安全·评测·治理，均 2.5）**——三者共同特征是「企业级 / 决策可信度」维度薄弱，恰是商业化要害。

---

## 1. 三大横切系统性洞察（比单领域结论更重要）

### 洞察 A：最后一公里集成断裂 — 死代码 / stub / 默认关闭遍地

这是全项目**最高 ROI 的修复方向**。能力都写了，就差「接上主路径」：

| 能力 | 代码状态 | 集成状态 | 修复成本 |
|---|---|---|---|
| 行业规则库 `expand_query_terms` | ✅ 实现（17 行） | ❌ **workflows/retrieval 零调用**（已 grep 确认） | 0.5 天 |
| 行业规则库前端 UI | ❌ 不存在 | ❌ 后端 API 完整但无界面 | 3 天 |
| SPLADE 稀疏检索 | ✅ 实现（sparse.py 575 行） | ⚠️ 默认 `SPARSE_ENABLED=false` | 0.5 天 |
| Pre-POC scanner | ✅ 实现（~352 行） | ❌ 未接入入库流程，无质量门控 | 3 天 |
| LLM 自动打标 `llm_tagger` | ✅ 实现（214 行） | ⚠️ 仅单文档 API，未进 processor 批量 | 8 天 |
| Retrieval rail（防间接注入） | 🟡 47 行骨架 | ❌ 未集成进 orchestrator | 4 天 |
| Presidio PII | ✅ 实现（132 行） | ⚠️ 是否真在 in/out 路径调用未确认 | 1 天 |
| Llama Guard 3 / Prompt Guard | ❌ stub（55/36 行正则玩具） | ❌ 无真实 LLM 推理 | 5 天 |
| 反馈硬负例 → re-train | ✅ 导出 JSONL | ❌ 无自动触发重索引 | 5 天 |

> **结论**：把这一列「接上」，比开发任何新功能都划算。第 4 节 P0 的一半都来自这里。

### 洞察 B：「未量化」是决策的总开关

解析栈 23000 行、切块 78 策略、检索四路融合——**全是经验堆出来的，没有一个跑过业界基准**。后果：
- 不知道自研 DeepDoc vs MinerU 2.5 谁好 → 无法定架构、无法定价
- 不知道 fixed vs semantic 切块谁优（Vectara 反直觉结论无法验证）
- 评测**无统计显著性** → 任何「A 比 B 好 3%」都可能是噪声（FloTorch 54% 假提升陷阱）

> **结论**：量化基线（OmniDocBench / chunking_grid / 中文 CRUD-RAG / 红队 ASR / 统计显著性）是所有后续优化的**前置条件**。先建标尺，再堆功能。

### 洞察 C：三大短板（2.5 分）= 企业商业化的三道门槛

安全 / 评测 / 治理同分 2.5，且都卡在「企业客户买单的关键维度」：
- **安全**：合规审计要的 Lineage / RTBF 级联 / chunk 级权限 / 红队 ASR 全缺 → 等保、金融客户进不来
- **评测**：没有统计严谨性 → 销售无法 quote 硬数据，POC 无法证明价值
- **治理**：反馈不闭环 → 客户「越用越准」的承诺兑现不了

> **结论**：工程深度的护城河已经够深，**差距在「能不能证明 + 能不能合规」**，不在「功能够不够多」。

---

## 2. 真实代码 vs MEMORY.md 旧记录（重要纠正）

实测发现 memory 多处已过时，**后续决策以本表为准**：

| 项 | MEMORY.md 旧记录 | 实测真实值 | 状态 |
|---|---|---|---|
| `web/lib/api-client.ts` | 4261 行，计划拆分 | **132 行索引 + lib/api/ 9 模块 6072 行** | ✅ **已完成拆分** |
| `web/types/index.ts` | 3008 行混杂 | **30 行索引** | ✅ **已重构** |
| `output_guard.py` | 35 行偏薄 | **123 行**（含 Llama Guard 3 集成位） | 🟡 已扩容但仍不足 200 |
| `retriever.py` | 5940 行 | **9082 行** | 实际更大 |
| `engine.py` | 4090 行 | **4455 行** | 单体过大需拆 |
| `orchestrator.py` | 5188 行 | **6075 行** | — |
| Embedding providers | 4 个 | **4 真实现 + 4 空壳（voyage/cohere/jina/bedrock 各 10 行）** | 空壳需补 |
| 切块策略 | 70+ | **78 个**（late_chunking_jina 798 行是 stub） | — |
| 前端 ingestion page | 3720 行需拆 | **6096 行**（拆分计划已搁置，改双模式） | 反而变大 |
| Agentic workflows | P0 待建 | **Self-RAG/CRAG/FLARE/Critic/routing 均已实现** | 大量已落地 |

> 行动：实测后应**精简 MEMORY.md**（已超 24.4KB 限制），把过时条目删除，本文作为单一事实源。

---

## 3. 12 领域能力矩阵（每领域：真实规模 / 关键缺口 / 已有 plan 状态）

> 每领域仅列**最关键 2-3 项缺口**与对应 plan 核实结论。完整 P0/P1/P2 见各领域原 plan。

### 1️⃣ 文档解析 Parsing — 3.5
- **真实规模**：32 parser（25 完整 + 7 占位）/ deepdoc vision 3995 行 / enrich 26 模块 5015 行 / processor.py 单体 6514 行
- **关键缺口**：① 未跑 OmniDocBench（最致命）② MinerU 版本不确定（可能停在 2.0 AGPL）③ ColPali/video/audio 仅占位 ④ 表格/公式/代码未进独立 chunk_type 索引
- **plan 核实**：`rag-parsing-chunking-deep-dive` 仍成立；deepdoc 系列大部分已落地，唯独 baseline benchmark 未执行

### 2️⃣ 切块 Chunking — 3.5
- **真实规模**：78 策略 / strategies 20690 行；semantic（min floor✅）/ parent_child（两层✅）/ metadata 三字段✅
- **关键缺口**：① `late_chunking_jina.py` 798 行**几乎全是 NotImplementedError** ② min chunk floor 仅 2-3 策略有 ③ RAPTOR 仅 leaf 层 ④ Context Cliff @2500 无监测 ⑤ 6 维量化评分缺
- **plan 核实**：`rag-chunk-preview` 设计成立但 3 个关键实现滞后

### 3️⃣ 检索 Retrieval / Embedding / Rerank — 3.8（最高）
- **真实规模**：retriever 9082 + orchestrator 6075 + reranker 工厂 13 种 + 向量后端 6 个（Milvus 1405 行主力）
- **关键缺口**：① embedding provider 4 空壳（voyage/cohere/jina/bedrock）② 默认模型 text-embedding-3-small 落后 SOTA 8 分 ③ SPLADE 默认关 ④ alpha 参数多处不一致（0.5 vs 0.6）⑤ 无 adaptive complexity routing
- **plan 核实**：`rag-hybrid-search-tuning` / `rag-embedding-models` 分析高度准确，落地滞后

### 4️⃣ 知识图谱 KG-RAG — 3.2
- **真实规模**：extraction 5562 + search 3769 + community 597（label propagation 确定性）+ snapshot 202 + api 4310
- **关键缺口**：① `plan_on_graph.py`(65) + `agentic_beam_search.py`(215) **仅框架无反馈闭环** ② snapshot 仅 count diff 非结构 diff ③ relation 22 predicate 硬编码无学习 ④ 多跳无反思/自纠正
- **plan 核实**：`rag-kg-deep-research` 方向验证正确；hyperedge/oneke 未实现；snapshot plan 仅 40% 落地

### 5️⃣ Agentic / Workflows / Reasoning — 3.5
- **真实规模**：langgraph.py 1849（LangGraph 1.0+ Functional API）+ 14 类 workflow + web_search 264 + MCP tools 1244
- **关键缺口**：① ReAct(435 行)无 LLM CoT 集成 ② FLARE 无段落级重写 ③ complexity_classifier 仅 28 行正则 ④ **Memory 三层（episodic/semantic/procedural）0% 实现** ⑤ multi-agent 无 supervisor
- **plan 核实**：`rag-agentic-reasoning` 80% 覆盖；`rag-agentic-memory` 0% 实现

### 6️⃣ 安全 / 合规 / Guard / 行业规则库 — 2.5 ⚠️
- **真实规模**：input_guard 157（8 类攻击✅）/ output_guard 123 / llama_guard 55（stub）/ prompt_guard 36（stub）/ industry_rules 后端 311 行
- **关键缺口**：① Llama Guard 3 / Prompt Guard-86M **无真实推理** ② retrieval rail 47 行未集成（RAG 最独特的间接注入威胁无防护）③ **行业规则库前端 0% + router 0%（已 grep 确认 expand_query_terms 零调用）** ④ chunk 级权限缺 ⑤ RTBF 级联 / Lineage API / 红队 ASR 全缺
- **plan 核实**：`rag-safety-compliance` P0 5 项仅落地 1；`industry-rules-productization` 后端 60% / 前端 0% / 集成 0%

### 7️⃣ 评测 / 消融 / Benchmark — 2.5 ⚠️
- **真实规模**：evaluation 12312 行 / 37 metric（10 RAGAS + 27 确定性）/ ablation CLI 602 + nightly 485 / 前端 ~3000 行
- **关键缺口**：① **统计显著性完全缺失**（无 t-test/Bootstrap CI/Cohen's d）② LLM-Judge 是 ad-hoc 无框架（无校准/方差/缓存/一致性）③ 中文 benchmark `datasets/` 仅占位 ④ 消融无 Pareto/敏感度/自动调参 ⑤ 前端无网格创建 UI（仅 CLI）
- **plan 核实**：`rag-evaluation` / `rag-ablation` 规划详尽，统计严谨性实现缺位

### 8️⃣ 数据治理 / 预处理 / 反馈 / 打标 — 2.5 ⚠️
- **真实规模**：cleaning 829 + processor 642 + governance_profiles 720（继承链✅）+ feedback_loop 407 + pre_poc_scanner 352
- **关键缺口**：① 自动打标 LLM 路径未批量化（llm_tagger 仅单文档 API）② 反馈无自动 re-train（dispatcher 明确 pull/batch，无触发）③ pre-poc scanner 未集成入库门控 ④ 无 multi-provider 兜底
- **plan 核实**：`governance-profiles-extension` 95% 完成；`rag-feedback-loop` 30%；`rag-auto-tagging` 25%；`rag-pre-poc-scanner` 工具 70% 但未集成

### 9️⃣ RAG Engine 核心 / LLM / Prompt / Memory — 3.8
- **真实规模**：engine 4455（stream_chat 主逻辑 3800+）/ llm factory 336（fallback chain✅）/ memory short 553 + long 765 / middleware 6 层
- **关键缺口**：① **engine.py 单体 4455 行需拆**（retrieval/generation/safety 三分）② 系统 prompt 仅 26 行（无 XML/refusal/conflict）③ prompt_guard 玩具级 ④ Claude/Gemini 无原生适配（仅 OpenAI-compatible）
- **plan 核实**：`rag-prompts-mainstream` 可立即执行；`rag-agentic-memory` 基建就绪缺核心；`rag-streaming` 架构已支持（P3 按需）

### 🔟 基础设施 / 连接器 / 存储 / 部署 — 3.2
- **真实规模**：向量后端 6 个 3299 行 / 对象存储 942（S3 族）/ 任务 arq 1858 / config 8215 行 1198 项 / API 384 端点 / Helm+3 档 Docker
- **关键缺口**：① **连接器仅 2 个 DB catalog**（无 SharePoint/Confluence/Notion/Jira/Slack 原生实现，仅 API 端点）② 任务队列 arq 无持久保证、parse/chunk 无 stage 重试、无 DLQ ③ config 1198 项无 preset 分层 ④ PGVector 仅 7 行 stub
- **plan 核实**：`rag-ingest-pipeline-orchestration` Section 2.2 六大缺口与代码 100% 吻合；`deployment-tier-matrix` 缺 runtime validator

### 1️⃣1️⃣ 前端架构 / 页面 / 类型 — 3.5
- **真实规模**：264 组件 / api-client **已拆✅**（132 索引 + 6072 分散）/ types index **已重构✅**（30 行）/ useQuery ~60% / i18n next-intl 成熟
- **关键缺口**：① 6 个 page-client >1500 行（ingestion 6096 / reports 3002 / feedback 2169）② **useMutation 0%**（仍 .then() 链）③ chunk-preview/parsing 缺 StrategyComparisonGrid ④ 无 Error Boundary 整体策略 ⑤ 状态管理无顶层（prop drilling）
- **plan 核实**：ingestion 拆分计划**已主动搁置**（改双模式，决策合理）；chunk-preview/parsing 对比框架 P0 未开始

### 1️⃣2️⃣ 可视化 / 可观测 / KG 前端 — 3.5
- **真实规模**：KG 可视化 18727 行 / force-graph 2D+3D / 自研 Quad-tree LOD 328 行 / observability 651 / vector-nebula 453
- **关键缺口**：① 节点/边精确 diff 缺（snapshot 仅聚合）② Louvain/社区折叠/agentic replay 未实现 ③ KG 本体质量 12 metric 缺 ④ per-case 子图未联动 /graph ⑤ 无 OTel 深度埋点
- **plan 核实**：`rag-kg-visualization` P0 部分落地（LOD✅，replay❌）；`rag-kg-snapshot` 40%；`rag-kg-diagnostics` 60%

---

## 4. 全局收敛优先级（跨领域 ROI 排序）

> 这是本文核心产出：把 12 领域的 P0 拉通，按 **ROI（影响 ÷ 成本）** 重排成一张可执行清单。分三波。

### 🌊 第一波 — 集成断裂修复（最高 ROI，~2 周，代码都写好了只差接线）

| # | 任务 | 领域 | 成本 | 收益 |
|---|---|---|---|---|
| 1 | 行业规则库 `expand_query_terms` 注入 query_rewrite workflow + system_router | 安全/治理 | 0.5 天 | 激活唯一难迁移护城河 |
| 2 | 行业规则库前端 UI（3 Tab + mining 审核 + preview） | 安全/前端 | 3 天 | 让护城河可见可运营 |
| 3 | SPLADE 默认开启评估（或加入 precision_first preset） | 检索 | 0.5 天 | 免费召回提升 |
| 4 | Pre-POC scanner 接入入库流程 + 质量门控 | 治理 | 3 天 | 坏数据预检，对接 precheck 前端 |
| 5 | Presidio PII 真实调用链验证（in/out 路径） | 安全 | 1 天 | 确认合规基线非空壳 |
| 6 | LLM 自动打标接入 processor 批量路径 | 治理 | 8 天 | 主题/分类标签，召回 +5-15% |

### 🌊 第二波 — 量化基线建设（决策前置条件，~3 周，先建标尺）

| # | 任务 | 领域 | 成本 | 收益 |
|---|---|---|---|---|
| 7 | 统计显著性框架（t-test/Bootstrap CI/Cohen's d）接入 regression diff | 评测 | 1 周 | 所有消融结论可信，杜绝假提升 |
| 8 | OmniDocBench runner（DeepDoc vs MinerU 2.5 vs Docling） | 解析 | 4 天 | 定架构、定价的依据 |
| 9 | chunking_grid 6 维量化评分 runner | 切块 | 1 周 | 验证 fixed vs semantic |
| 10 | 中文 benchmark 基线（CRUD-RAG + 自建金融 50 题） | 评测 | 1 周 | 销售可 quote 硬数据 |
| 11 | MinerU 版本确认 + 若 2.0 升级 2.5 | 解析 | 2 天 | 免费质量提升、去 AGPL |

### 🌊 第三波 — 最紧迫短板补齐（企业商业化门槛，~6 周）

| # | 任务 | 领域 | 成本 | 收益 |
|---|---|---|---|---|
| 12 | Output Guard 扩容 200 行 + Llama Guard 3 真实化（vLLM） | 安全 | 1 周 | 输出侧合规可证 |
| 13 | Prompt Guard-86M 本地部署（CPU） | 安全 | 2 天 | 注入防护二层 |
| 14 | Retrieval rail 真集成（chunk 级过滤 + 间接注入检测） | 安全 | 4 天 | RAG 独有威胁防护 |
| 15 | LLM-Judge 框架（G-Eval + Self-Consistency + 校准 + 缓存） | 评测 | 2 周 | 评测业界标配 |
| 16 | engine.py 拆分（retrieval/generation/safety 三分 + 核心<500 行） | Engine | 1 周 | 可维护性、并行开发 |
| 17 | 红队评测套件（JailbreakBench + 自建中文 200 条 + ASR 报表） | 安全 | 4 天 | ASR<5% 可量化 |
| 18 | 反馈闭环自动 re-train（arq 触发重索引） | 治理 | 5 天 | 「越用越准」可兑现 |
| 19 | 系统 prompt 扩至 50+ 行（Prompt-as-Code + XML + refusal） | Engine | 3 天 | 答案质量、拒答策略 |

### 🌊 后续（P1/P2，季度级，各领域原 plan 已详述）
- KG agentic search 完整化（ToG/PoG ~800 行）、snapshot 结构 diff、连接器生态前 5、Memory 三层、useMutation 全量迁移、可视化 agentic replay、Claude 原生 provider、RTBF 级联 + Lineage API、合规自动化、DeepDoc API 化……

---

## 5. 三大真护城河 vs 三大最紧迫短板

### 🏰 三大护城河（应优先产品化，海外/开源难迁移）
1. **行业规则库**（术语/模式/意图）— 唯一跨企业难复制的数据资产，**但目前是死代码**（第一波 #1#2 激活）
2. **解析栈深度**（23000 行 + 自研 deepdoc vision）— 对标 Reducto/Mistral OCR，且中文+可私有化部署是海外进不来的，**但未量化**（第二波 #8 证明）
3. **KG 影响分析 + agentic**（金融反欺诈/供应链/合规穿透杀手级）— 框架在，**但 agentic 是 stub**（后续波次完整化）

### 🚨 三大最紧迫短板（卡企业商业化）
1. **安全合规 2.5** — Llama/Prompt Guard 是 stub、retrieval rail 未集成、红队 0、Lineage/RTBF 缺 → 等保/金融客户门槛
2. **评测无统计严谨 2.5** — 无显著性 → 任何提升都可能是噪声，销售无硬数据
3. **反馈不闭环 2.5** — 无自动 re-train → 「越用越准」承诺空转

---

## 6. 落地路线图建议

```
2026 Q2 剩余（6-7 月）
├─ 第一波 集成修复（2 周）   ← 立即可启动，无依赖，ROI 最高
└─ 第二波 量化基线（3 周）   ← 与第一波部分并行

2026 Q3（7-9 月）
├─ 第三波 短板补齐（6 周）   ← 安全/评测/治理三短板
└─ KG agentic + connector 前 5

2026 Q4
└─ P1/P2 战略项（合规自动化 / DeepDoc API / Memory 三层 / 多模态）
```

### 立即可做（无依赖、当天能动手）
- 行业规则库 router 注入（0.5 天）→ 激活护城河
- SPLADE 默认开启评估（0.5 天）
- Presidio 真实调用验证（1 天）
- MinerU 版本确认（0.5 天）

### 决策门槛
- OmniDocBench 出分后：DeepDoc < MinerU 2.5 → 切默认；≥ → 留用并对外宣传量化优势
- 中文 benchmark 出分后：with-rules vs without ≥ +5pt → 印证行业规则库价值，加大投入
- 红队 ASR > 5% → 阻断 P3 合规/边缘部署商业化

---

## 7. 与既有 67 份 plan 的关系

本文**不取代**任何领域 plan，而是它们的**索引 + 优先级仲裁 + 真实代码校准层**。各领域执行细节仍查原 plan：
- 解析→`rag-parsing-chunking-deep-dive` / `deepdoc-*`
- 安全→`rag-safety-compliance-deep-dive` / `industry-rules-productization`
- 评测→`rag-evaluation-deep-dive` / `rag-ablation-deep-dive` / `cn-benchmark-baseline`
- 其余见 §3 各领域「plan 核实」行

> 建议：把本文设为 plans 入口，MEMORY.md 仅保留一行指向本文，删除已被本文校准的过时条目，缓解 24.4KB 超限。

---

*生成方式：12 并行 Explore agent 直读真实代码（已 wc/grep 交叉验证关键行数与 expand_query_terms 零调用）。评分为对标业界 SOTA 的相对值，非绝对质量分。*
