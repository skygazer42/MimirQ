# RAG 反馈闭环运营化计划（2026-Q3）——差评三分类落库 + 反馈→评测集转化 + 微调数据管线定期化

> 日期：2026-07-13 ｜ 前置调研：`plans/rag-poc-attribution-framework-2026-q2.md`（POC 运营=既定护城河）、`plans/rag-feedback-frontend-deep-dive-2026-q2.md`
> 定位：反馈闭环的**骨架接线超预期**（candidates.py 已挂 hard_negative_mining + 行业规则自动建议，dispatcher 有定时批），但三个断点让"POC 一周运营手册"跑不起来：差评三分类没有结构化字段（归因看板无数据源）、负反馈不会自动变评测 case（验证域"动态评测集"断粮）、微调数据出口有导出无节拍。

## Context（2026-07-13 核实）

- `app/rag/feedback_loop/` 共 415 行三件套：
  - candidates.py——已 import `mine_hard_negatives_for_case_from_trace` + `build_ruleset_suggestions`，schema `mimirq.feedback_loop_candidates.v1` / `mimirq.feedback_training_triple.v1` 双定义
  - dispatcher.py——`dispatch_feedback_loop_batch` + scheduled 变体（:12/:74）
  - hard_negative_promoter.py——JSONL 训练数据导出（:49）
- **缺口 1**：`app/models/feedback.py` 仅 rating / reason(Text 自由文本, :41) / expected_answer——Q2 设计的差评三分类（检索不到 24% / 答错 35% / 超纲 37%）与五字段埋点无结构化落库，前端三分类饼图（既定 P0）无数据源
- **缺口 2**：反馈→评测 case 转化 grep 零命中——验证域 plan 的"评测集动态阶段（月增 ≥50 条）"依赖此链路
- **缺口 3**：超纲三级验证（attribution plan 设计）落地未证实；"系统可控好评率" KPI 无法计算（分母需要三分类）

## 落地设计

### P0-1 差评三分类结构化落库（一切归因的数据源）
- `feedback` 表加字段：`category`（enum: retrieval_miss / wrong_answer / out_of_scope / other）+ `category_source`（user / llm_auto / reviewer）+ 五字段埋点对齐（query_hash / retrieval_trace_ref / profile / judge_score_ref / tenant）。
- 双通道填充：前端打分时可选分类（低摩擦三选一）；未选的由 LLM 自动预分类（用验证域 llm_judge 的 mode=feedback_triage，异步批处理走 dispatcher 既有定时批）。
- 立即解锁：三分类饼图、**"系统可控好评率" KPI**（好评 ÷ (总数 − out_of_scope)）——POC 汇报的核心口径。

### P0-2 反馈→评测 case 转化器（评测集的活水）
- 负反馈（尤其带 expected_answer 的）→ 自动生成 eval case 草稿（question / expected / 差评 trace 引用 / 三分类标签）→ 进待审队列，人工确认后入正式评测集。
- 落点：candidates.py 扩一个 `build_eval_case_candidates`（与既有 ruleset/训练三元组并列的第三种 candidate），schema `mimirq.feedback_eval_case.v1`。
- 与验证域衔接：确认入集的 case 自动带 judge 版本与集版本号；月增 ≥50 条为运营指标。

### P1-1 超纲三级验证接线 + 归因数据服务
- out_of_scope 判定三级：检索分布空/低（trace 已有）→ 知识库覆盖检查（dataset 主题标签）→ llm_judge 复核；三级结论写回 feedback.category_source。
- 归因看板后端：三分类 × 时间 × dataset × profile 聚合 API（前端 feedback P0 的数据层，dashboard service 已有先例可挂）。

### P1-2 微调数据管线定期化（出口有了，补节拍与版本）
- hard_negative_promoter 的 JSONL 导出接入 scheduled dispatcher：周批导出 + 数据集版本号 + 统计卡（数量/去重率/类别分布）；为"先反馈基建后微调"（POC-to-MVP 既定顺序）备好弹药，微调本身不在本计划。

### P2 进阶
- 规则建议审核流：`build_ruleset_suggestions` 产出→industry_rules workbench 待审队列（前端 1222 行已在，接后端待审状态机）。
- 好评侧利用：高分答案的 (query, chunk) 对进 LTR 训练信号（reranker/ltr.py 已有）。

## 优先级矩阵

| 优先级 | 任务 | 工作量 | 落点 |
|---|---|---|---|
| P0 | 三分类字段 + LLM 预分类 | ~3 人日 | `models/feedback.py` + migration + dispatcher |
| P0 | 反馈→评测 case 转化器 | ~3 人日 | `feedback_loop/candidates.py` + 待审 API |
| P1 | 超纲三级验证 + 归因聚合 API | ~4 人日 | feedback_loop + services |
| P1 | 微调数据周批 + 版本化 | ~2 人日 | hard_negative_promoter + dispatcher |

## 验证与门槛
- P0 上线一周内：三分类覆盖率 ≥90%（含 LLM 兜底）；LLM 预分类与人工抽检一致率 ≥80% 才可用于 KPI 口径。
- 评测集月增 ≥50 条且人工确认率有记录——拒绝"自动入集无人审"。

## 不做什么
- 不做在线学习/自动调权（反馈只进离线管线，线上行为变更必须走 A/B）；不自动采纳规则建议（必须过 workbench 人审）；微调训练本身另行立项（本计划只备数据）。
