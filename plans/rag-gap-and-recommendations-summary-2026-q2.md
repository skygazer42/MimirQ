# MimirQ RAG 差距与建议 Executive Summary（2026 Q2）

> **30 份既有 deep-dive plan 的元层聚合**：把分散的 gap + 建议浓缩为 *工程团队 30 分钟可读完的决策视图*。本 summary 不重做对标 / 不写新代码 / 不重复学术综述，仅做 *去伪存真 + 优先级排序 + 可执行 checklist*。
>
> 创建日期：2026-05-08
> 受众：MimirQ 工程团队
> 失效日期：2026-11（业界变化快，6 月后重做）
>
> **TL;DR**：MimirQ 工程深度业界第一梯队，差距在 *产品化包装 + 中文 vertical 沉淀*；P0 立即做 2 件事，P1 按需启动 2 件，P2/P3 观望。**最大遗憾：行业规则库未产品化**。

---

## 0 阅读路径

| 章节 | 用途 | 谁读 |
|---|---|---|
| 第 1 章 | 方法论 | 全部 |
| 第 2 章 | 现状全景 | 工程 / PM |
| 第 3 章 | **5 大核心 GAP**（核心 1） | 工程 / 决策 |
| 第 4 章 | **5 大核心建议**（核心 2） | 工程 / 决策 |
| 第 5 章 | **真假 GAP 区分**（核心 3）| 工程 / 决策 |
| 第 6 章 | 6-12 月路线图 | PM / 决策 |
| 第 7 章 | 工程 checklist（直接 fork）| 工程 |
| 第 8 章 | 30+ plan 速查索引 | 全部 |

---

## 1 方法论

### 1.1 数据来源
- **30+ 份既有 plan**（`plans/*.md`，~17,500 行）的 *gap + 建议* 章节
- 12 份对标 plan：rag-deep-research(852) / rag-capability-gap(664) / rag-system-landscape-supplement(499) + 9 份 P0-P3 实施 plan
- 18 份 vertical 深化 plan：KG / 解析 / 切块 / 评测 / 安全 / Agentic / 可视化 / POC 等

### 1.2 不重复声明

| 已有 plan 覆盖的内容 | 本 summary 不重做 |
|---|---|
| 学术综述（50+ 篇论文） | ✅ 详见 `rag-deep-research-2026-q2.md` |
| 商业横向矩阵（11 家） | ✅ 详见 `rag-system-landscape-2026-q2-supplement.md` |
| 中文生态专章 | ✅ 详见同上第 4 章 |
| 9 份实施 plan 的 daily 拆解 | ✅ 仅引用，不复述 |

### 1.3 工程团队视角过滤标准
- 每条 gap 必须含 *代码路径 + 文件行数*
- 每条建议必须含 *工作量 + 启动条件*
- 真假 gap 必须从 *技术* 而非 *营销* 角度区分
- 优先级标记 P0/P1/P2/P3，无模糊形容词

---

## 2 MimirQ 现状全景

### 2.1 核心模块行数（关键文件 only）

| 路径 | 行数 | 角色 |
|---|---|---|
| `app/rag/engine.py` | 4,090 | RAGEngine 主路径 |
| `app/rag/pipelines/langgraph.py` | 1,751 | LangGraph 管线 |
| `app/rag/retriever.py` | 5,940 | HybridRetriever（Vector+BM25+SPLADE+ColBERT） |
| `app/rag/retrieval/orchestrator.py` | 5,188 | 检索编排 |
| `app/rag/kg/` 全栈 | ~12,000 | extraction+search+quality+community+ontology+provenance+snapshot |
| `app/parsing/parsers/` | ~14,000 | 25+ parser |
| `app/rag/chunking/strategies/` | ~17,700 | 70+ 切块策略 |
| `app/rag/workflows/` | 12 个 agent | crag/flare/self_rag/self_route/system_router/... |
| `app/rag/safety/` | ~1,200 | 7 个模块（input/output/llama/llm/prompt 都有） |
| `app/rag/evaluation/` | ~3,500 | 15+ 评测模块 |
| `app/rag/industry_rules/` | 309 | **后端 60% 已就位** |
| 前端 web/ | ~50,000+ | 多个 vertical 页面 |
| **合计** | **~110,000 行 backend** | |

### 2.2 横向定位（与开源最佳对比）

| 能力 | MimirQ | 开源最佳 | 商业最佳 | 自评梯队 |
|---|---|---|---|---|
| 解析栈 | deepdoc 5300 行 vision | RAGFlow（同源） | Reducto / Mistral OCR | **第一梯队** |
| 切块 | 70+ 策略 | LlamaIndex | — | **第一梯队** |
| 检索（Hybrid） | Vector+BM25+SPLADE+ColBERT | LangChain | Glean | **第一梯队** |
| KG 全栈 | extraction+community+ontology+snapshot | LangChain GraphRAG | — | **第一梯队** |
| Agentic | 12 个 workflow | LangGraph | OpenAI Agents SDK | 第一梯队 |
| 评测 | 计划 + 部分实现 | LangSmith / RAGAS | Vectara HHEM | 第二梯队 |
| Safety | input/output/llama/prompt 7 模块 | NeMo Guardrails | Lakera | 第二梯队 |
| 可视化 | 9084 行 /graph | Verba | Glean UI | **第一梯队** |
| **行业规则库** | 后端 60% / 前端 0% | — | — | **未产品化** |
| **中文 benchmark** | 未跑 | — | — | **缺基线** |
| **解析 API 化** | 内部用 | Marker | Reducto / Mistral | **未对外** |
| **POC 运营** | 5 字段 + 三分类 + UMAP | — | — | **第一梯队** |

### 2.3 一句话定位
> MimirQ 是 **工程深度业界第一梯队 + 商业化包装弱 + 中文 vertical 沉淀强** 的 B 端 RAG 系统。

---

## 3 5 大核心 GAP（核心章节 1）

### 3.1 GAP #1：行业规则库未产品化 ★★★★★（最大遗憾）

**现象**：
- 后端 60% 已就位（`app/api/v1/industry_rules.py` 145 行 + `app/rag/industry_rules/` schema/loader/applier/mining 309 行）
- **前端 UI 0%**（`web/app/governance/industry-rules/` 不存在）
- **Router 接入 0%**（`expand_query_terms` 已实现但未被任何 workflow 调用）
- 客户 onboarding / 评测闭环 / mining 审核流 全 0%

**量化差距**：
- 是垂直 SaaS 真正护城河（参照 `rag-poc-attribution-framework-2026-q2.md` 第 7.4 节）
- 客户场景 know-how 沉淀的载体
- 不可拷贝的 ★★★★★ 数据资产

**严重度**：★★★★★（投资人 / 销售视角）

**来源**：rag-poc-attribution-framework / rag-system-landscape supplement / industry-rules-productization

---

### 3.2 GAP #2：未跑过中文 benchmark 基线 ★★★★★

**现象**：
- 评测基建 80% 完备（graphrag_bench_runner / parse_bench / runners / reports / poc_runner / telemetry 全栈）
- **从未在 CRUD-RAG / C-MTEB-zh / Chinese FinQA 等公开 benchmark 上跑过基线**
- 销售 / PM 无可 quote 的硬数据
- "MimirQ 在金融场景多准确"无法回答

**量化差距**：
- 业界标杆：Mafin 2.5（PageIndex 驱动）98.7% on FinanceBench
- MimirQ：未知（最大问题）

**严重度**：★★★★★（销售 / 决策视角）

**来源**：rag-eval-dataset-deep-dive / rag-system-landscape supplement 第 7.1 P0-2 / cn-benchmark-baseline plan

---

### 3.3 GAP #3：解析栈未 API 化 ★★★★

**现象**：
- `app/deepdoc/vision/` ~5300 行（layout/ocr/recognizer/operators/postprocess/table 全栈）+ `app/parsing/parsers/deepdoc_parser.py` 269 行
- 内部 `app/api/v1/parsing.py` 1537 行（绑文档）
- **没有独立 OCR / 解析 API 对外销售**
- 工程深度不输 Reducto / Mistral OCR，但**未变现**

**量化差距**：
- Reducto $1-5/页（约 ¥7-35/页）已 SaaS 化
- Mistral OCR API 2026-Q2 GA，价格压低
- PageIndex Cloud OCR API 化
- MimirQ：未对外，**0 销售**

**严重度**：★★★★（商业视角）

**来源**：rag-system-landscape supplement 第 5.3 节 / deepdoc-api-productization plan

---

### 3.4 GAP #4：评测维度暴露偏少 ★★★★

**现象**：
- 后端评测栈 ~3500 行 + 15+ 模块（graphrag_bench / multihop / ragas / parse_bench / redteam_suite 等）
- **暴露 metric 仅 3 个**（业界 ≥ 30 个）
- LLM-Judge 框架未统一（`rag-evaluation-deep-dive-2026-q2.md` P0 已规划）
- Citation / Atomic Fact / Calibration 已规划未落
- 无统计显著性 / 置信区间 / effect size / Pareto 前沿（rag-ablation 已规划）

**量化差距**：
- 业界 ≥ 30 个 metric（DeepEval / TruLens / Phoenix / RAGAS）
- MimirQ 暴露 3 个

**严重度**：★★★★（信任 + 投资人视角）

**来源**：rag-evaluation-deep-dive / rag-ablation-deep-dive

---

### 3.5 GAP #5：Output Guard 偏薄 + 红队评测落地 ★★★

**现象**：
- `app/rag/safety/` 7 个模块（input_guard 157 / output_guard 123 / llama_guard / llm_guard / prompt_guard / retrieval_rail / rules）共 ~1200 行
- Output Guard 仅 123 行（业界标杆 NeMo Guardrails Output rail ≥ 500 行）
- redteam_suite 已存在但未跑红队基线
- Llama Guard 3 / Prompt Guard-86M / Presidio 中文扩展 都已规划未落

**量化差距**：
- 业界主流：NeMo Guardrails 5 rails / Lakera / Vectara HHEM-2.0
- MimirQ：基础栈在，但深度不够 + 未跑红队

**严重度**：★★★（合规客户必备）

**来源**：rag-safety-compliance-deep-dive

---

## 4 5 大核心建议（核心章节 2）

### 4.1 建议 #1（P0-1，**立即做**）：行业规则库产品化

**对应 GAP**：#1
**工作量**：~1210 行 / **1 周**
**核心动作**：
- 前端 UI 700 行（`web/app/governance/industry-rules/page.tsx` + 5 个组件）
- Router 接入 80 行（`workflows/query_rewrite.py` + `system_router.py` 注入 `expand_query_terms`）
- Onboarding 模板 150 行（`app/rag/industry_rules/templates/`）
- 评测闭环 200 行（`evaluation/poc_runner/industry_rules_eval.py`）
- Trace 可见性 80 行

**启动条件**：**无**（立即做）
**预期收益**：命中率 ≥60% / 改写正确率 ≥85% / with-rules vs without ≥+5pt accuracy
**详见**：`plans/industry-rules-productization-2026-q2.md`（483 行 daily 拆解）

---

### 4.2 建议 #2（P0-2，**立即做**）：跑中文 benchmark 基线

**对应 GAP**：#2
**工作量**：~350 行 / **1 周**
**核心动作**：
- 4 个 runner：`crud_rag_runner.py` / `cmteb_zh_runner.py` / `chinese_finqa_runner.py` / `cn_finance_self_runner.py`
- 1 份横向报告 generator：`reports/cn_benchmark_summary.py`
- 自建 5 篇 A 股年报 50 题（工行/茅台/比亚迪/中芯/宁德）
- Day 1-7 daily 拆解

**启动条件**：**无**（立即做）
**预期收益**：销售可 quote 硬数据 / 任何 RAG 改动跑回归基准 / 决策门槛 4 档
**详见**：`plans/cn-benchmark-baseline-2026-q2.md`（438 行）

---

### 4.3 建议 #3（P1-2，按需）：deepdoc API 化

**对应 GAP**：#3
**工作量**：~1500 行 / **4 周 MVP + 8 周 GA**
**核心动作**：
- `app/api/v1/ocr_service.py` 独立 endpoint group（不动 vision 内部 5300 行）
- Python + Node SDK
- 计费引擎 + 鉴权 + 限流
- `docs/ocr/` + 在线 playground
- 3 档解析模式（fast ¥3/accurate ¥6/table-focused ¥10）

**启动条件**：P0-2 OmniDocBench 验证 deepdoc ≥ Reducto / Mistral OCR + 商务确认
**预期收益**：6 月 ARR ¥100 万 + 引流到完整 RAG 产品
**详见**：`plans/deepdoc-api-productization-2026-q3.md`（425 行）

---

### 4.4 建议 #4（紧迫，**立即做**）：Output Guard 扩容 + 红队基线

**对应 GAP**：#5
**工作量**：~700 行 / **2 周**
**核心动作**：
- `app/rag/safety/output_guard.py` 123 → 200+ 行（接 Llama Guard 3 + Prompt Guard-86M）
- Presidio 中文扩展（PII 识别）
- `evaluation/redteam_suite.py` 跑 JailbreakBench / HarmBench / AdvBench 基线
- 目标：ASR（Attack Success Rate）< 5%
- False Positive 数学验证（5 个 90% 守卫叠加=41% 误报）

**启动条件**：**无**（立即做，合规客户必备）
**预期收益**：合规客户必备项 / ASR < 5% / 给客户 quote 的安全数据
**详见**：`plans/rag-safety-compliance-deep-dive-2026-q2.md`

---

### 4.5 建议 #5（**立即做**，零成本）：MCP server 注册 marketplace

**对应 GAP**：（未在 5 大 gap 但价值高）
**工作量**：~200 行 / **3 天**
**核心动作**：
- 新建 `app/mcp/server.py` 暴露 RAG tools（query / retrieve / kg_search / industry_rules_check）
- 注册到 Anthropic / OpenAI MCP marketplace
- 写 README 教程（如何在 Claude Desktop 接 MimirQ）

**启动条件**：**无**（零成本品牌曝光）
**预期收益**：免费品牌曝光 + 开发者获客 + 与 P1-2 deepdoc API 协同
**详见**：`plans/rag-agent-rag-boundary-2026-q4.md` 第 9 章"立即可做的小事"

---

## 5 真假 GAP 区分（核心章节 3）

### 5.1 看起来像 GAP 但实际不是（"营销 GAP"）

| "营销 GAP" | 真相 | 工程判断 |
|---|---|---|
| **Vectorless RAG**（PageIndex 28.9k stars） | 营销概念，本质是 LLM-augmented retrieval；MimirQ 已有 hierarchy 12 策略 + agentic_beam_search | **不追**，详见 `rag-pageindex-deep-dive` 第 7 章 |
| **Hallucination Detection**（Vectara HHEM-2.0） | = Citation + Atomic Fact，已在 `rag-evaluation` P0 计划 | **不追**，落地评测计划即可 |
| **Adaptive Routing**（多家鼓吹） | MimirQ 已有 system_router / self_route / 12 workflow，缺 *UI 透出* | **不追**，仅补可视化 |
| **Agentic AI**（OpenAI Agents SDK / NVIDIA AgentIQ） | MimirQ 已有 12 workflow agent + KG agentic_beam_search | **不追** |
| **Computer Use**（Anthropic / OpenAI Operator） | OSWorld 准确率 30-50%，离 95% 工业级远 | **观望 1-2 年**，仅做 MCP 雏形 |
| **FinanceBench 98.7%**（PageIndex Mafin 2.5） | Cloud OCR + 自家 router 数字，开源版达不到 | **不被吓到**，跑自己的中文 benchmark |
| **多模态（视频）RAG** | 90% 价值在会议视频文字化 + 文本 RAG，其他场景商业价值低 | **不全栈追**，仅会议 ASR + RAG |

### 5.2 看起来不大但实际是真 GAP（"被忽视的真 GAP"）

| "看起来小 GAP" | 真相 | 严重度 |
|---|---|---|
| **行业规则库前端 UI 缺失** | 是垂直 SaaS 真正护城河产品化关键，1 周搞定 | ★★★★★ |
| **中文 benchmark 基线缺失** | 是销售可 quote 的唯一硬数据，1 周搞定 | ★★★★★ |
| **MCP marketplace 未注册** | 免费品牌曝光，3 天搞定，但**全公司没人想到去做** | ★★★ |
| **Output Guard 偏薄** | 合规客户必备，2 周扩容 | ★★★ |
| **解析栈未对外卖** | 工程深度世界级，但**0 收入**，4 周可化为产品 | ★★★★ |
| **router UI 透出缺失** | adaptive routing 已实现但客户看不到 → 失去可信度卖点 | ★★★ |

### 5.3 区分原则（工程团队判断标准）

| 判断维度 | 真 GAP | 营销 GAP |
|---|---|---|
| 客户付费意愿 | ≥ 1 个客户明确说"必须有" | "听说很重要"无付费 |
| 工程量 vs 收益 | 1 周搞定 + ≥ ★★★ 影响 | ≥ 1 月开发 + 模糊收益 |
| 是否被业界 marketing 包装 | 多家鼓吹 + 学术热点 = 警惕 | — |
| MimirQ 现状 | 未实现 + 不可绕过 | 已实现或可绕过 |

---

## 6 6-12 月路线图

### 6.1 月度执行图

```
2026-05  [立即]  P0-1 行业规则库产品化（1 周 ~1210 行）
                P0-2 中文 benchmark 跑基线（1 周 ~350 行）
                MCP server 雏形 + marketplace 注册（3 天 ~200 行）
                Output Guard 扩容 + 红队基线（2 周 ~700 行）

2026-06  [立即]  P1-2 deepdoc API MVP 启动（4 周 MVP）
                统一 LLM-Judge 框架落地（rag-evaluation P0）
                Citation / Atomic Fact metric 上线
                ★ 月底 milestone：5 大 gap 中 3 个已闭环

2026-07          P1-2 deepdoc API GA + 销售启动
                P1-1 合规自动化客户验证（如 ≥ 2 律所付费意向）
                ★ 月底 milestone：deepdoc API 首位付费客户

2026-08          P1-1 合规自动化 Demo（如 P1 启动）
                /governance/industry-rules 客户 PoC 落地

2026-09          P2-2 政务部署评估（如政务客户出现）
                bench 季度回归（CRUD-RAG / C-MTEB-zh / 自建集）

2026-10          P2-3 联邦 RAG 评估（如金融多机构客户）

2026-11  [复盘]  ★ 6 个月节点：本 summary 失效，需重做
                重新评估业界变化 + 客户画像变化
                调整 P1-P3 优先级
```

### 6.2 每月 milestone 退出条件

| 月 | 必须达成 | 不达成则 |
|---|---|---|
| 2026-05 | P0-1/P0-2/MCP/Output Guard 4 件 | 优先级反思 |
| 2026-06 | deepdoc API MVP + 评测 metric 12+ | 调资源 |
| 2026-07 | deepdoc 首付费客户 | 复盘销售 |
| 2026-08 | 行业规则库 ≥ 1 客户 PoC | 复盘产品 |
| 2026-09 | 政务客户 OR 季度 benchmark 回归 | 重排 P2 |
| 2026-10 | 联邦客户 OR 维持现状 | 调整 P3 |
| 2026-11 | 全面复盘 | 写新 summary |

---

## 7 工程实施 checklist（直接 fork）

### 7.1 P0 立即可做（不依赖任何外部条件）

#### P0-1 Day 1：行业规则库前端
- [ ] 新建 `web/app/governance/industry-rules/page.tsx`
- [ ] 新建 `web/components/industry-rules/ruleset-selector.tsx`
- [ ] 接 `GET /api/v1/industry-rules/rulesets`
- [ ] 复用 `web/components/governance-profiles/` 的列表样式
- [ ] **详见** `plans/industry-rules-productization-2026-q2.md` Day 1-7

#### P0-2 Day 1：中文 benchmark 数据准备
- [ ] `git clone https://github.com/IAAR-Shanghai/CRUD_RAG`
- [ ] huggingface datasets 拉 `mteb/c-mteb`
- [ ] 选 5 篇 A 股年报 PDF（工行/茅台/比亚迪/中芯/宁德）
- [ ] 业务专家 + 标注外包 6h 标 50 题
- [ ] **详见** `plans/cn-benchmark-baseline-2026-q2.md` Day 1-7

#### MCP Day 1：3 天 200 行
- [ ] 新建 `app/mcp/server.py` 暴露 RAG tool
- [ ] 注册 Anthropic / OpenAI MCP marketplace
- [ ] 写 README 教程（Claude Desktop 接 MimirQ）
- [ ] **详见** `plans/rag-agent-rag-boundary-2026-q4.md` 第 9 章

#### Output Guard Day 1：扩容
- [ ] `app/rag/safety/output_guard.py` 123 → 200+ 行
- [ ] 接 Llama Guard 3
- [ ] 接 Prompt Guard-86M
- [ ] Presidio 中文 PII 扩展
- [ ] 跑 `evaluation/redteam_suite.py` JailbreakBench 基线
- [ ] **详见** `plans/rag-safety-compliance-deep-dive-2026-q2.md`

### 7.2 P0 周末验收

| 验收项 | 通过标准 |
|---|---|
| P0-1 端到端 demo | 用 industrial_control ruleset 改写 query 演示 |
| P0-2 HTML 报告 | 4 benchmark 横向对比报告生成 |
| MCP marketplace | 客户能在 Claude Desktop 接到 MimirQ |
| Output Guard ASR | < 5% on JailbreakBench |

### 7.3 P0 完成后下一步

按 6.1 路线图：6 月启动 P1-2 deepdoc API MVP。

---

## 8 30+ Plan 速查索引

### 8.1 按主题分组

| 主题 | Plan 文件 | 核心 gap（一句话） |
|---|---|---|
| **元层** | `rag-deep-research-2026-q2.md`（852）| 没把已实现能力用业界 benchmark 量化 |
| **元层** | `rag-capability-gap-2026-q2.md`（664）| 业界 gap 散落各章无横向矩阵 |
| **元层** | `rag-system-landscape-2026-q2-supplement.md`（499）| 商业 + 中文 + 护城河未集中 |
| **元层** | **本 summary** | 28 份 gap 未元层聚合 |
| **解析** | `rag-parsing-chunking-deep-dive-2026-q2.md`（665）| 未跑 OmniDocBench |
| **解析** | `rag-pre-poc-scanner-2026-q2.md`（577）| Pre-POC 工具未落地 |
| **切块** | `rag-context-expansion-rerank-2026-q2.md`| 整体评估 reranker 缺失 |
| **检索** | `rag-pageindex-deep-dive-2026-q2.md`（512）| 不必抄，仅借鉴接口设计 |
| **KG** | `rag-kg-deep-research-2026-q2.md`（713）| Agentic search 与影响分析未落 |
| **KG** | `rag-kg-snapshot-deep-dive-2026-q2.md`| 现状是"假快照"，影响分析是真护城河 |
| **KG** | `rag-kg-diagnostics-deep-dive-2026-q2.md`| 仅 5 metric 业界 ≥ 18 |
| **KG** | `rag-kg-visualization-self-built-2026-q2.md`| 9084 行已业界一线 |
| **Agentic** | `rag-agentic-reasoning-deep-dive-2026-q2.md`| Self-RAG / CRAG / FLARE 已规划未落 |
| **评测** | `rag-evaluation-deep-dive-2026-q2.md`| 暴露 3 metric / 业界 ≥ 30 |
| **评测** | `rag-eval-dataset-deep-dive-2026-q2.md`| 4 阶段评测集未落 |
| **评测** | `rag-ablation-deep-dive-2026-q2.md`| 38 参数缺统计显著性 |
| **安全** | `rag-safety-compliance-deep-dive-2026-q2.md`（617）| Output Guard 偏薄 + 未跑红队 |
| **可视化** | `rag-visualization-deep-dive-2026-q2.md`| OTel-first 埋点未落 |
| **POC** | `rag-poc-attribution-framework-2026-q2.md`（596）| **行业规则库未产品化（最大遗憾）** |
| **POC** | `rag-poc-to-mvp-delivery-2026-q2.md`（863）| 客户运营 know-how 沉淀缺 |
| **打标** | `rag-auto-tagging-services-2026-q2.md`| 完全无 LLM 路径 |
| **前端 11 份** | rag-*-frontend-deep-dive-* | 多个页面拆分需求 |
| **实施 P0-P3** | 9 份新 plan（2026-05-07） | 见 6.1 月度路线图 |

### 8.2 按优先级分组

| 优先级 | Plan |
|---|---|
| **P0 立即做** | industry-rules-productization / cn-benchmark-baseline / rag-safety-compliance（Output Guard）/ MCP 雏形（agent-rag-boundary 第 9 章） |
| **P1 按需** | deepdoc-api-productization / rag-compliance-automation |
| **P2 观望** | rag-edge-deployment / rag-federated / rag-video-rag |
| **P3 远期** | rag-streaming / rag-agent-rag-boundary（完整版） |

---

## 9 关键洞察（5 条）

1. **MimirQ 工程深度业界第一梯队**（与 RAGFlow / LangChain / LlamaIndex 同档），差距在 *社区运营 + 商业化包装*
2. **真正不可拷贝的 3 条护城河**：行业规则库、POC 运营 know-how、KG 影响分析。**最大遗憾：行业规则库未产品化**（建议 #1 推动）
3. **快被追平的 3 条护城河**：解析栈（Reducto / Mistral OCR）、Agentic（OpenAI Agents SDK）、评测严谨（DeepEval / HHEM-2.0）
4. **真假 GAP 区分**：Vectorless / Hallucination Detection / Adaptive Routing / Agentic AI / Computer Use 都是营销概念，MimirQ 不必追；行业规则库 / 中文 benchmark / MCP 注册 / Output Guard 才是真 GAP
5. **中文不是限制，是护城河**：等保 2.0 + 政务合规 + vertical 沉淀，海外 / 开源进不来。**别去和 Glean / Vectara 拼通用，去拼中文政务 / 金融 vertical**

---

## 10 立即可做（不需要任何审批）

按 7.1 P0 立即可做，**今天就能开始**：

```
Day 1 上午：P0-1 前端骨架 + P0-2 git clone CRUD-RAG
Day 1 下午：MCP server 雏形 + Output Guard 扩容启动
Day 2-7：按各 plan 的 daily 拆解执行
Day 7 晚：4 项 P0 同时验收
```

**4 项 P0 不互相阻塞，可全部并行启动。**
