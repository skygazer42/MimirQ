# Agentic / Reasoning RAG 深度调研报告（2026 Q2）

> **编写日期**：2026-04-18
> **定位**：前 4 份 plan 的 **Agentic 推理专项深化**。KG 专项已讲 ToG/PoG（KG 侧 agentic），本专项聚焦**通用 Agentic RAG 与 Reasoning RAG**——Self-RAG / CRAG streaming / FLARE / A-RAG / RAG-Critic / Plan-Execute / ReAct / Reflexion / Multi-Agent / ToT / System 1/2 / SoK POMDP。
> **核心问题**：LLM 何时、以何种粒度、用什么工具去"自主决策检索"？如何在**准确性、成本、延迟、可解释性**四维做 Pareto 最优？
> **交叉引用**：`rag-capability-gap-2026-q2.md` §8；`rag-deep-research-2026-q2.md` §11-13；`rag-kg-deep-research-2026-q2.md`（KG 侧 agentic）；`rag-eval-dataset-deep-dive-2026-q2.md`（decomposition F1 / 路由评测）。
>
> `feat/backend` 当前只吸收其中对外可复用的 RAG 能力：检索编排、工具调用、评测与可观测性。多 agent 问答编排、research-debate、聊天型记忆增强不纳入当前分支交付范围。

---

## 1. Agentic RAG 分类法（5 Pattern）

按 **Agentic RAG Survey**（arXiv:2501.09136）与 **SoK**（arXiv:2603.07379），Agentic RAG 可沿 4 维展开，实践落地的 **5 种 pattern**：

| # | Pattern | 核心机制 | 代表方法 |
|---|---|---|---|
| 1 | **Reflection** | 自我批评 + 自我修正 | Self-RAG / Reflexion / RAG-Critic |
| 2 | **Planning** | 任务分解 + 子目标规划 | Plan-and-Solve / Plan-Execute / Plan-on-Graph |
| 3 | **Tool Use** | 动态调用外部工具 | ReAct / Toolformer / Function calling |
| 4 | **Multi-Agent** | 角色分工 + 消息协作 | AutoGen GroupChat / CrewAI Crew / LangGraph Supervisor |
| 5 | **Memory** | 长短期记忆 + episodic | MemGPT / Mem0 / LangGraph Checkpointer |

**SoK 的 POMDP 形式化**：把 agentic 检索-生成循环建模为**有限视界部分可观测马尔可夫决策过程**，显式建模 control policy 与 state transition，识别 4 大系统性风险：
- **Compounding hallucination propagation**：错误逐跳放大
- **Memory poisoning**：恶意样本污染长期记忆
- **Retrieval misalignment**：检索器与生成器目标不一致
- **Cascading tool-execution vulnerability**：工具链错误级联

**设计寓意**：Agentic RAG 不是 "堆 agent"，而是**每层加 agent 前都要问"它会引入哪类 cascading risk"**。

---

## 2. Self-RAG 完整落地

**论文**：Self-RAG（Asai et al., NeurIPS 2023，https://github.com/AkariAsai/self-rag）

### 2.1 核心机制：Reflection Tokens

单模型 + 4 类特殊 token：

| Token | 作用 | 何时生成 |
|---|---|---|
| `[Retrieve]` / `[No Retrieve]` | 是否需要检索 | 每个 segment 开头 |
| `[IsRel]` | 文档是否相关 | 对每个检索文档 |
| `[IsSup]` | 答案是否被支持 | 生成后 |
| `[IsUse]` | 整体有用度 | 生成结束 |

### 2.2 训练与推理

- 训练 **Critic** + **Generator** 两个模型（均扩展特殊 token 的词表）
- 推理时 Generator 原位产出 reflection tokens
- vLLM 推理注意：**需显式设置 `skip_special_tokens=False`** 才能保留 reflection token；旧版 vLLM 不支持 SamplingParam 级别设置
- 完整流程：LangGraph 节点编排"retrieve → grade → generate → self-critique → rewrite query if needed"

### 2.3 2025 工程趋势

**LangChain/LangGraph Self-Reflective RAG 指南**（2024-2025）已成主流参考：
- grade 每个检索文档相关性
- 若全部无关 → transform query → 重检索
- 若仍无关 → **CRAG 式 web search 兜底**

**与 Self-RAG 的差异**：LangGraph 实现多用 **prompt-based** reflection（不扩词表，靠指令让 LLM 输出 JSON critique），工程成本低、可 plug-and-play。

### 2.4 我方现状对标

- `app/rag/workflows/evaluator_optimizer.py`（430 行）—— **是 Self-RAG 的 generalize 版本**（评估器 + 优化器循环）
- `app/rag/evaluation/evidence_retrieve_gate.py` —— retrieval gating
- `app/rag/retrieval/evidence_gap.py` —— evidence 缺口检测
- `app/rag/policy/must_recall*.py` —— 检索义务判定

**Gap**：缺明确的 **4 类 reflection token 或其 prompt-based 等价物**完整闭环；`evaluator_optimizer` 更像 Reflexion 风格（反思-重试），不是 Self-RAG 风格（per-segment decision）。

### 2.5 建议

- **P0** `workflows/self_rag.py`（~300 行）：prompt-based reflection，复用 `evaluator_optimizer` 基类，输出 JSON 的 4 类 critique（`need_retrieval` / `is_relevant` / `is_supported` / `is_useful`）
- **P1** 微调专用小模型（~3B 参数）做 Critic，降低 per-query 成本
- **P2** vLLM 适配 skip_special_tokens

---

## 3. CRAG + Streaming + Web Search Fallback

**论文**：Corrective Retrieval Augmented Generation（Yan et al., 2024）

### 3.1 核心机制

- **Retrieval Evaluator**（T5-large fine-tuned）→ 文档 3 分类：
  - **Correct**（高置信）：直接用
  - **Incorrect**（全部低于下阈值）：**丢弃全部检索 → 走 web search**
  - **Ambiguous**（混合）：**refined 内部 + web 补充**

### 3.2 2025 工程实践（Serper/Tavily 兜底）

典型 2025 生产栈：
1. vector retrieval（AlloyDB/Chroma/Meilisearch）
2. re-ranker 做 sufficiency 判定
3. evaluator 打分 → Correct/Ambiguous/Incorrect
4. **Incorrect → Serper API 或 Tavily API 做 web search**
5. guardrails 注入（防幻觉）
6. streaming generation

**关键工程点**：CRAG 的 web fallback **必须接入 streaming 主路径**，否则用户体验回退成"等待-再等待"。

### 3.3 CRAG × Self-RAG 互补

- **CRAG**：修正**证据**（输入侧）
- **Self-RAG**：修正**推理**（输出侧）
- 生产典型做法（LangGraph）：CRAG 作 retrieve 节点的 wrapper + Self-RAG 式反思在 generate 节点后

### 3.4 我方现状对标

- `app/rag/retrieval/evidence_gap.py` —— 有 gap 检测
- `app/rag/policy/must_recall_auto.py` —— 自动判定
- `app/rag/tools/{simple_kb_search,mcp_client,mcp_tools}.py` —— **仅 KB 检索 + MCP，无 web search tool**
- **无 streaming 主路径对接的 CRAG 闭环**

### 3.5 建议

- **P0** `tools/web_search.py`（~200 行）：Serper + Tavily + Brave 三路 fallback；支持 `query_with_site_filter`、`freshness`、`lang`、`region`
- **P0** `workflows/crag_streaming.py`（~250 行）：接 `retrieval/orchestrator.py` 的 streaming 流，incorrect → web_search → 继续生成而非重走
- **P1** Retrieval evaluator：可先 prompt-based，后续替换 T5-large 或 BGE-reranker-v2 的相关性分
- **P1** CRAG metrics：记录每 query 的 evaluator 决策分布（correct/ambig/incorrect 比例）

**预计收益**：对"知识库外"类问题，answer correctness 从 ~40% 提升至 ~70%（CRAG 论文数据 + Serper 兜底经验）。

---

## 4. FLARE：Token-Level 主动再检索

**论文**：FLARE（Jiang et al., EMNLP 2023）

### 4.1 核心机制

- 生成过程中 **per-token 计算置信度**（logit margin / entropy）
- 若低于阈值 → 丢弃当前 sentence → 用该 sentence 作为 query 触发再检索 → 重生成

### 4.2 工程难点

- 要么需要 **logprob 访问**（OpenAI API 支持 `logprobs=True`，Claude/Gemini 视 API 版本而定）
- 要么用"生成一段后 LLM 自评置信"的 prompt-based 变体（慢但通用）

### 4.3 我方现状对标

`app/rag/core/confidence.py` 有置信度工具 —— 基础在；需接入生成主路径。

### 4.4 建议

- **P2** `workflows/flare.py`（~200 行）：prompt-based 版本先行；按段落 granularity 触发再检索
- 不推荐 P0/P1：ROI 相对 Self-RAG/CRAG 较低，且 token-level 实现对 streaming UX 有破坏（"生成到一半突然重来"）

---

## 5. A-RAG：Hierarchical Retrieval Interfaces

**论文**：A-RAG（arXiv:2602.03442，Feb 2026）

### 5.1 核心机制

向 agent **暴露 3 种粒度的检索工具**（而非单一 "search" tool）：

| Tool | 输入 | 输出 | 何时用 |
|---|---|---|---|
| `keyword_search` | 关键词 / 实体 | 精确匹配文档 | 查 ID / 术语 |
| `semantic_search` | 自然语言 | top-k 语义段 | 通常问答 |
| `chunk_read` | chunk_id | 完整 chunk 原文 | 深挖某段 |

Agent 通过 function calling 自主选择粒度。

### 5.2 量化收益

- 在多个 open-domain QA 基准上 **outperform baselines with comparable or lower retrieved tokens**
- 成本比单一 "dump top-10 chunks" 的基线低

### 5.3 我方现状对标

- `app/rag/tools/simple_kb_search.py`（77 行）—— **单一语义检索 tool**
- `app/rag/tools/mcp_tools.py`（940 行）—— MCP tool registry，有扩展骨架

### 5.4 建议

- **P0** `tools/hierarchical_retrieval_tools.py`（~300 行）：
  ```python
  @tool
  async def keyword_search(query: str, tenant: str) -> list[Chunk]: ...
  @tool
  async def semantic_search(query: str, tenant: str, top_k: int = 5) -> list[Chunk]: ...
  @tool
  async def chunk_read(chunk_id: str, tenant: str) -> Chunk: ...
  ```
- Agent prompt 中**显式描述每个 tool 的 cost 与使用场景**（参考 A-RAG prompt template）
- 在 `workflows/react.py` 的 ReActWorkflow 中首先注册这 3 个工具
- **预计收益**：复杂 query 上 token 消耗降 20–40%，accuracy 持平或提升

---

## 6. Critic / Self-Reasoning 家族

| 方法 | 年份 | 核心 |
|---|---|---|
| **RAG-Critic** | ACL 2025 | 自动批评家引导的 agentic workflow |
| **Self-Reasoning RAG** | AAAI 2025 | 改进 RALM 自推理能力 |
| **Interact-RAG** | 2026 | LLM 从 **passive query issuer** 升级为 **active manipulator**（调 retriever 参数） |
| **EviOmni** | 2026 | RL 学习抽取 rational evidence |
| **RAGShaper** | 2026 | auto data synthesis 诱导 agentic skills |
| **TreePS-RAG** | 2026 | tree-based process supervision |
| **RAGCap-Bench** | 2026 | agentic 中间任务能力评测 |

### 6.1 我方现状对标

- `app/rag/workflows/evaluator_optimizer.py`（430 行）—— 评估器-优化器循环
- `app/rag/agents/multi_agent.py`（405 行）—— 多 agent 骨架
- **无独立 critic agent**；critic 逻辑混在 evaluator_optimizer 内

### 6.2 建议

- **P1** `workflows/critic.py`（~300 行）：独立 critic agent，产出结构化 critique（claim-level faithfulness、citation missing、style violation）
- **P2** `evaluation/ragshaper_synthesizer.py`：按 RAGShaper 思路合成 agentic 训练样本
- **P3** RL 策略（EviOmni、TreePS-RAG）：观察论文代码放出后再跟进

---

## 7. Plan-and-Solve / ReAct / Reflexion 对比

| Pattern | 核心循环 | 强项 | 弱项 |
|---|---|---|---|
| **ReAct** | Thought → Action → Observation 循环 | 工具调用 + 透明 | 每步 LLM 调用贵、循环发散 |
| **Plan-and-Solve** | 先整体规划 → 再逐步执行 | 结构化、可中断、易检查 | 计划错误难中途纠正 |
| **Reflexion** | Act → Eval → Reflect → Retry | 自修正能力强 | 成本高（多轮 LLM） |
| **Plan-Execute**（LangGraph） | Planner + Executor + Re-Planner | 生产化、checkpoint 友好 | 复杂 |

### 7.1 我方现状对标

- `app/rag/workflows/react.py`（345 行）—— **class Tool + ReActWorkflow**；有完整实现
- `app/rag/workflows/planner_worker.py`（362 行）—— Plan-and-Execute 风格
- `app/rag/workflows/evaluator_optimizer.py`（430 行）—— Reflexion 风格

**总结**：骨架齐全。但：
- ReAct 的 Tool 只注册了 `simple_kb_search`（见 §5）
- planner_worker 的 plan 粒度能否子目标级可追溯未确认
- evaluator_optimizer 的 reflect 是否落审计未确认

### 7.2 建议

- **P0**（与 §5 联动）：把 `hierarchical_retrieval_tools` + `web_search` 注册进 ReActWorkflow
- **P1** Planner 输出子目标树 → `trace_schema.py` 记录每子目标状态（pending/done/failed），前端可视化
- **P1** Reflexion 上限：每 query 最多 **2 次反思**，避免 cascading cost

---

## 8. Multi-Agent：AutoGen / CrewAI / LangGraph 对比（2026）

### 8.1 三大框架定位

| 框架 | 设计哲学 | 强项 | 弱项 |
|---|---|---|---|
| **LangGraph** | Graph-based 状态机 | **MCP 一等公民** / LangSmith / per-node streaming / checkpoint time-travel | 学习曲线高 |
| **CrewAI** | Role-based crew | 原型快 / 1.8s 平均延迟 | 无内置 checkpoint / 粗粒度控制 |
| **AutoGen / AG2** | Event-driven / GroupChat | 对话式协作 / 适合 research debate | **高 token 成本**（4 agent × 5 rounds = 20 LLM calls） |

### 8.2 关键 benchmark（2026）

| 指标 | LangGraph | CrewAI | AutoGen |
|---|---|---|---|
| Task success rate | **87%**（最高） | 82% | — |
| 平均延迟 | 中 | **1.8s**（最快） | 高 |
| 生产就绪度 | **最高** | 中 | 中 |
| MCP 深度集成 | **一等公民**（streaming） | 函数式 | 函数式 |
| 企业合规（SOC2/GDPR） | ✅ | 🟡 in progress | ✅ |
| 状态持久化 | ✅ checkpoint | Task output 串行 | In-memory |

### 8.3 生产 RAG 选型（2026 共识）

> **LangGraph emerges as the strongest choice for multi-agent RAG in production.** MCP 深、观测强、支持 checkpoint + per-node streaming；CrewAI 为快速原型；AutoGen 适合 research / debate。

### 8.4 我方现状对标

- `app/rag/pipelines/langgraph.py`（1751 行）—— **已经是 LangGraph 主路径** ✅
- `app/rag/checkpointer/{memory,sqlite,time_travel}.py` —— checkpoint 完整
- `app/rag/agents/multi_agent.py`（405 行）—— 多 agent 骨架
- `app/rag/tools/mcp_{client,tools}.py`（574+940 行）—— **MCP 栈完备** ✅
- `app/rag/middleware/{agent_logging,context_injection,dynamic_model,dynamic_prompt,error_handler,tool_logging}.py` —— 中间件齐

**结论**：**架构选型与业界 2026 共识一致**（LangGraph + MCP + checkpoint）。优势明显。

### 8.5 建议

- 当前分支**不继续推进** multi-agent Supervisor / research-debate 这类问答编排强化。
- 优先保留 LangGraph + MCP 作为可插拔 orchestration 底座，服务检索工具调用、追踪与可观测。
- **P2** CrewAI 式 role-based 不推荐迁入（与现有 LangGraph 路线冲突）

---

## 9. Tree-of-Thoughts / Graph-of-Thoughts 推理

| 方法 | 核心 | 2026 状态 |
|---|---|---|
| **Chain-of-Thought (CoT)** | 线性推理链 | 已常态 |
| **Self-Consistency** | 多 CoT 投票 | 贵但鲁棒 |
| **Tree-of-Thoughts (ToT)** | 树搜索推理状态 | 复杂推理 SOTA |
| **Graph-of-Thoughts (GoT)** | 图结构思考（支持合并） | 学术 |
| **Algorithm of Thoughts** | 组合算法 + LLM | 学术 |

### 9.1 实战建议

ToT/GoT 在通用 RAG 中 **ROI 不高**（成本 5×+，收益仅在难题上显著）。建议仅对下列场景开启：
- 复杂多跳推理题（HotpotQA 级）
- 法律 / 医疗诊断辅助
- 代码调试 agent

### 9.2 我方现状对标

无 ToT/GoT 专门实现。`workflows/parallelization.py`（298 行）提供并行推理 primitive，可作 ToT 分支展开基础。

### 9.3 建议

- **P3** `workflows/tot.py`：仅对指定 query_type（`multi_hop_hard`）开启；配合 `parallelization` 做 k 分支 + LLM vote
- **现阶段不优先**

---

## 10. Reasoning RAG：System 1 vs System 2（arXiv:2506.10408）

### 10.1 两种范式

| 范式 | 描述 | 代表 |
|---|---|---|
| **System 1（predefined reasoning）** | 固定 pipeline，按规则执行 | Advanced RAG / Modular RAG |
| **System 2（agentic reasoning）** | 决策嵌入检索过程，**何时/何物/如何检索** | Self-RAG / CRAG / A-RAG / ToG / Plan-on-Graph |

### 10.2 切换标准

- 简单事实（factual） → System 1（快）
- 多跳 / 歧义 / 需澄清 → System 2（准）
- 业务通常 **System 1 cover 80% 流量，System 2 做 20% 长尾**

### 10.3 我方现状对标

- 缺 **显式的 System 1 / System 2 router**
- `workflows/routing.py`（246 行）已有框架，但未见复杂度感知路由

### 10.4 建议

- **P0**（与评测集专项联动）：`policy/complexity_classifier.py` + `workflows/system_router.py`，对齐 Adaptive-RAG / RAGRouter-Bench（轻量分类器 TF-IDF+SVM 可达 93% F1）
- simple → System 1（小 model + 单路检索）
- multi_hop → System 2（LLM-as-searcher / Self-RAG / CRAG）
- unanswerable → 拒答 + 可选 web search

---

## 11. SoK Agentic RAG POMDP 视角与风险模型

**论文**：SoK Agentic RAG（arXiv:2603.07379, Mar 2026）—— 把 agentic 循环形式化为 POMDP。

### 11.1 四大系统性风险

| 风险 | 描述 | 我方如何防 |
|---|---|---|
| **Compounding hallucination** | 错误跨步放大 | 每步 faithfulness 门控 + 早停 |
| **Memory poisoning** | 恶意样本污染 long_term memory | memory write 权限最小化 + diff 审计 |
| **Retrieval misalignment** | retriever 目标 ≠ 生成目标 | RAG-Critic 定期对齐 |
| **Cascading tool vuln** | 工具链错误级联 | Tool sandbox + 每步 recovery 策略 |

### 11.2 开放研究方向

- **Stable adaptive retrieval**（稳定性 vs 自适应权衡）
- **Cost-aware orchestration**（成本感知编排）
- **Formal trajectory evaluation**（形式化轨迹评测）
- **Oversight mechanisms**（监督机制）

### 11.3 我方现状对标

- `app/rag/memory/{short_term,long_term}.py`（552+765 行）—— memory 完整
- `app/rag/middleware/error_handler.py` —— 错误处理
- `app/rag/evaluation/{hard_negative_mining,replay_capture,test_generator}.py` —— 回归数据

**Gap**：**没有专门的 agent 对抗 / 红队测试**；memory poisoning / cascading tool 风险无针对性 regression。

### 11.4 建议

- **P1** `evaluation/agent_redteam.py`：agent 专用对抗测试集，包含 memory poisoning / tool hijack / cascading error 三类
- **P1** `workflows/` 每个 agent 节点加 **最大迭代次数** + **早停 faithfulness 阈值**（防止 cascading）
- **P2** Cost-aware orchestration：每步记录 tokens + latency，超预算强制退化到 System 1

---

## 12. Agentic RAG 评测

### 12.1 业界基准

- **RAGCap-Bench**（2026）：agentic RAG 中间任务能力，构建 LLM 典型错误 taxonomy
- **AgenticRAG-Survey**（GitHub asinghcsu）：论文与基准集合
- **Awesome-RAG-Reasoning**（EMNLP 2025，DavidZWZ）：推理 RAG 资源

### 12.2 中间指标（evaluator_optimizer 视角）

| 指标 | 含义 |
|---|---|
| **Plan correctness** | 计划子目标是否正确分解 |
| **Tool selection accuracy** | 工具选择是否匹配任务 |
| **Intermediate factuality** | 每步输出是否符合事实 |
| **Reflection trigger precision** | 反思触发是否合理（不过度反思） |
| **Termination correctness** | 何时停止 / 何时继续 |

### 12.3 我方现状对标

- `app/rag/evaluation/agent_evals.py` —— 有基础
- 与评测集专项的 **decomposition F1** 配合，可构建完整 agentic eval
- **Gap**：未跑 RAGCap-Bench；无独立 agent regression suite

### 12.4 建议

- **P1** `evaluation/ragcap_bench_runner.py`：对齐 RAGCap-Bench，定期评我方 5 个 pattern 的中间能力
- **P1** 评测集专项 Stage 3 加入 agentic 样本，与 decomposition F1 联合

---

## 13. 我方 agentic 栈现状对标总表

| 能力 | 业界对标 | 本系统位置 | 行数 | 状态 |
|---|---|---|---|---|
| LangGraph 主路径 | LangGraph 2026 最强 | `pipelines/langgraph.py` | 1751 | 🟢 |
| ReAct | 经典 | `workflows/react.py` | 345 | 🟢 |
| Plan-Execute | 主流 | `workflows/planner_worker.py` | 362 | 🟢 |
| Evaluator-Optimizer | Reflexion 近亲 | `workflows/evaluator_optimizer.py` | 430 | 🟢 |
| Parallelization | 并行推理 primitive | `workflows/parallelization.py` | 298 | 🟢 |
| Routing | 路由 | `workflows/routing.py` | 246 | 🟡 复杂度路由缺 |
| Chain | 串联 | `workflows/chain.py` | 167 | 🟢 |
| Multi-Agent | Supervisor / Worker | `agents/multi_agent.py` | 405 | 🟡 supervisor pattern 待接入 |
| Prebuilt agents | 预置 | `agents/prebuilt.py` | 397 | 🟢 |
| RAG agent | 主 agent | `agents/rag_agent.py` | 584 | 🟢 |
| MCP 集成 | 2026 标准 | `tools/mcp_{client,tools}.py` | 574+940 | 🟢 |
| KB 检索 tool | 基础 | `tools/simple_kb_search.py` | 77 | 🟡 仅语义，缺 keyword/chunk-read |
| Web search tool | CRAG 必需 | — | — | 🔴 缺 |
| Self-RAG | NeurIPS 2023 | — | — | 🔴 缺独立 workflow |
| CRAG streaming | 2024 | — | — | 🔴 缺完整闭环 |
| FLARE | EMNLP 2023 | `core/confidence.py` 基础 | — | 🔴 未形成 workflow |
| Critic 独立 agent | ACL 2025 | (在 eval_opt 内) | — | 🟡 未独立 |
| Complexity router | Adaptive-RAG | (在 intent_router) | — | 🟡 不显式 |
| Memory 长短期 | MemGPT/Mem0 | `memory/{short,long}_term.py` | 552+765 | 🟢 |
| Checkpoint | LangGraph | `checkpointer/{memory,sqlite,time_travel}.py` | — | 🟢 |
| Middleware 栈 | 生产必需 | `middleware/*.py` 6 文件 | — | 🟢 |
| Trace schema | 可观测 | `trace_schema.py` | 145 | 🟢 |
| Agent eval | RAGCap-Bench | `evaluation/agent_evals.py` | — | 🟡 未跑业界基准 |

**总结**：**框架基础设施在业界第一梯队**（LangGraph + MCP + Checkpoint + Middleware），**策略层缺关键论文落地**（Self-RAG / CRAG streaming / A-RAG hierarchical tools / Web search / Complexity router）。

---

## 14. Gap + 建议（按优先级）

### 🥇 P0（1–3 周，必做）

| # | 建议 | 预计收益 | 引用 |
|---|---|---|---|
| 1 | `tools/web_search.py`（Serper + Tavily + Brave） | CRAG 闭环必要条件；外部问题 accuracy +30pp | CRAG 2024 |
| 2 | `tools/hierarchical_retrieval_tools.py`（keyword + semantic + chunk-read） | token -20~40%，agent 决策更细 | A-RAG arXiv:2602.03442 |
| 3 | `workflows/crag_streaming.py` | incorrect 路径可恢复；answer 准确率显著升 | CRAG + LangGraph 2025 |
| 4 | `workflows/self_rag.py`（prompt-based reflection） | reflection 闭环；faithfulness +10–15pp | Self-RAG NeurIPS 2023 |
| 5 | `policy/complexity_classifier.py` + `workflows/system_router.py` | System 1/2 分流，simple 流量成本 -70% | Adaptive-RAG / RAGRouter-Bench |

### 🥈 P1（1–2 月，补强）

| # | 建议 | 理由 |
|---|---|---|
| 6 | ~~`workflows/critic.py` 独立 critic agent~~ | 当前分支不继续扩展 answer-agent critique loop |
| 7 | `evaluation/agent_redteam.py` | memory poisoning / tool hijack / cascading 防护 |
| 8 | ~~Multi-agent Supervisor pattern~~ | 当前分支不做多 agent 问答编排 |
| 9 | Cost-aware orchestration（每步 token/latency 门控） | 防止 runaway cost |
| 10 | ~~`evaluation/ragcap_bench_runner.py`~~ | 当前分支不做 agent QA 基准对齐 |

### 🥉 P2（2–6 月，长期）

| # | 建议 |
|---|---|
| 11 | `workflows/flare.py`（prompt-based FLARE） |
| 12 | ~~`evaluation/ragshaper_synthesizer.py`~~（当前分支不做 agent 问答训练数据合成） |
| 13 | ~~Fine-tuned Critic 小模型~~（当前分支不做 critic 专项优化） |
| 14 | `workflows/tot.py`（ToT 仅限难题开关） |

### 观望 / 延后

- RL-based EviOmni / TreePS-RAG（等开源代码）
- GroupChat / CrewAI 迁入（与 LangGraph 路线冲突）
- ToT/GoT 通用化（ROI 不足）

---

## 15. 参考资料

### Agentic RAG 核心论文
- [Self-RAG (arXiv:2310.11511)](https://selfrag.github.io/) NeurIPS 2023
- [CRAG (arXiv:2401.15884)](https://arxiv.org/abs/2401.15884) 2024
- [FLARE (arXiv:2305.06983)](https://arxiv.org/abs/2305.06983) EMNLP 2023
- [A-RAG (arXiv:2602.03442)](https://arxiv.org/abs/2602.03442) Feb 2026
- [Adaptive-RAG (arXiv:2403.14403)](https://arxiv.org/abs/2403.14403) NAACL 2024
- RAG-Critic (ACL 2025)
- Self-Reasoning RAG (AAAI 2025)
- [Interact-RAG / RAGShaper / EviOmni / TreePS-RAG / RAGCap-Bench (2026)](https://github.com/DavidZWZ/Awesome-RAG-Reasoning)

### Survey
- [Agentic RAG Survey (arXiv:2501.09136)](https://arxiv.org/abs/2501.09136) Jan 2025
- [SoK Agentic RAG (arXiv:2603.07379)](https://arxiv.org/abs/2603.07379) Mar 2026
- [Reasoning RAG System 1/2 (arXiv:2506.10408)](https://arxiv.org/abs/2506.10408) Jun 2025
- [Awesome-RAG-Reasoning](https://github.com/DavidZWZ/Awesome-RAG-Reasoning) EMNLP 2025
- [AgenticRAG-Survey](https://github.com/asinghcsu/AgenticRAG-Survey)

### Multi-Agent 框架
- [LangGraph](https://langchain-ai.github.io/langgraph/)
- [AutoGen / AG2](https://github.com/microsoft/autogen)
- [CrewAI](https://www.crewai.com/)
- [LangGraph vs CrewAI vs AutoGen 2026 比较](https://medium.com/data-science-collective/langgraph-vs-crewai-vs-autogen-which-agent-framework-should-you-actually-use-in-2026-b8b2c84f1229)

### 工程实践
- [Self-Reflective RAG with LangGraph](https://blog.langchain.com/agentic-rag-with-langgraph/)
- [CRAG + LangGraph DataCamp](https://www.datacamp.com/tutorial/corrective-rag-crag)
- [AkariAsai/self-rag GitHub](https://github.com/AkariAsai/self-rag)
- [Self-Reflection + Serper fallback (2025)](https://pawan-kumar94.medium.com/beyond-basic-rag-implementing-self-reflection-rag-with-serper-search-fallback-ac7608b6fdb1)

### 本项目相关 plan
- `plans/rag-capability-gap-2026-q2.md` §8
- `plans/rag-deep-research-2026-q2.md` §11-13
- `plans/rag-kg-deep-research-2026-q2.md`（KG 侧 agentic）
- `plans/rag-eval-dataset-deep-dive-2026-q2.md`（decomposition F1 + 复杂度 router 评测）

---

## 结论

1. **架构层我方已在业界第一梯队**（LangGraph 1751 行主管线 + MCP 1500+ 行 + checkpointer + middleware），**不需要重构**。
2. **策略层的 P0 五项全部训练-free，3 周可交付**：`web_search` + `hierarchical_retrieval_tools` + `crag_streaming` + `self_rag` + `complexity_classifier/system_router`。
3. **核心洞察**：**Agentic RAG 的生产化不在于用多复杂的 agent，而在于 System 1/2 分流 + Cost-aware orchestration**。80% 流量用 System 1 省钱，20% 长尾用 System 2 保准。
4. **风险前置**：SoK POMDP 指出的 4 类系统性风险（cascading hallucination / memory poisoning / retrieval misalignment / cascading tool vuln）必须在 P1 加红队测试。

**下一步**：P0 五项各自拆 ~300–500 行实施 plan 单独执行。

---

> **可独立拆的子 plan**：
> - `plans/agentic-web-search-tool.md`
> - `plans/agentic-hierarchical-retrieval-tools.md`（A-RAG）
> - `plans/agentic-crag-streaming.md`
> - `plans/agentic-self-rag.md`
> - `plans/agentic-system-router.md`（Adaptive-RAG / complexity classifier）
> - `plans/agentic-critic-agent.md`
> - `plans/agentic-redteam-suite.md`
> - `plans/agentic-ragcap-bench.md`

---

## 15. 2026-05-01 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口.

已落地:
- Self-RAG / CRAG / Web Search / hierarchical retrieval 已拆进真实后端路径:`app/rag/workflows/self_rag.py`,`app/rag/workflows/crag_streaming.py`,`app/rag/tools/web_search.py`,`app/rag/tools/hierarchical_retrieval_tools.py`.
- Adaptive-RAG 路由已落地:`app/rag/policy/complexity_classifier.py` 与 `app/rag/workflows/system_router.py` 支撑查询复杂度判定、系统路由和降级.
- 主要行为已有测试覆盖:`tests/test_self_rag_workflow.py`,`tests/test_agentic_crag_streaming.py`,`tests/test_web_search_tool.py`,`tests/test_hierarchical_retrieval_tools.py`,`tests/test_system_router.py`,`tests/test_complexity_classifier.py`.
- Redteam 相关能力已并入安全评测路径:`app/rag/evaluation/agent_redteam.py` 与 `tests/test_agent_redteam.py`.

暂缓:
- 不做开放式多智能体辩论、无限 ReAct 工具链和长期记忆代理,避免把 3-5s RAG 响应目标拖成研究型 deep research.
- 不做 fine-tuned critic agent 和 RAGCap 全量 benchmark runner,除非后续有独立评测目标和数据集.

Directive: 后续 agentic 能力只能围绕明确产品路径增量补工具,不要再按本文研究清单逐项推进.
