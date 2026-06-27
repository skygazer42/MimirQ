# RAG 鲁棒性 / 知识冲突处理 deep-dive（2026-Q2，纯 RAG·training-free）

> 日期：2026-06 ｜ 来源：`plans/cosmic-meandering-teapot.md` 调研地图方向 A+C
> 定位：纯 RAG 检索增强方向，**明确排除 RL 训练**。本方向是我方 67 份 plan + 真实代码的**真空白**（grep 确认 0 实现），且全部 training-free，差异化价值最高。

## Context

我方检索到的 chunk **直接拼进 prompt 喂给 LLM**，不做任何"内外知识一致性"处理。但业界量化发现：
- **~70% 检索段落不直接包含答案**（Astute RAG 实测）——噪声/误导是常态，不是例外。
- **19.2% 案例存在知识冲突**（检索内容 vs 模型内部知识矛盾）。
- 冲突中**内部知识对 47.4% / 外部知识对 52.6%**——两边都不能盲信，简单"以检索为准"会错近一半。

这意味着：再强的检索/rerank 也救不了"检索回来但内容互相打架/与常识冲突"的场景。这一层是我方 pipeline 末端的系统性短板，且补它**零训练、纯 prompt**。

## 一、业界方法拆解

### 1.1 Astute RAG（arxiv 2410.07176，ACL'25，Google）— 主参考
training-free，三步：
1. **Internal Knowledge Elicitation**：先让 LLM 基于 query 生成 N 段"内部知识段落"（它参数里已知的），与检索段落并列，弥补检索遗漏。
2. **Source-aware Consolidation**：把 internal + external（检索）段落一起送入 LLM，按来源分组并做三件事——**合并一致信息 / 显式标记冲突信息 / 过滤无关信息**，产出带来源标注的"整合文档"。
3. **Answer Finalization**：基于整合后信息生成候选答案，按信息可靠性比较，定最终答案。
- 效果：Gemini/Claude 上超越其他鲁棒 RAG；**最差检索质量下，唯一能持平/超过"纯 LLM 不检索"的方法**（即不会被坏检索拖累到比不检索还差）。

### 1.2 同线方法（作为 P2 进阶储备）
- **TrustRAG**（2501.00879）：两阶段；Conflict Resolution 阶段用内部知识补全 + **驳斥恶意/投毒文档**（抗 RAG poisoning）。
- **TruthfulRAG**（2511.10375）：聚焦 factual-level 冲突，token-level 偏好调控。
- **Micro-Act**（2506.05278）：actionable self-reasoning，把冲突拆成可执行的自推理动作。

### 1.3 冲突三分类（survey 2403.08319，Xu et al.；benchmark ConflictBank 2408.12076）
- **context-memory**：检索内容 vs 模型参数知识（最常见，Astute 主攻）。
- **inter-context**：多个检索文档之间互相矛盾。
- **intra-memory**：模型对语义相近输入给出不一致回答。

### 1.4 Faithfulness 评测：FaithJudge（arxiv 2505.04847，EMNLP'25）
LLM-as-judge + 人标注幻觉样本池，评摘要/QA/data-to-text 的 context-faithfulness，比单纯 NLI 更稳。可作为冲突处理效果的度量工具。

## 二、我方现状核实（grep 真实结果）

| 能力 | 现状 | 证据 |
|---|---|---|
| 知识冲突处理 | ❌ 0 实现 | `grep -ri "knowledge conflict\|astute\|consolidat" app/rag/` 仅子串误命中 |
| 内部知识补全检索 | ❌ 无 | engine 检索后直接装配 context |
| 投毒/恶意文档防御 | 🟡 部分 | `safety/output_guard.py`(123) 仅答案级 citation 一致性，无检索段落级冲突识别 |
| Faithfulness 评测 | 🟡 有 metric 无 judge | `evaluation/ragas.py`(2447) 有 `faithfulness`/`atomic_faithfulness`，但无 LLM-Judge 框架（与 `rag-evaluation-deep-dive` P0 缺口一致） |

## 三、落地设计

### P0 — Astute 式 prompt 版知识冲突整合（training-free，最高 ROI）
**新增** `app/rag/components/knowledge_consolidation.py`：
```python
async def consolidate_knowledge(query, retrieved_chunks, llm, *, max_internal=3) -> ConsolidatedContext:
    # 1. 内部知识补全：LLM 基于 query 生成 ≤3 段内部知识(标 source=internal)
    # 2. source-aware 整合：internal+external 一起，LLM 输出
    #    {consistent:[...], conflicts:[{claim_a, claim_b, sources}], filtered_out:[...]}
    # 3. 返回整合后 context + 冲突清单(供 prompt 显式呈现 / trace 透出)
```
**接入** `app/rag/engine.py`：在检索得到 chunks 之后、生成答案之前插入一步（配置开关 `KNOWLEDGE_CONSOLIDATION_ENABLED`，默认 `false`，benchmark 验证后再切默认）。生成 prompt 中把"冲突清单"显式呈现，让 LLM 按可靠性裁决而非盲信。

prompt 骨架（中英双语，放 `app/rag/llm/prompts/`）：
```
你将看到来自[检索]与[模型内部知识]两类来源的信息。请：
1) 合并一致的信息；2) 列出相互冲突的点并标注来源；3) 剔除与问题无关的信息。
回答时优先采用多来源一致的信息；冲突处显式说明依据哪一来源及理由。
```

成本控制：内部知识补全 + 整合 = 1-2 次 fast LLM 调用；建议仅对"检索分数离散度高 / 命中数 < 阈值 / 多文档"场景触发（复用现有 `complexity` 信号），避免每条 query 都付费。

### P1 — FaithJudge 式 faithfulness 评测
扩 `app/rag/evaluation/ragas.py`：新增 LLM-Judge 框架（G-Eval 风格 + 人标注幻觉池），度量"冲突处理 on/off"的 faithfulness 提升。与 `rag-evaluation-deep-dive` 的 LLM-Judge P0 合并实现，避免重复。

### P2 — 进阶
- **TrustRAG 投毒防御**：整合阶段加"恶意文档识别"，对接 `safety/retrieval_rail.py`（防间接注入）。
- **inter-context 冲突**：多文档矛盾检测（NLI 小模型 pairwise）。
- **TruthfulRAG / Micro-Act**：token-level 偏好 / 自推理动作。

## 四、优先级矩阵

| 优先级 | 任务 | 工作量 | 落地文件 |
|---|---|---|---|
| **P0** | Astute prompt 版冲突整合 | ~250 行 + prompt | `components/knowledge_consolidation.py` + `engine.py` 接入 + `config.py` 开关 |
| **P0** | 触发策略（按检索信号选择性启用） | ~60 行 | `engine.py` / 复用 `policy/` |
| **P1** | FaithJudge 式评测 | 合并 eval LLM-Judge | `evaluation/ragas.py` |
| **P2** | 投毒防御 + inter-context 冲突 | ~300 行 | `safety/` + `components/` |

## 五、验证

- **benchmark on/off 对比**：用既有评测栈，跑"冲突处理开/关"的 `faithfulness`/`atomic_faithfulness`/`hallucination_rate` 差异；构造含冲突的测试子集（部分检索段落与已知事实矛盾）。
- **决策门槛**：faithfulness 提升 ≥ +3pt 且延迟/成本可接受 → 切为高风险场景默认开；否则保留为可选开关。
- **成本监控**：记录每 query 额外 LLM 调用数与 token，确认选择性触发把均摊成本压在可接受范围。

## 六、学习入口
- **Astute RAG** arxiv 2410.07176（ACL'25）
- TrustRAG 2501.00879 ｜ TruthfulRAG 2511.10375 ｜ Micro-Act 2506.05278
- Knowledge Conflicts survey 2403.08319 ｜ ConflictBank 2408.12076
- **FaithJudge** 2505.04847（EMNLP'25）

> 一句话：补这一层不需要训练、不需要新模型，只在"检索后→生成前"加一步 source-aware 整合，就能直接抬升最易踩坑的"坏检索/知识冲突"场景的可信度——纯 RAG 里 ROI 最高的差异化点。
