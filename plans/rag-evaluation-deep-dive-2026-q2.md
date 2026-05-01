# RAG 评测全面调研 — 维度盘点 + 自研 LLM-as-Judge 框架

## Context

**触发场景**:用户从 `/evaluations` 出发,要求**全面调研 RAG 评测**,约束**不引入冗余大包,优先自研**。`/evaluations` 已有 3 个 tab(对话评测 / 回归测试 / 检索集健康度),依托 RAGAS + 完整 regression 工程化(8+ services + 1214 行 ablation 前端 + 823 行 regression-tab + 371 行 queryset-health + holographic-radar 雷达),后端 `app/rag/evaluation/` 15+ 文件覆盖 RAGAS / agent_evals 765 / hard_negative_mining 352 / kg_hardcase_deterministic 259 / chunk_diagnostics / calibration / online_eval_service / queryset_health 等已具规模。

**问题**:工程化骨架完整,但**评测维度过窄**——只有 3 个 RAGAS metric 暴露给用户(faithfulness / response_relevancy / context_precision),业界主流 metric ≥30 个未实现;**LLM-as-Judge 缺统一框架**(各处散写 prompt,无方差控制 / 无校准 / 无人机一致性);**红队/对抗/多跳推理/Citation/校准/公平性等评测缺失**;**评测集建设缺方法论**(评测集 plan 已规划但未落地)。本调研对标业界(RAGAS/TruLens/DeepEval/Phoenix/CRAG/HaluEval/MultiHop-RAG),**全部自研补齐**,不引入 DeepEval/TruLens/Phoenix 这类带巨大依赖的评测库。

---

## 1. 现状盘点(已确认)

### 1.1 后端评测能力(15+ 模块,~3000+ 行)

| 文件 | 行数 | 角色 |
|---|---|---|
| `app/rag/evaluation/agent_evals.py` | 765 | Agent 工作流评测 |
| `app/rag/evaluation/hard_negative_mining.py` | 352 | 硬负样本挖掘 |
| `app/rag/evaluation/kg_hardcase_deterministic.py` | 259 | KG 困难案例 |
| `app/rag/evaluation/evidence_retrieve_gate.py` | 233 | 证据检索门 |
| `app/rag/evaluation/chunk_diagnostics.py` | 177 | chunk 诊断 |
| `app/rag/evaluation/agent_redteam.py` | 133 | Agent 红队(轻量) |
| `app/rag/evaluation/calibration.py` | 106 | 置信度校准 |
| `app/rag/evaluation/hard_negative_stress.py` | 76 | 硬负样本压测 |
| `app/rag/evaluation/graphrag_bench.py` | 57 | GraphRAG benchmark |
| `app/rag/evaluation/ragas.py` | - | RAGAS 集成主入口 |
| `app/rag/evaluation/retrieval_evaluator.py` | - | 检索 metric(MRR/NDCG/Recall) |
| `app/rag/evaluation/regression_sample_builder.py` | - | 回归样例构建 |
| `app/rag/evaluation/online_eval_service.py` | - | 在线评测 |
| `app/rag/evaluation/queryset_health_service.py` | - | 检索集健康度 |
| `app/rag/evaluation/document_retrieval_hit_frequency.py` | - | 命中频次 |
| `app/services/regression_*.py` (8 个) | - | leaderboard/diff/bundle/retention/scope |
| `app/api/v1/evaluations.py` | 大 | 完整路由 |

### 1.2 前端评测能力(~3000+ 行)

| 文件 | 行数 | 角色 |
|---|---|---|
| `web/components/evaluation/retrieval-ablations-page.tsx` | 1214 | 消融实验(已 plan) |
| `web/components/evaluation/regression-tab.tsx` | 823 | 回归测试 |
| `web/components/evaluation/queryset-health-tab-client.tsx` | 371 | 检索集健康度 |
| `web/components/evaluation/evaluation-data-ops-panel.tsx` | 182 | 数据 ops |
| `web/app/evaluations/page.tsx` | 798 | 主页 + 对话评测 tab |
| `web/components/evaluation/holographic-radar*.tsx` | 111 | 雷达图 |
| `web/components/evaluation/ragas-metric-selector.tsx` | 72 | metric 选择器 |

### 1.3 已暴露 metric(仅 3 个 RAGAS)

```ts
RAGAS_METRIC_OPTIONS = [
  { key: 'faithfulness', label: 'Faithfulness（忠实度）' },
  { key: 'response_relevancy', label: 'Response Relevancy（相关性）' },
  { key: 'context_precision', label: 'Context Precision' },
]
```

**Leaderboard metric 6 个**(从 ablation plan 已知):retrieval_mrr / retrieval_recall / retrieval_ndcg@10 / retrieval_ndcg@20 / faithfulness_det / refusal_correctness

### 1.4 8 大缺口

1. ❌ **评测维度过窄**:只 3 个 RAGAS,业界 ≥30 个 metric 未实现
2. ❌ **LLM-as-Judge 框架缺失**:各处散写 prompt,无方差/校准/置信度
3. ❌ **多跳推理评测缺失**:对齐 MultiHop-RAG / HotpotQA 没有
4. ❌ **Citation/Attribution 评测缺失**:引用准不准、能不能定位回原文
5. ❌ **公平性/偏见评测缺失**:不同 group / domain 的差异
6. ❌ **多模态评测缺失**:图表/表格/OCR-based 答案
7. ❌ **对抗鲁棒性评测**:`agent_redteam.py` 仅 133 行偏轻
8. ❌ **评测集建设方法论未落地**(对齐 eval-dataset plan 4 阶段)

---

## 2. 业界 RAG 评测全景(2024-2026)

### A. 评测框架(全部排除自部,只参考思路)

| 框架 | 特点 | 排除原因(按用户约束) |
|---|---|---|
| **RAGAS** | 已集成 | ✅ 保留 |
| **TruLens** | RAG triad + leaderboard | 全套引入太重 |
| **DeepEval** | 14+ metric + pytest CI | 依赖 transformers / torch 链路重 |
| **Phoenix Evals** | OTel 原生 | 全 Phoenix 服务太重 |
| **LangChain Eval** | criteria evaluators | 偏 LangChain 强耦合 |
| **OpenAI Evals** | YAML 配置 | 重 |
| **Promptfoo** | matrix 对比 | 偏 prompt 不偏 RAG |
| **MLflow Evaluation** | LLM judges | MLflow 接入是 lock-in 解药 |
| **Inspect AI** (UK AISI) | 安全评测 | 偏研究 |
| **Garak** | LLM 漏洞扫描 | safety plan 已规划 |

**结论**:**只复用 RAGAS,其他全自研** metric 实现(每个 metric 50-200 行 Python)。

### B. 业界标准 benchmark(评测集来源)

| Benchmark | 类型 | 与 MimirQ |
|---|---|---|
| **RAGBench** (NeurIPS'24) | 标准化 RAG | 已在 eval-dataset plan |
| **CRAG** (Meta, NeurIPS'24) | 综合 RAG benchmark | 已规划 |
| **MultiHop-RAG** | 多跳推理 | 已规划 |
| **HotpotQA / 2WikiMultiHop** | 多跳 QA | 已规划 |
| **CRUD-RAG** | 中文 RAG(增删改查) | 已规划 |
| **LegalBench-RAG** | 法律 RAG | 已规划 |
| **MIRAGE** | 医疗 RAG | 候选 |
| **FEVER / FEVEROUS** | 事实核查 | 候选 |
| **HaluEval** | 幻觉评测 | **强相关,P0 候选** |
| **TruthfulQA** | 真实性 | 候选 |
| **MS MARCO / BEIR** | 检索 baseline | 已规划 |
| **MTEB** | embedding 评测 | 已规划 |
| **GraphRAG-Bench** (ICLR'26) | KG-RAG | 已有 graphrag_bench.py |
| **JailbreakBench / HarmBench / AdvBench** | 安全红队 | safety plan 已规划 |
| **RGB** (Robustness, Generation, Bias) | 中文 RAG 鲁棒性 | 候选 |

### C. RAG 评测 30+ metric 全景(分维度)

#### C.1 检索质量(纯程序化)
- **Recall@K / Precision@K / Hit@K / F1@K**
- **MRR (Mean Reciprocal Rank)**
- **NDCG@K / DCG@K**(相关性折扣)
- **MAP (Mean Average Precision)**
- **Coverage** / **Diversity** / **Novelty**
- **Latency-Adjusted Recall**

#### C.2 答案忠实度(LLM-as-Judge)
- **Faithfulness**(已有,RAGAS)
- **Groundedness**(类似)
- **Hallucination Rate**(对应 HaluEval)
- **Atomic Fact Verification**(分解为子事实验证)
- **Contradiction Detection**(NLI 思路)

#### C.3 答案相关性
- **Response Relevancy**(已有)
- **Helpfulness**(LLM-Judge)
- **Completeness**(回答覆盖问题)
- **Conciseness**(简洁度)

#### C.4 答案正确性(对照 ground truth)
- **Exact Match (EM)**
- **Token F1** / **Rouge-L** / **BLEU-4**
- **BERTScore**(语义)
- **LLM-Judge Correctness**(G-Eval 风格)
- **Numeric Accuracy**(数字答案专项)

#### C.5 上下文质量
- **Context Precision**(已有)
- **Context Recall**(对照 ground truth contexts)
- **Context Sufficiency**(自研:LLM 判断"上下文是否足够回答")
- **Context Coverage**
- **Context Entity Recall**
- **Noise Sensitivity**(加噪后稳定性)

#### C.6 引用/可归属性
- **Citation Accuracy**(引用是否真实存在)
- **Citation Coverage**(每个事实有引用)
- **Quote Verifiability**(引用文本回查)
- **Attribution Score** (HuggingFace SourceLink)

#### C.7 多跳推理
- **Decomposition Accuracy**(分解步骤对不对)
- **Hop Path Correctness**(路径)
- **Bridge Entity Recall**(桥节点)
- **Sub-question F1**

#### C.8 鲁棒性
- **Adversarial Robustness**(对抗 prompt)
- **Noise Tolerance**(注入无关 chunk)
- **Order Sensitivity**(打乱顺序)
- **Negation Handling**(否定句)
- **OOD Detection**

#### C.9 安全/合规
- **Refusal Correctness**(已有 leaderboard)
- **Toxicity Score**
- **PII Leakage Rate**(对齐 safety plan)
- **Jailbreak Resistance (ASR)**
- **Bias / Group Disparity**(性别/地域/年龄)
- **Harm Score**(Llama Guard 风格)

#### C.10 校准/置信度
- **Expected Calibration Error (ECE)**(已有 calibration.py)
- **Brier Score**
- **Reliability Diagram**
- **Selective QA Coverage-Risk**

#### C.11 多轮对话
- **Conversation Coherence**
- **Topic Drift Detection**
- **Follow-up Resolution**(代词解析)
- **Memory Consistency**

#### C.12 多模态
- **Image-Text Alignment**
- **OCR Accuracy**
- **Table-Cell QA Accuracy**
- **Chart Understanding**

#### C.13 KG-RAG 专项
- **Triple F1**(已有 hardcase)
- **Path Accuracy**
- **Subgraph Coverage**
- **Cypher Query Correctness**

#### C.14 系统级
- **End-to-End Latency** (p50 / p95 / p99)
- **Cost per Query** (tokens × price)
- **Throughput (QPS)**
- **Error Rate**

### D. LLM-as-Judge 业界最佳实践

- **G-Eval (Liu et al. 2023)**:CoT 引导的 LLM 打分,prompt 含评分准则
- **JudgeLM**:专门微调的 judge 模型(开源 7B/13B/33B)
- **Self-Consistency**:多次采样取平均/中位数(对齐 IBM blueprint 思路)
- **Position Bias 修正**:对比时交换 A/B 两次取平均
- **Verbosity Bias 修正**:控制候选答案长度
- **Reference Bias 修正**:不依赖参考答案
- **Pairwise vs Pointwise**:pairwise 更稳但 N² 慢
- **Calibration Set**:小批人工标注校准 LLM 分数
- **Inter-annotator Agreement (Cohen's κ)**:LLM judge 之间一致性
- **Reproducibility**:固定 seed + temperature=0 + 模型版本锁

---

## 3. Gap 分析(MimirQ vs 业界 SOTA)

| 维度 | 业界 SOTA | MimirQ 现状 | Gap | 优先级 |
|---|---|---|---|---|
| 检索 metric 全套 | BEIR 标准(MRR/NDCG/Recall/MAP/Hit) | 已有 mrr/recall/ndcg | 缺 MAP / Hit@K / Diversity | P1 |
| Faithfulness / Hallucination | RAGAS + HaluEval | 已有 faithfulness | 缺 atomic fact / contradiction | **P0** |
| Citation / Attribution | HuggingFace SourceLink | 无 | **完全缺**(关键差异化) | **P0** |
| 多跳推理评测 | MultiHop-RAG / HotpotQA | 无 | 完全缺 | P1 |
| LLM-as-Judge 框架 | G-Eval / JudgeLM | 散在各处无统一 | **完全缺统一框架** | **P0** |
| Self-Consistency / 方差控制 | G-Eval 论文 | 无 | LLM 分数不稳 | **P0** |
| 校准(ECE / Brier) | 已有 calibration.py | 偏薄(106 行) | 缺 reliability diagram + selective QA | P1 |
| 公平性/偏见 | RGB / Bias-RAG | 无 | 缺 group 切片 | P2 |
| 对抗鲁棒性 | JailbreakBench | agent_redteam 133 行偏轻 | 缺标准红队套件 | P1 |
| 多模态评测 | MMMU / DocVQA | 无 | KG plan 多模态后置 | P3 |
| 完整性 / 简洁度 | LLM-Judge | 无 | 用户体验维度缺 | P1 |
| Noise Sensitivity | RAGAS NoiseSensitivity | 已有 hard_negative | 半实现 | P1 |
| Numeric Accuracy | 自研 | 无 | 数字答案专项 | P2 |
| 评测集 4 阶段建设 | eval-dataset plan | 仅规划未落地 | 缺执行 | P1 |
| MTEB / BEIR 适配 | 标准接口 | graphrag_bench 已类似 | 缺标准化 | P2 |
| HaluEval 中文集 | 学术开源 | 无 | 幻觉评测无基线 | P1 |
| Pairwise A/B Judge | LMSYS arena | 无 | 缺 ELO leaderboard | P2 |

---

## 4. 推荐方案:三层自研评测架构

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3 — 专项与生态(P2/P3,全自研)                            │
│   - 多模态评测套件                                             │
│   - 公平性 / 偏见 group 切片                                   │
│   - Pairwise ELO arena(对齐 LMSYS)                            │
│   - BEIR / MTEB 标准接口                                       │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2 — 维度补齐(P1,1-2 月,全自研)                         │
│   - 多跳推理 metric(decomposition / hop accuracy)             │
│   - 完整性 / 简洁度 / 校准 metric 扩展                         │
│   - 红队套件扩容(JailbreakBench 子集本地化)                  │
│   - 评测集 Stage 1→2 落地(50→1000 cases)                      │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1 — 严谨性补齐(P0,2-3 周,全自研)                       │
│   - **统一 LLM-as-Judge 框架**(G-Eval 风格,Pydantic SO)      │
│   - **Citation/Attribution 评测**(自研引用回查)              │
│   - **Atomic Fact Verification**(答案分解 → 子事实校验)      │
│   - Self-Consistency 多采样方差控制                            │
│   - 前端 metric 选择器扩展(从 3 个到 12+ 个)                  │
└──────────────────────────────────────────────────────────────────┘
```

**核心设计原则**:
1. **零新依赖**:所有 metric 自研 50-200 行 Python,只用现有 LLM 客户端 + scipy
2. **复用基建**:RAGAS 保留作为参考实现,但 12+ 新 metric 走自研框架
3. **LLM-Judge 统一管控**:所有 LLM 评分走 `app/rag/evaluation/llm_judge.py` 单一入口,方便控成本/方差/版本
4. **Pydantic SO + JSON mode**:所有 judge prompt 强类型输出,对齐 IBM blueprint
5. **Reproducibility 默认**:judge model + version + temperature + seed 入 metric 元数据

---

## 5. P0 落地任务(2-3 周纯自研)

### 5.1 统一 LLM-as-Judge 框架(~500 行)

**新建** `app/rag/evaluation/llm_judge.py`:
- `class LLMJudge`:统一 judge 入口
  - `judge(prompt, schema, n_samples=3, temperature=0.0, seed=42)` → `JudgeResult { score, reasoning, samples, variance }`
  - Self-Consistency:n_samples > 1 时多次采样取中位数,记录方差
  - Position Bias 修正:pairwise 时交换两次
  - Pydantic SO 强类型输出
  - 复用 `app/rag/kg/extraction/llm_processor.py` 的 LLM 客户端
  - Cost tracker 集成(对齐 deep-research plan)

**新建** `app/rag/evaluation/judge_prompts.py`:
- 类组织(对齐 IBM blueprint Prompt-as-Code):
  - `SystemPrompts.FAITHFULNESS / RELEVANCY / CORRECTNESS / COMPLETENESS / CONCISENESS / CITATION`
  - `SchemaDefinitions.JudgeScore { score: 0-5, reasoning, confidence }`
  - `OneShots.*` 各 metric 的 few-shot 例子

### 5.2 Citation / Attribution 评测(~400 行)

**新建** `app/rag/evaluation/citation_eval.py`:
- `compute_citation_accuracy(answer, citations, contexts)`:
  - 抽取答案中所有 `[1]`/`[doc_id]` 引用标记(正则)
  - 验证每个引用确实存在于 contexts(精确字符串匹配 + fuzzy)
  - 返回 `accuracy = correct / total`
- `compute_citation_coverage(answer, citations)`:
  - LLM-Judge 抽取答案中"声明性陈述"
  - 每个陈述是否有引用支撑
  - 返回 `coverage = supported / total_claims`
- `compute_quote_verifiability(answer, contexts)`:
  - 答案中带引号 `"..."` 的片段
  - 每个能否在 contexts 中精确找到
  - 返回 `verifiability ratio`

### 5.3 Atomic Fact Verification(~350 行)

**新建** `app/rag/evaluation/atomic_fact_eval.py`:
- `decompose_into_atomic_facts(answer)` → 调 LLM 分解为子事实列表(Pydantic SO)
- `verify_atomic_fact(fact, contexts)` → NLI 思路:`entails / neutral / contradicts`
- 总体 `faithfulness = entails_count / total_facts`
- `hallucination_rate = (neutral + contradicts) / total`
- 复用 5.1 的 LLMJudge

### 5.4 前端 metric 选择器扩展(~200 行)

**修改** `web/components/evaluation/ragas-metric-selector.tsx`:
- `RAGAS_METRIC_OPTIONS` 从 3 → **12+**:
  - 已有:faithfulness / response_relevancy / context_precision
  - 新增:atomic_faithfulness / hallucination_rate / citation_accuracy / citation_coverage / quote_verifiability / answer_correctness / completeness / conciseness / context_recall / context_sufficiency
- 分类标签:`检索质量 / 忠实度 / 相关性 / 引用 / 完整性`
- 每个 metric 标注"程序化"/"LLM-Judge"/"成本估"
- 默认勾选 4 个核心:faithfulness / response_relevancy / citation_accuracy / context_recall

**修改** `web/components/evaluation/holographic-radar.tsx`:
- 雷达图轴数支持动态 4-12 维

### 5.5 自研 metric 实现集合(~600 行)

**新建** `app/rag/evaluation/metrics/`:
- `text_metrics.py`:exact_match / token_f1 / rouge_l / bleu_4(纯 Python,无 nltk/sacrebleu 依赖,~150 行)
- `bertscore_metric.py`:复用项目内 BGE-M3 embedding 算 cos sim(无 bert-score 包,~50 行)
- `noise_sensitivity.py`:已有 hard_negative_mining 扩展(~50 行)
- `completeness.py` / `conciseness.py`:LLM-Judge(~50 行 each)
- `context_recall.py`:对照 ground truth contexts 算 recall

### 5.6 评测路由扩展

**修改** `app/api/v1/evaluations.py`:
- `RagasRunCreate` 接收 `metrics: list[str]` 扩展校验
- 新增 metric 路由到对应实现
- 单 run 可配置 LLM judge 模型(默认项目 LLM,可降为 Haiku)
- 输出 schema 加 `metric_metadata`(judge_model / n_samples / variance / cost)

### 5.7 单测(~400 行)

- `tests/test_llm_judge.py`:Self-Consistency 方差;Position Bias 修正;Schema 校验
- `tests/test_citation_eval.py`:正例/负例/边界
- `tests/test_atomic_fact_eval.py`:分解 / 验证逻辑
- `tests/test_metrics_text.py`:EM/F1/Rouge/BLEU 经典样例

---

## 6. P1 落地任务(1-2 个月,全自研)

### 6.1 多跳推理评测(~400 行)

**新建** `app/rag/evaluation/multihop_eval.py`:
- `decomposition_accuracy`:LLM-Judge 拆解步骤是否正确
- `hop_path_correctness`:KG plan 的 agentic_beam_search trace → 路径对照
- `bridge_entity_recall`:桥节点是否在 contexts 中
- `sub_question_f1`:子问题答案 F1

### 6.2 检索 metric 补全(~200 行)

**修改** `app/rag/evaluation/retrieval_evaluator.py`:
- 新增 MAP / Hit@K / Diversity(Jaccard) / Coverage
- benchmark 1k queries < 1s

### 6.3 校准扩展(~250 行)

**修改** `app/rag/evaluation/calibration.py`(从 106 行 → ~350 行):
- ECE 已有 → 加 Brier Score / Reliability Diagram
- Selective QA Coverage-Risk(覆盖率-风险曲线)
- 前端 `web/components/evaluation/calibration-panel.tsx`(~250 行)用 echarts

### 6.4 红队套件扩容(~500 行)

**修改/扩容** `app/rag/evaluation/agent_redteam.py`(从 133 → ~600 行):
- JailbreakBench 子集本地化(100 prompts,中文翻译)
- HarmBench 子集
- AdvBench 子集
- Indirect Prompt Injection(对齐 input_guard 测试)
- 输出 ASR(Attack Success Rate)目标 <5%(对齐 safety plan)

### 6.5 评测集 4 阶段落地(对齐 eval-dataset plan)

- `evaluation/poc_runner/` 落地(已规划,5 字段埋点)
- Stage 1:50 cases 手工 → Stage 2:1000 cases LLM 合成 + 人工筛
- 集成 IBM blueprint 8 维难点表

### 6.6 Per-metric 失败钻取

**新建** `web/components/evaluation/metric-failure-drilldown.tsx`(~300 行):
- 选 metric → 列出该 metric 最差的 N 个 case
- 展示 question / expected / actual / judge_reasoning
- 对齐 ablation plan 的 per-case 钻取

### 6.7 HaluEval 中文集成

**新建** `app/rag/evaluation/halu_eval_zh.py`(~200 行):
- 下载 HaluEval-zh 子集
- 适配为 MimirQ 评测格式
- 提供 `app/cli/run_halu_eval.py` 一键跑

---

## 7. P2/P3(季度计划)

### P2

- **Pairwise A/B Judge ELO Arena**(对齐 LMSYS):新建 `app/rag/evaluation/pairwise_arena.py`,~400 行,Bradley-Terry 模型计算 ELO
- **公平性切片**:`group_disparity.py`,按 metadata 切片(性别/地域/年龄/行业),报告 Δ
- **BEIR / MTEB 标准接口**:`scripts/run_beir_eval.py` + dataset 适配器
- **Numeric Accuracy 专项**:数字答案的 ±tolerance 评分
- **JudgeLM 自托管**(可选):本地小模型替代 GPT-4 judge,降成本 10×

### P3

- **多模态评测套件**:image-text alignment / OCR / table QA / chart QA
- **多轮对话评测**:topic drift / coherence / memory consistency
- **持续 online eval**:`online_eval_service.py` 扩展,生产采样自动评测 + 告警
- **跨语言评测**:中英文对照 metric

---

## 8. 关键文件清单

**修改**:
- `app/api/v1/evaluations.py`(metric 路由扩展)
- `app/rag/evaluation/calibration.py`(P1 扩容)
- `app/rag/evaluation/agent_redteam.py`(P1 扩容)
- `app/rag/evaluation/retrieval_evaluator.py`(P1 metric 补全)
- `web/components/evaluation/ragas-metric-selector.tsx`(metric 列表 12+)
- `web/components/evaluation/holographic-radar.tsx`(动态轴数)
- `web/components/evaluation/regression-tab.tsx`(metric 展示扩)
- `web/app/evaluations/page.tsx`(对话评测 metric 显示扩)

**新建**(纯自研):
- `app/rag/evaluation/llm_judge.py`(P0)
- `app/rag/evaluation/judge_prompts.py`(P0,Prompt-as-Code 类组织)
- `app/rag/evaluation/citation_eval.py`(P0)
- `app/rag/evaluation/atomic_fact_eval.py`(P0)
- `app/rag/evaluation/metrics/text_metrics.py`(P0)
- `app/rag/evaluation/metrics/bertscore_metric.py`(P0)
- `app/rag/evaluation/metrics/completeness.py`(P0)
- `app/rag/evaluation/metrics/conciseness.py`(P0)
- `app/rag/evaluation/metrics/context_recall.py`(P0)
- `app/rag/evaluation/metrics/noise_sensitivity.py`(P0)
- `app/rag/evaluation/multihop_eval.py`(P1)
- `app/rag/evaluation/halu_eval_zh.py`(P1)
- `app/rag/evaluation/pairwise_arena.py`(P2)
- `app/rag/evaluation/group_disparity.py`(P2)
- `web/components/evaluation/metric-failure-drilldown.tsx`(P1)
- `web/components/evaluation/calibration-panel.tsx`(P1)
- `tests/test_llm_judge.py` / `test_citation_eval.py` / `test_atomic_fact_eval.py` / `test_metrics_text.py`

**复用**(零修改):
- `app/rag/evaluation/ragas.py`(保留作为对照实现)
- `app/rag/evaluation/agent_evals.py`(765 行,扩展不重写)
- `app/rag/evaluation/hard_negative_mining.py`(352 行)
- `app/rag/evaluation/kg_hardcase_deterministic.py`(259 行)
- `app/services/regression_*.py`(8 个)
- 现有依赖:scipy / numpy / pydantic(无新增)

---

## 9. 验证方法

1. **LLM-Judge 单测**:`pytest tests/test_llm_judge.py -v` — Self-Consistency 方差 <0.5;Position Bias 修正后 swap 一致
2. **Citation 单测**:正例(全引用对)+ 负例(虚构引用)+ 边界(0 引用)
3. **Atomic Fact 单测**:已知答案分解出 ≥3 facts;contradicts 测例正确识别
4. **API 烟测**:
   ```bash
   curl -X POST /api/v1/ragas/regression/runs \
     -d '{"metrics":["faithfulness","atomic_faithfulness","citation_accuracy","context_recall"],...}'
   ```
5. **前端联调**:`/evaluations` → 对话评测 tab → metric 选择器显示 12+ 项 → 跑一个 run → 雷达图 12 轴显示
6. **失败钻取**(P1):选 atomic_faithfulness 最差 5 case → 看 judge_reasoning 合理
7. **HaluEval 联调**(P1):跑 HaluEval-zh 200 cases,准确率与论文 baseline 同档
8. **完整验证**:`pnpm verify` + `pytest tests/test_llm_judge.py tests/test_citation_eval.py tests/test_atomic_fact_eval.py -v` 全绿

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| LLM-Judge 成本爆 | 默认 Claude Haiku 4.5(¥0.005/judge);1000 cases × 4 metric ≈ ¥20;n_samples 默认 1,关键 metric 才 3 |
| LLM-Judge 方差大 | Self-Consistency n_samples + 中位数;temperature=0;固定 seed |
| Position Bias 误差 | pairwise 强制双向交换 |
| Verbosity Bias | judge prompt 显式提示"忽略长度差异" |
| Pydantic SO 失败 | 二次 reparse(对齐 IBM blueprint SO Reparser);失败降级到正则抽数 |
| Citation 正则误判 | 多 pattern 兼容 `[1]` / `[doc_id]` / `^chunk_xxx` / `(Source: ...)` |
| 评测集小 → 显著性低 | 强制 n>=30 才信任(对齐 ablation plan bootstrap) |
| HaluEval 中文质量 | 人工 spot-check 100 例 |
| 12+ metric 加载慢 | 异步并行;前端流式更新 |
| 改动后 leaderboard schema 不兼容 | metric_metadata JSON 字段扩展;旧 run 显示"-" |

---

## 11. 与已有调研的关系

- 与 `plans/rag-eval-dataset-deep-dive-2026-q2.md`:本计划是其**评测维度的工程实现**,提供 metric 定义,评测集 plan 提供数据
- 与 `plans/rag-ablation-deep-dive-2026-q2.md`:本计划提供 metric,ablation plan 提供运行框架与统计显著性 → 配对完美
- 与 `plans/rag-poc-attribution-framework-2026-q2.md`:差评三分类(检索不到 24% / 答错 35% / 超纲 37%)直接对应本计划的 context_recall / faithfulness / refusal_correctness 三类 metric
- 与 `plans/rag-safety-compliance-deep-dive-2026-q2.md`:红队套件扩容是双方共同 P1
- 与 `plans/rag-visualization-deep-dive-2026-q2.md`:RAG triad 雷达 / failure drilldown 是其 P1 的具体实例
- 与 `plans/rag-ibm-champion-blueprint-2026-q2.md`:judge_prompts.py 类组织 + Pydantic SO 直接复用其规范
- 与 `plans/rag-context-expansion-rerank-2026-q2.md`:855 问 × 11.3 段评测集是本计划的高质量 ground truth 来源
- 与 `plans/rag-poc-to-mvp-delivery-2026-q2.md` LLM 元数据三字段(summary/keywords/questions):questions 字段 = HyDE eval 的 query 来源
- 与 `plans/rag-auto-tagging-services-2026-q2.md` LLM tagger:标签作为评测切片维度

---

## 12. 关键洞察

1. **MimirQ 评测骨架已业界一线**(15+ 后端 + 3000+ 前端),但**暴露 metric 仅 3 个,深度 ≠ 广度**
2. **不引大包是对的**:DeepEval/TruLens 全套带 transformers/torch 等几 GB 依赖,自研 12+ metric 只需 ~2000 行 Python + 现有 LLM 客户端
3. **LLM-as-Judge 必须统一框架**:散在各处的 prompt 是技术债,统一入口能控成本/方差/校准/复现
4. **Citation 评测是真护城河**:业界都没做透;企业客户最看重"答案是否能定位到原文"
5. **Self-Consistency + 固定 seed + 模型版本锁**是 reproducibility 的底线:任何 LLM-Judge 不带这三样都是不可复现的
6. **Atomic Fact Verification 比 Faithfulness 更严**:答案分解到子事实再验证,能抓住 RAGAS 漏掉的"部分正确"幻觉
7. **评测集质量 > 评测 metric 数量**:50 个高质量人工 case 胜过 1000 个 LLM 合成低质 case(对齐 PoC plan 工程次序)
8. **Reproducibility 是评测的尊严**:judge_model + version + temperature + seed + prompt_hash 必须入 metric_metadata,任何 leaderboard 不带这些都是误导

---

## 13. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口。

已落地:
- 回归评测指标 catalog 扩展:在现有 RAGAS 指标之外,显式开放 deterministic gate 指标。
- 低成本核心指标:atomic_faithfulness、hallucination_rate、citation_accuracy、citation_coverage、quote_verifiability、chunk_attribution、chunk_utilization、noise_sensitivity、self_knowledge_ratio、refusal_correctness。
- 后端执行策略:会话评测保持原 RAGAS 路径;回归评测会自动拆分 RAGAS 指标与程序化指标,避免把程序化指标误送进 RAGAS。
- 元数据闭环:regression item meta 持久化 citation / hallucination / quote-verifiability 信号,per-case scores 可按请求指标返回。

暂缓:
- 暂缓统一 LLM-as-Judge 大框架、自研 prompt/schema 平台和 self-consistency 多采样,当前已有可选 llm_judge,先不扩大成本面。
- 暂缓 Atomic Fact LLM 分解,NLI verifier,以及 HaluEval/CRAG/BEIR/MTEB 等 benchmark 接入,这些属于研究或数据集体系。
- 暂缓 Pairwise ELO、公平性、多模态、多轮对话评测套件,当前产品闭环不依赖。
- 暂缓新增大依赖或外部评测平台,继续坚持零新增依赖和复用现有 regression 基建。

Directive: 后续如需继续扩展评测,从真实线上失败样例或客户验收指标出发建 ticket,不要再按本文档逐项推进。
