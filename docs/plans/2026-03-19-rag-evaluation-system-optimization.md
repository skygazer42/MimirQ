# RAG 评估系统优化计划

> 基于 2026-03-19 代码审计 + 行业对标（RAGChecker, DeepEval, Galileo, Langfuse, RagMetrics）。
> 聚焦评估管线本身的能力增强。

---

## 现状审计摘要

| 维度 | 已有能力 |
|------|---------|
| **LLM 指标** | RAGAS faithfulness / response_relevancy / answer_similarity / answer_correctness / context_recall / context_precision |
| **检索指标** | recall / MRR / NDCG@K / Hit@K (K=1,3,5,10,20) / doc_recall / family_recall |
| **确定性忠实度** | claim-support ratio（token overlap + 可选 NLI fallback） |
| **多跳评估** | path_completeness / order_consistency / chain_hit_rate |
| **拒答评估** | refusal_correctness / false_positive_rate / false_negative_rate / abstain_rate |
| **回归门禁** | CLI 脚本，top-level + per-slice 阈值，v2 schema，自动生成阈值 |
| **证据检索门禁** | must_recall / parse_quality / provenance_integrity |
| **KG 诊断** | hit_at_k / mrr / recall，failure attribution，ablation |
| **Hard Negative Mining** | 从回归 trace 提取 hard negatives 用于 LTR |
| **Queryset Health** | hit/mrr/ndcg + 延迟 + miss_rate + hard_cases，跨快照 diff |
| **测试生成** | 从文档/对话自动生成测试案例 |
| **排行榜** | 按 metric 排序回归运行 |
| **运行对比** | Diff 两次运行，导出 JSON/HTML |
| **前端** | 对话评估 tab / 回归 tab / 检索消融 tab / 雷达图 |

---

## 差距与优化

### Gap 1: Chunk-Level 细粒度诊断 -- P0

**现状**: faithfulness 是 response 级别。无法回答"哪些 chunk 被使用了？哪些是噪声？"

**行业标杆**: RAGChecker (Amazon, NeurIPS 2024) 提供 Context Utilization / Noise Sensitivity / Self-Knowledge / Hallucination；Galileo 提供 Chunk Attribution Plus / Chunk Utilization Plus。

**建议**: 新增 `app/rag/evaluation/chunk_diagnostics.py`：
- `chunk_utilization`: 被引用的 chunk 数 / 总检索 chunk 数
- `chunk_attribution`: 每个 claim 可归因到的 chunk 比例
- `noise_sensitivity`: 来自不相关 chunk 的 claim 比例
- `self_knowledge_ratio`: 不来自任何 chunk 的正确 claim 比例

### Gap 2: 在线实时评估 -- P0

**现状**: 所有评估离线手动触发。无法持续监控生产质量。

**行业标杆**: RagMetrics 实时 API + 7x24 监控 + 告警；Langfuse observation-level LLM-as-a-Judge。

**建议**: 新增 `app/services/online_eval_service.py`：
- 生产查询异步采样（默认 5%）
- 轻量评估：faithfulness_det + chunk_utilization
- 滑动窗口聚合 + 质量下降告警
- 前端 `/diagnostics` 增加 Online Quality 趋势图

### Gap 3: LLM-as-Judge 深度集成 -- P1

**现状**: `agent_evals.py` 有 LLM-based 评估器但默认 False，未集成到回归流。

**建议**: 在 `run_regression_ragas_evaluation` 中支持 `use_llm_judge=True`，每个 case 输出 `{score, reason, evidence_quotes}`。支持 component-level judge（分别评估检索和生成）。

### Gap 4: 评估结果解释性 -- P0

**现状**: 输出分数但不解释为什么。

**建议**: per-case 增加 `explanation` 字段：
- faithfulness: "共 8 个 claims，6 个有支撑，2 个无支撑：'{claim1}', '{claim2}'"
- retrieval_recall: "参考来源 3 个，命中 2 个，未命中：'{source_id}'"
- 前端回归详情页显示每个 case 的 explanation

### Gap 5: Queryset Health UI + API -- P1

**现状**: 计算服务存在但无 API 端点，无前端可视化。

**建议**: 新增 `/queryset-health/runs` API 端点 + 前端 tab（运行列表/diff/时间趋势图）。

### Gap 6: 质量关联分析 -- P1

**现状**: 无法看到"解析质量差 → 检索质量差"的因果链。

**建议**: 新增 slice 维度 `slice_parse_quality` / `slice_chunk_quality`，前端增加质量归因视图。

### Gap 7: 合成测试案例增强 -- P2

**现状**: 自动生成案例无 `reference_sources`。

**建议**: LLM 同时输出 reference_sources + embedding 搜索自动校验 + 案例类型控制（factual/multi_hop/comparison/conditional/unanswerable）。

### Gap 8: 评估成本追踪 -- P2

**现状**: 不追踪评估本身的 token 消耗和费用。

**建议**: 回归 summary 增加 `eval_llm_tokens_input/output`, `eval_estimated_cost_usd`。

### Gap 9: CI 门禁与 Queryset Health 联动 -- P2

**建议**: `regression_gate.py` 支持 `--queryset-health-baseline` 参数。

---

## 建议实施顺序

**Phase 1 (1-2 周)**: Gap 1 (Chunk-Level 诊断), Gap 4 (解释性)

**Phase 2 (2-3 周)**: Gap 2 (在线评估), Gap 5 (Queryset Health UI)

**Phase 3 (2-3 周)**: Gap 3 (LLM Judge), Gap 6 (质量关联), Gap 7 (合成案例)

**Phase 4 (1 周)**: Gap 8 (成本追踪), Gap 9 (门禁联动)
