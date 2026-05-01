# RAG 消融实验全面调研 — 现状评估 + 业界对标 + 升级路径

## Context

**触发场景**:用户从 `/evaluations/ablations` 页面出发,要求对消融实验做全面调研。该页面是 MimirQ 评估检索/生成参数对指标影响的核心工具。**项目内 ablation 工程化已具规模**(`scripts/retrieval_ablation.py` 602 行 + `scripts/run_nightly_ablations.py` 485 行 + 前端 `retrieval-ablations-page.tsx` 1214 行 + 8 个后端 service),覆盖 38 个可调参数(retrieval_profile / multi_query / hierarchy / fusion / reranker / mmr / sparse / query_rewrite / weight_rerank 等),支持笛卡尔网格、leaderboard、base vs target diff、HTML 导出、夜间 cron。

**问题**:工程化"做了"不等于"做对"——对比业界(W&B Sweeps / MLflow / Optuna / Promptfoo / LangSmith Experiments / BEIR / RAGAS),MimirQ 缺**统计显著性、参数敏感度、多目标 Pareto、自动调参、实验跟踪标准化**等关键能力,且前端只支持单 run 创建,后端 CLI 才能笛卡尔批量。本调研目标:**评估"做得有多深"、对标业界 SOTA、给出升级路径**。

---

## 1. 现状盘点(已确认)

### 1.1 后端能力(强项)

| 文件 | 规模 | 能力 |
|---|---|---|
| `app/api/v1/evaluations.py` | 大 | 完整 regression run 路由(create/list/leaderboard/diff/bundle/case 导入) |
| `app/services/regression_leaderboard.py` | - | 按 metric 排序的多 run 排行榜 |
| `app/services/regression_run_diff.py` | - | 两 run 字段级 diff |
| `app/services/regression_run_diff_html.py` | - | HTML 导出报告 |
| `app/services/regression_run_bundle.py` | - | run 完整 bundle 导出(可含 contexts/text) |
| `app/services/regression_run_retention.py` | - | 数据保留/清理 |
| `app/services/regression_run_scope.py` | - | scope 过滤 |
| `app/rag/evaluation/ragas.py` | - | RAGAS 集成(faithfulness/relevancy/precision) |
| `scripts/retrieval_ablation.py` | 602 行 | **CLI 笛卡尔展开** + base vs N variants 批量 |
| `scripts/run_nightly_ablations.py` | 485 行 | **Cron 夜间运行**(retrieval-only 默认,无 LLM 成本) |
| `tests/test_retrieval_ablation.py` | - | 单测 |
| `tests/test_run_nightly_ablations.py` | - | 单测 |

### 1.2 前端能力

| 维度 | 现状 |
|---|---|
| 文件 | `web/components/evaluation/retrieval-ablations-page.tsx` 1214 行 |
| dataset 选择 + 单 run 创建 | ✅ |
| Leaderboard 表(6 metric) | ✅ retrieval_mrr / recall / ndcg@10 / ndcg@20 / faithfulness_det / refusal_correctness |
| Base vs Target diff | ✅ metric_diffs + param_diffs |
| HTML 导出 + Bundle JSON 导出 | ✅ |
| 检索模式 | hybrid / vector / keyword / mmr |
| 关键参数 UI | top_k / score_threshold / alpha / mmr_lambda / vector_weight / keyword_weight / reranker_provider / reranker_top_n |
| **批量笛卡尔网格 UI** | ❌ 仅 CLI 有 |
| **统计显著性** | ❌ |
| **>2 run 对比矩阵** | ❌ 仅 base vs target |
| **参数敏感度** | ❌ |
| **Pareto 前沿** | ❌ |
| **自动调参** | ❌ |
| **实验跟踪标准化(MLflow/W&B)** | ❌ |

### 1.3 38 个可调参数(已支持)

`scripts/retrieval_ablation.py:_RUN_PARAM_FIELDS` 定义,涵盖:
- **profile**:retrieval_profile
- **query 改写**:enable_query_alias_expansion / query_alias_max_queries / enable_multi_query / multi_query_count / multi_query_temperature / enable_query_rewrite / query_rewrite_strategy
- **hierarchy**:enable_hierarchy_recall / hierarchy_family_collapse / hierarchy_family_aggregation / hierarchy_tree_dedup / hierarchy_parent_depth / hierarchy_sibling_window / hierarchy_overfetch_factor
- **sparse**:sparse_retrieval_enabled / sparse_retrieval_provider
- **检索核心**:top_k / score_threshold / retrieval_mode / alpha
- **fusion**:fusion_strategy / fusion_budgets / fusion_min_scores / fusion_weights
- **加权重排**:enable_weight_rerank / vector_weight / keyword_weight / mmr_lambda
- **reranker**:enable_reranker / reranker_provider / reranker_top_n
- **prompt**:prompt_template_id / prompt_template_key / prompt_ab_experiment_key

---

## 2. 业界 RAG 消融实验全景(2024-2026)

### A. 实验跟踪与可视化平台

| 平台 | 核心能力 | 开源? | 与 MimirQ |
|---|---|---|---|
| **MLflow** | 实验追踪 + 参数/metric/artifact + UI + Model Registry | ✅ Apache 2.0 | **业界事实标准**,Python 生态最成熟 |
| **W&B (Weights & Biases)** | Sweeps 超参搜索 + 报告 + alerts | 商业(免费层) | 可视化最强,sweep config YAML |
| **W&B Sweeps** | grid / random / bayes 三策略 + early stop | 商业 | bayes 比 grid 快 3-10× |
| **Comet ML** | 类 W&B,Optimizer 模块 | 商业(免费层) | 适合多团队 |
| **TensorBoard hparams** | 经典超参对比 | ✅ | 简单场景够用 |
| **Aim** | 开源 W&B 替代,UI 极快 | ✅ Apache 2.0 | 大量实验首选 |
| **Neptune.ai** | 商业 | 商业 | 略小众 |

### B. 自动调参(HPO)

| 工具 | 算法 | 与 MimirQ |
|---|---|---|
| **Optuna** | TPE / CMA-ES / NSGA-II 多目标 / pruner | **首选**,Python 原生,Dashboard 完善 |
| **Ray Tune** | ASHA / PBT / BOHB,分布式 | 大规模实验 |
| **Hyperopt** | TPE 早期实现 | 已被 Optuna 超越 |
| **Sigopt** | 商业贝叶斯优化 | 闭源 |
| **Ax (Meta)** | 贝叶斯 + bandit | PyTorch 生态 |
| **scikit-optimize** | 经典贝叶斯 | 简单实验 |
| **AutoRAG** (开源) | **专门做 RAG 调参** | 强相关,值得借鉴 |

### C. RAG 专项评测/调参框架

| 工具 | 能力 | 关键 |
|---|---|---|
| **AutoRAG** (Marker-Inc) | 自动评测 + 节点选择 + 配置生成 | **直接对标**,YAML 配置驱动 |
| **RAGAS** | 4 大 metric(faithfulness/answer relevancy/context precision/recall) | 已集成 |
| **TruLens** | RAG triad + leaderboard | 评测 |
| **LangSmith Experiments** | dataset × runner × evaluator 矩阵 | 商业 |
| **Promptfoo** | prompt × test 矩阵 + assertion + red team | 矩阵对比标杆 |
| **DeepEval** | pytest 化评测 + CI 报告 | CI 友好 |
| **BEIR** | 18 数据集统一接口 | 检索 benchmark 黄金标准 |
| **MTEB** | embedding 模型 leaderboard | 模型选型 |
| **TREC-Eval** | 经典 IR(MRR/NDCG/MAP) | metric 实现参考 |
| **GraphRAG-Bench**(ICLR'26) | KG-RAG benchmark | 已记入 deep-research plan |
| **CRUD-RAG** | 中文 RAG 基准 | 已记入 eval-dataset plan |

### D. 统计显著性与实验设计

| 方法 | 用途 | 在 RAG 的应用 |
|---|---|---|
| **Paired t-test** | 同 query 配对差异 | 两 run 比较 |
| **McNemar's test** | 离散结果(对/错) | retrieval@k 命中率 |
| **Bootstrap CI** | 任意 metric 置信区间 | 默认应有 |
| **Wilcoxon signed-rank** | 非正态配对 | 长尾 metric |
| **Friedman test** | >2 system 同时比较 | leaderboard 显著性 |
| **Benjamini-Hochberg** | 多重比较校正 | 多 metric 同时报 |
| **Cohen's d / Cliff's delta** | 效应量 | "差异有多大" |
| **Power analysis** | 决定样本量 | dataset 规模设计 |
| **Sobol indices** | 全局敏感度 | 38 参数中哪个最重要 |
| **Pareto front (NSGA-II)** | 多目标 | metric vs latency vs cost |
| **One-Factor-At-a-Time (OFAT)** | 单因素扫描 | 最朴素的 ablation |
| **Plackett-Burman / Fractional Factorial** | 减少 grid 大小 | 38 参数 cartesian 不可行 |
| **Latin Hypercube Sampling** | 高效采样 | 替代 random search |

### E. CI/CD 集成

| 工具 | 用途 |
|---|---|
| **GitHub Actions / GitLab CI matrix** | 矩阵作业 |
| **Argo Workflows / Kubeflow Pipelines** | 复杂 pipeline |
| **Prefect / Dagster** | 数据流编排 |
| **promptfoo CI** | PR 上跑 prompt eval |
| **DeepEval CI** | pytest 化 |
| **GitHub Issue Forms + Bot** | 实验报告自动评论 |

### F. 业界关键论文/文档(2024-2026)

- **AutoRAG: Automated Framework for optimization of Retrieval Augmented Generation Pipeline** (NAACL 2025)
- **HyperRAG: Empower Trade-off in RAG with HyperParameter Optimization** (arxiv 2024)
- **A Survey of RAG: Foundations, Models, Applications**(2024) — 评测章节
- **RAGBench**(NeurIPS 2024)— 标准化评测
- **Vectara NAACL 2025** — chunk size ablation 反直觉结论
- **Chroma Context Rot**(2025)— 上下文长度 ablation
- **FloTorch 54%**(2024)— 错误 ablation 误导决策案例

---

## 3. Gap 分析(MimirQ vs 业界 SOTA)

| 能力 | 业界 SOTA | MimirQ 现状 | Gap | 优先级 |
|---|---|---|---|---|
| 笛卡尔批量 ablation | W&B Sweeps / Optuna grid | ✅ 后端 CLI / ❌ 前端 | **前端 UI 缺** | **P0** |
| 统计显著性(paired t-test/bootstrap) | RAGAS confidence + Promptfoo CI | ❌ | 完全缺 | **P0** |
| 多 run 对比矩阵(>2) | W&B / MLflow | ❌ 仅 base vs target | **缺 N×M 矩阵** | **P0** |
| Per-case 失败钻取 | LangSmith / Promptfoo | ❌(只有 metric 级) | 缺 case-level diff | **P0** |
| 参数敏感度(Sobol) | Optuna importance | ❌ | 缺 | P1 |
| Pareto 前沿(metric vs latency/cost) | Optuna NSGA-II / Ax | ❌ | 缺 | P1 |
| 自动调参(贝叶斯/TPE) | Optuna / Ray Tune | ❌ 仅 grid | 缺 | P1 |
| 实验跟踪标准化 | MLflow / W&B / Aim | ❌ 自建表 | **lock-in 风险** | P1 |
| Per-param impact 雷达 | Optuna importance plot | ❌ | 缺 | P1 |
| Effect size(Cohen's d) | RAGAS / DeepEval | ❌ | 缺 | P2 |
| Power analysis(样本量决定) | scipy.stats | ❌ | 缺 | P2 |
| Multi-objective(Pareto) | Optuna NSGA-II | ❌ | 缺 | P2 |
| AutoRAG 风格自动节点选择 | AutoRAG | ❌ | 战略空白 | P3 |
| BEIR/MTEB 标准接口 | BEIR | ❌ | 缺业界对齐 | P3 |
| Prompt × Retrieval 矩阵 | Promptfoo | ❌ 仅 prompt_ab_experiment_key 配置项 | 缺正交矩阵 UI | P2 |
| Slice-based eval(by category/domain) | LangSmith | ❌ | 缺垂类切片 | P2 |

---

## 4. 推荐方案:三层升级架构

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3 — 战略层(P2/P3,自动化与生态)                         │
│   - Optuna 贝叶斯 HPO + Pareto 前沿                              │
│   - AutoRAG 风格节点自动选择                                     │
│   - BEIR/MTEB 标准接口                                           │
│   - MLflow Tracking 接入(实验跟踪标准化)                       │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2 — 深度分析(P1,1-2 月)                                 │
│   - 参数敏感度热力图(Sobol / Optuna importance)               │
│   - Per-param impact bar chart                                  │
│   - Multi-objective Pareto plot(metric × latency × cost)       │
│   - Slice-based eval(by query category/intent/domain)          │
│   - Prompt × Retrieval 正交矩阵 UI                              │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1 — 严谨性补齐(P0,2-3 周)                              │
│   - 前端笛卡尔网格 UI(对齐 CLI 能力)                          │
│   - Bootstrap CI + Paired t-test + BH 校正                      │
│   - N×M 多 run 对比矩阵(echarts heatmap)                      │
│   - Per-case 失败钻取(query 级别表格 + diff)                 │
│   - 显著性标注(*: p<0.05, **: p<0.01)                         │
└──────────────────────────────────────────────────────────────────┘
```

**核心设计原则**:
1. **后端为主,前端补能力**:CLI 已有的功能优先暴露到前端,而不是另起炉灶
2. **统计严谨先于花哨**:置信区间和显著性是底线,缺它的 leaderboard 都是"伪科学"
3. **Per-case 钻取是杀手锏**:聚合 metric 上升不等于真的好,要看到"哪些 query 变好/变坏"(对齐 POC plan 差评分类)
4. **多目标必须显式**:metric 提升 1pt 但延迟翻倍,几乎必然不值;Pareto 是默认视图
5. **OTel 协同**:复用上一份可视化 plan 的 OTel span 提取 latency/cost,避免重复埋点

---

## 5. P0 落地任务(2-3 周交付)

### 5.1 前端笛卡尔网格 UI(~600 行)

**新建** `web/components/evaluation/ablation-grid-panel.tsx`:
- YAML/JSON 编辑器(可复用 monaco)定义 grid:`{retrieval_mode: ["hybrid","vector"], top_k: [10,20,50], reranker_provider: ["llm","bge","none"]}`
- 提示组合数(防止误操作生成 1000+ runs)
- 调用新增后端 `/api/v1/evaluations/ragas/regression/ablation/batch`
- 进度条显示 N/M runs 完成
- 完成后跳转 leaderboard

**后端**:
- `app/api/v1/evaluations.py` 新增 `POST /ragas/regression/ablation/batch`,接收 grid + base 参数
- 复用 `scripts/retrieval_ablation.py:expand_param_grid` 函数(`scripts/` 下函数提到 `app/services/`)
- 异步执行(已有 Celery/RQ 或 BackgroundTasks)
- 返回 ablation_id + run_ids 列表

### 5.2 统计显著性引擎(~400 行)

**新建** `app/services/regression_run_significance.py`:
- 输入:base run + target run(都需有 per-case 数据)
- 输出:
  - paired t-test p-value
  - Wilcoxon p-value(非正态备份)
  - Bootstrap 95% CI(metric_diff)
  - Cohen's d 效应量
  - McNemar(对 retrieval@k 命中)
- 多 metric 同时报时走 BH 校正
- 依赖:`scipy.stats`(应已有,核对 `pyproject.toml`)

**前端**:`retrieval-ablations-page.tsx` diff tab 新增"显著性"列,展示 `p=0.003 ** [-0.012, +0.045]` 形式

### 5.3 N×M 多 run 对比矩阵(~300 行)

**新建** `web/components/evaluation/ablation-comparison-matrix.tsx`:
- 选择 N 个 run(checkbox)+ M 个 metric
- 用 echarts heatmap:行=run / 列=metric,色阶=value,单元格=`value (Δ vs base)`
- 点击单元格 → 显示参数 diff(已有 paramDiffRows 逻辑可抽离)
- 旁边小图:scatter `latency vs primary_metric`,初步 Pareto 直观感受

### 5.4 Per-case 失败钻取(~400 行)

**新建** `web/components/evaluation/ablation-case-drilldown.tsx`:
- 选两个 run → 显示所有 case 的 metric 对比表
- 颜色:绿(提升 >5%)/ 灰(无变化)/ 红(下降 >5%)
- 行点击展开:question / base_contexts / target_contexts / base_answer / target_answer / 标签(改善/退化/无变化)
- 标签来源:已有 `app/services/regression_run_diff.py` 输出 `case_diffs`(若没有则新增)
- 导出 CSV(对齐 POC plan 的 5 字段埋点习惯)

**后端**:`app/services/regression_run_diff.py` 增加 `include_per_case=True` 选项,返回 per-case metric

### 5.5 Bootstrap & CI 配置

**修改** `app/rag/evaluation/ragas.py`:
- `run_regression_ragas_evaluation` 新增 `n_bootstrap=1000` 参数
- 输出每个 metric 的 `value` + `ci_lower` + `ci_upper`
- DB schema 加 `metric_ci_lower` / `metric_ci_upper` 字段(Alembic 迁移)
- 默认 dataset >= 30 cases 才开启 bootstrap(power 不够时静默跳过)

---

## 6. P1 落地任务(1-2 个月)

### 6.1 参数敏感度分析

**新建** `app/services/regression_sensitivity_analysis.py`:
- 收集同一 dataset 上 N 个 ablation runs 的 (params, metric)
- 算 Sobol indices 或 Optuna `get_param_importances`
- 输出 `{param: importance_score}`

**前端**:`ablation-sensitivity-bars.tsx` echarts 横向 bar,显示 top 10 重要参数

### 6.2 Pareto 前沿

**新建** `web/components/evaluation/pareto-frontier-plot.tsx`:
- 散点:x = primary metric,y = latency(或 cost)
- 算 Pareto 前沿(简单 O(n²) 即可)
- 高亮前沿点;hover 显示参数
- 用 plotly scatter(已用)

### 6.3 自动调参

**新建** `app/services/optuna_tuner.py`:
- 包装 Optuna study,objective = -primary_metric(若多目标:NSGA-II)
- 每个 trial 调 `run_regression_ragas_evaluation`(已有)
- 持久化:Optuna 自带 SQLAlchemy storage,可复用项目 PG
- CLI:`scripts/run_optuna_ablation.py`
- 前端 P1.1 暂不做 UI,先用 Optuna Dashboard(`optuna-dashboard` 包)

### 6.4 MLflow Tracking 接入

**新建** `app/services/mlflow_logger.py`:
- 在 `run_regression_ragas_evaluation` 末尾 log params + metrics + artifact(bundle)
- MLflow Server 走 Docker 单容器
- 收益:获得"实验对比 / 模型注册 / artifact 浏览"开箱即用

### 6.5 Slice-based eval

**修改** `app/services/regression_leaderboard.py`:
- 接收 `slice_by` 参数(query.intent / domain / difficulty)
- 输出每个 slice 的 metric
- 前端用 echarts grouped bar,横轴 slice,系列=run

### 6.6 Prompt × Retrieval 正交矩阵

- 复用 `prompt_template_key` + `retrieval_profile`,前端 2D 矩阵
- 单元格颜色编码 primary metric

---

## 7. P2/P3(季度计划)

- **P2**:Power analysis 工具(给定 effect size + p<0.05 + power=0.8 反推所需 cases)
- **P2**:Effect size 排行榜(不只 p-value,看实际差异)
- **P2**:Multi-objective Pareto with cost & safety(safety plan 的 ASR<5% 作为约束)
- **P3**:**AutoRAG 风格节点自动选择**——给定数据集 + 预算,系统输出最优 pipeline 配置
- **P3**:BEIR / MTEB 标准接口(`scripts/run_beir_eval.py` + dataset 适配器)
- **P3**:实验报告自动生成(对齐 IBM Champion Blueprint 的 SO Reparser,LLM 写 Markdown 报告)
- **P3**:GitOps 实验(每个实验是一个 PR,CI 自动跑 + 评论)

---

## 8. 关键文件清单

**修改**:
- `app/api/v1/evaluations.py`(新增 `/ablation/batch` + `include_per_case` + `slice_by`)
- `app/services/regression_leaderboard.py`(slice 支持)
- `app/services/regression_run_diff.py`(per-case + significance)
- `app/rag/evaluation/ragas.py`(bootstrap CI)
- `app/api/schemas/regression.py`(新字段)
- `web/components/evaluation/retrieval-ablations-page.tsx`(集成新组件)
- `web/lib/api/evaluation.ts`(新方法)
- `scripts/retrieval_ablation.py`(`expand_param_grid` 提到 service 层)

**新建**:
- `app/services/regression_run_significance.py`
- `app/services/regression_run_ablation_batch.py`
- `app/services/regression_sensitivity_analysis.py`(P1)
- `app/services/optuna_tuner.py`(P1)
- `app/services/mlflow_logger.py`(P1)
- `web/components/evaluation/ablation-grid-panel.tsx`
- `web/components/evaluation/ablation-comparison-matrix.tsx`
- `web/components/evaluation/ablation-case-drilldown.tsx`
- `web/components/evaluation/ablation-sensitivity-bars.tsx`(P1)
- `web/components/evaluation/pareto-frontier-plot.tsx`(P1)
- `scripts/run_optuna_ablation.py`(P1)
- `scripts/run_beir_eval.py`(P3)
- `tests/test_regression_run_significance.py`
- `tests/test_regression_ablation_batch.py`
- Alembic 迁移:`migrations/versions/xxxx_add_metric_ci.py`

**复用**(零修改):
- `scripts/run_nightly_ablations.py`(可叠加 batch)
- `scripts/retrieval_ablation.py`(逻辑提到 service)
- 已有依赖:scipy / plotly / echarts / monaco

---

## 9. 验证方法

1. **后端单测**:`pytest tests/test_regression_run_significance.py tests/test_regression_ablation_batch.py -v`
2. **CLI 烟测**:
   ```bash
   python scripts/retrieval_ablation.py --dataset-id <uuid> \
     --grid '{"retrieval_mode":["hybrid","vector"],"top_k":[10,30]}'
   ```
3. **前端联调**:`/evaluations/ablations` 创建 grid → 看到 4 个 runs 排队 → leaderboard 显示带 CI 的 metric → 选 2 个 runs 显示显著性
4. **Per-case 钻取联调**:点选 base+target → 钻取页显示绿/红 case 数量 → 点行展开 query+contexts diff → 导出 CSV 字段齐全
5. **N×M 矩阵联调**:选 4 个 runs × 6 metrics → heatmap 渲染 → hover 显示参数 diff
6. **Bootstrap CI**:同一 run 跑 2 次,CI overlap 应高(无显著性);改 top_k 应有显著差异
7. **Optuna 集成**(P1):跑 100 trials → optuna-dashboard 显示参数重要性 + Pareto
8. **MLflow 集成**(P1):runs 在 MLflow UI 出现,artifact 可下载
9. **完整验证**:`pnpm verify` + `pytest tests/` 全绿

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 笛卡尔展开生成数千 runs 跑爆 LLM 配额 | UI 显示组合数 + 上限 50 + 默认 retrieval-only 不调 LLM(对齐 nightly 默认) |
| Bootstrap 慢 | 默认 1000 次,最多 5000;<30 cases 自动跳过;计算放后台 |
| 多重比较"刷 p-value" | 强制 BH 校正显示;前端标注"已校正" |
| Optuna trial 失败 | 用 Optuna pruner 早停;失败 trial 不污染 study |
| MLflow 数据库爆炸 | 配置 retention(对齐 `regression_run_retention.py`) |
| Per-case 数据隐私 | 与 trace 同步走 Presidio 脱敏(对齐 safety + viz plan) |
| Pareto 前沿误读 | UI 提示"前沿点不一定全局最优,仍需领域判断" |
| 实验"过拟合" eval set | 强制 train/dev/test 切分;eval 结果不允许调参回流(对齐 PoC plan) |

---

## 11. 与已有调研的关系

- 与 `plans/rag-eval-dataset-deep-dive-2026-q2.md` 的"先松后紧 4 阶段评测集"配对:本计划是**评测集的使用方法论**
- 与 `plans/rag-poc-attribution-framework-2026-q2.md` 的"5 字段埋点 + 差评三分类"协同:per-case 钻取直接消费这些字段
- 与 `plans/rag-visualization-deep-dive-2026-q2.md`(刚完成)协同:消融的可视化(矩阵/Pareto/敏感度)是其 P1/P2 的具体实例
- 与 `plans/rag-deep-research-2026-q2.md` 的 cost tracker 协同:Pareto 前沿的 cost 轴消费此数据
- 与 `plans/rag-ibm-champion-blueprint-2026-q2.md` 的 chunking_grid 300/50 对照协同:本计划提供运行此对照的工具
- 与 `plans/rag-context-expansion-rerank-2026-q2.md` 的 855 问评测集协同:用本计划的 ablation 框架跑该评测集
- 与 `plans/rag-auto-tagging-services-2026-q2.md` 的 LLM tagger 协同:tagger 的 8-12 维标签可作为 slice-based eval 的切片维度

---

## 12. 关键洞察

1. **MimirQ ablation 工程化已在第一梯队,但缺统计严谨性**:1214 行前端 + 1087 行后端 CLI 是真投入,但没有 CI 也没有 effect size,容易被"看起来提升了"误导(对齐 FloTorch 54% 陷阱)
2. **Per-case 钻取价值远大于聚合 metric**:聚合提升 0.5pt 可能掩盖"30% case 退化 + 30% case 改善"的内部巨变
3. **Pareto 是 RAG 调参的默认视图**:任何 ablation 不附 latency/cost 都是耍流氓
4. **38 参数全笛卡尔不可行**:必须做 Plackett-Burman 或 fractional factorial 缩减,Optuna 贝叶斯比 grid 快 3-10×
5. **AutoRAG 思路是终态**:输入数据集 + 预算,系统自动产出最优 pipeline,这是产品差异化的关键(对齐 PoC plan 的"行业规则库护城河")
6. **MLflow/W&B 不是炫技,是 lock-in 解药**:自建 regression_run 表迁移到任何标准平台都成本高,先打 OTLP/MLflow 接口
7. **统计显著性是底线**:任何 leaderboard 不显示 CI 都是误导用户,这是 P0 不能砍的需求

---

## 13. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口。

已落地:
- P0 严谨性闭环:前端笛卡尔网格、后端 batch run、统计显著性、N×M 对比、per-case drilldown。
- 轻量 P1 决策辅助:切片差异面板、Pareto 前沿、参数影响排序。
- 实现原则:只消费当前 OpenAPI / regression run / diff payload,不新增平台级依赖。

暂缓:
- 暂缓 Optuna / Bayesian HPO / NSGA-II,当前 run 规模和操作频次不足以支撑自动调参平台。
- 暂缓 MLflow / W&B / Aim,先保留自建 regression run 闭环,避免引入额外部署面。
- 暂缓 BEIR / MTEB / AutoRAG,这些属于研究或 benchmark 体系,不影响当前产品闭环。
- 暂缓 Sobol / power analysis,当前页面只做观测相关提示,不伪装成因果或统计设计结论。

Directive: 后续如果要继续扩展,从真实产品问题或线上实验 ticket 开始,不要再按本文档逐项推进。
