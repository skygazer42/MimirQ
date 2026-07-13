# RAG 验证域统一裁判计划（2026-Q3）——独立 llm_judge + ragas.py 拆分 + 裁判可信度自证

> 日期：2026-07-13 ｜ 前置调研：`plans/rag-evaluation-deep-dive-2026-q2.md`
> 定位：**所有其他 plan 的验收都依赖裁判可信**——召回 A/B、解析 harness、切块 grid、KG 消融，最终都要一个统一、抗偏、可自证的 LLM 裁判。当前裁判逻辑散落在 2543 行的 ragas.py 里，G-Eval/Self-Consistency/Position-Bias 三件防偏机制均缺。

## Context（2026-07-13 核实）

- `app/rag/evaluation/ragas.py` 已长到 **2543 行**（memory 记录时为 ~1000 行段落），judge 逻辑内嵌其中；全库无独立 judge 模块，grep `g_eval|self_consistency|position_bias|atomic_fact` = 0
- 资产良好：runners 五件套（agentic/hybrid/kg/retrieval/stage1_batch，`app/rag/evaluation/runners/`）、metrics 六件（answer_det/decomposition/fusion/ragas_adapter/retrieval/routing）、显著性全套（`regression_run_significance.py` 271 行：t-test/Wilcoxon/McNemar/Bootstrap/BH/Cohen's d）、citation_accuracy/coverage 已有（ragas.py:84-116）
- 评测集：政务自建集 + `contextual_855_plan.py`；"先松后紧"四阶段（50→1000→5000→动态）走到哪一档待盘点

## 落地设计

### P0-1 独立 `app/rag/evaluation/llm_judge.py`（新模块，唯一裁判入口）
接口设计（所有 runner 统一走它，禁止各自手搓 prompt 调 LLM）：
```
judge(question, answer, contexts, *, rubric, mode) -> JudgeResult
  JudgeResult: {score, verdict, rationale, confidence, votes[], schema:"mimirq.llm_judge.v1"}
```
三件防偏机制内建：
1. **G-Eval 式打分**：rubric 显式化 + CoT 打分 + 概率加权（logprobs 可得时）——替代裸 1-5 分。
2. **Self-Consistency**：k=3 采样投票（temperature>0），votes 落库，分歧度进 confidence；分歧超阈值标 `needs_human`。
3. **Position-Bias 消解**：成对比较场景强制 A/B 双序各评一次，冲突则平局——pairwise 是消融对比（召回 plan A/B）的刚需。
- 迁移：ragas.py 内嵌 judge 逻辑改为薄封装调用 llm_judge（兼容期保留旧路径 + 开关）。

### P0-2 裁判可信度自证（judge-the-judge）
- 建 **100 条人工金标**（政务 50 + 通用 50，含刻意的部分正确/引用错误/超纲样本），每季度跑一次 judge vs 人工的 Cohen's κ；κ<0.6 禁止该裁判用于门禁。
- 裁判版本化：prompt/rubric/模型 三元组 hash 进 JudgeResult——换裁判模型后历史分数不可直接比，报告必须携带 judge 版本。

### P1-1 Atomic Fact / Citation 深检（真护城河项，Q2 既定）
- 答案拆原子事实 → 逐条与 citation 上下文做支持性判定（NLI 小模型或 llm_judge mode=fact_check）→ 输出 `supported/contradicted/unverifiable` 三态占比。
- 与 citation_accuracy 现有指标合流：faithfulness 从"整体印象分"升级为"逐 claim 归因"。政务场景"答案每句话可溯源"是投标语言。

### P1-2 ragas.py 拆分（工程还债，随迁移顺手做）
- 2543 行按职责拆：`judge 调用（→llm_judge.py）/ citation 解析（→citation_resolver.py）/ 指标计算（→metrics/）/ 会话取数（→dataset_loader.py）`；ragas.py 保留编排壳 <500 行。

### P2 进阶
- **裁判成本分层**：门禁跑小模型裁判（本地 Qwen 级）+ 周报抽样大模型复核，分歧率监控——评测成本降一个量级才能支撑"每 PR 跑评测"。
- 评测集进入"动态阶段"：线上差评三分类（已有埋点）自动转评测 case，月增 ≥50 条。

## 优先级矩阵

| 优先级 | 任务 | 工作量 | 落点 |
|---|---|---|---|
| P0 | llm_judge.py 三防偏 + 接口统一 | ~5 人日 | `evaluation/llm_judge.py`（新） |
| P0 | 100 条人工金标 + κ 自证 | ~3 人日（含标注） | `evaluation/datasets/` |
| P1 | Atomic Fact + citation 深检 | ~5 人日 | llm_judge mode + metrics |
| P1 | ragas.py 拆分 | ~4 人日 | `evaluation/` 四模块 |
| P2 | 裁判成本分层 | ~3 人日 | judge 配置 + 报告 |

## 验证与门槛
- llm_judge 上线门槛：金标 κ ≥0.6；Self-Consistency 分歧率 <15%；pairwise 双序冲突率 <10%。
- 所有下游 plan（召回/解析/切块/KG）的 A/B 报告自 P0 完成起必须标注 judge 版本。

## 不做什么
- 不引 RAGAS/DeepEval 整框架替换自研栈（现有 runner+显著性资产更贴需求，只借鉴 rubric 设计）；不用裁判分数直接做线上路由（裁判是离线门禁，不进热路径）。
