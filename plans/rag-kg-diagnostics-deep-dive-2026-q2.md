# KG 诊断(`/graph/diagnostics`)调研 — 现状评估 + 自研深化路线

## Context

**触发场景**:用户从 `/graph/diagnostics` 出发,要求对 KG 诊断能力做全面调研,**约束:不引大包,优先自研**。这是 MimirQ 评估"知识图谱抽取质量 + KG 检索质量"的核心工具——给定 dataset 中的 RAGAS 回归用例,跑 baseline KG search,生成 hardcase(deterministic / LLM 两种),输出 hit@k / mrr / recall + 失败归因 + KG 提取 preflight,可持久化 run 用于跨时序 diff。

**问题**:工程化骨架完整(后端 ~1500 行 + 前端 1174 行),**但深度 ≠ 广度**:① metric 只有 5 个核心 IR 指标,**缺 NDCG / MAP / Path Accuracy / Triple F1 / Subgraph Coverage** 等 KG-RAG 专项;② 缺**KG 本体质量诊断**(孤立节点 / 重复实体 / 关系密度 / 类型覆盖 / 置信度分布);③ 缺**LLM 抽取质量评测**(extraction precision/recall vs 人工);④ 缺**多跳推理诊断**(对齐 ToG/PoG agentic search);⑤ 缺**端到端链路诊断**(question→KG→answer 全栈追溯);⑥ hardcase **未闭环到训练/微调反哺**(主动学习);⑦ 前端 **per-case drilldown 缺子图可视化**(与 9084 行 /graph 不联动);⑧ 缺**时序漂移监控**(KG 越用越脏吗?)。本调研对标业界(GraphRAG-Bench ICLR'26 / KGQA / ToG / PoG / D-RAG EMNLP'25 / LC-QuAD / WebQSP),**全部自研补齐**。

---

## 1. 现状盘点(已确认)

### 1.1 后端实现(~2200 行)

| 文件 | 行数 | 角色 |
|---|---|---|
| `app/rag/evaluation/kg_search_diagnostics.py` | **1068** | 主诊断引擎(seed 自 RAGAS cases,baseline + hardcase 对比) |
| `app/services/hardcase_discovery_service.py` | 467 | hardcase 候选发现(feedback 联动 + parse-risk 派生) |
| `app/rag/evaluation/kg_hardcase_deterministic.py` | 259 | 确定性 hardcase 生成(无 LLM,可复现) |
| `app/rag/evaluation/kg_hardcase_generator.py` | - | LLM 版 hardcase 生成 |
| `app/api/schemas/kg_diagnostics.py` | 149 | Pydantic schemas(请求/响应/run 持久化) |
| `app/rag/evaluation/kg_search_diagnostics_metrics.py` | 72 | hit@k / mrr / recall 算法 |

**API 路由**:`/api/v1/evaluations/kg/search/diagnostics`(持久化可选)+ run 列表 + 详情

### 1.2 前端实现

| 文件 | 行数 | 角色 |
|---|---|---|
| `web/components/graph/kg-diagnostics-page.tsx` | **1174** | 主诊断页(3 view:run / quality / compare) |

**视图**:
- `run`:发起诊断 + 实时结果
- `quality`:质量摘要(metric tile)
- `compare`:跨 run diff(类似 snapshot 思路)

**已展示 metric**(从 `KGSearchRunMetrics`):
1. `hit_at_k`(布尔)
2. `mrr`(0-1)
3. `recall`(0-1)
4. `matched_evidence_chunks`
5. `total_evidence_chunks`

**Hardcase 模式 3 种**:`off` / `deterministic`(无 LLM) / `llm`(temperature=0.2)

**Hardcase 类型 2 种**:`knowledge_pressure` / `reasoning_pressure`

**归因**:`KGEvalAttribution.primary_cause`(other / kg_extraction_missing / kg_search_miss / event_only / entity_only / etc.)

**Preflight 检查**:KG 是否已抽取(auto_extract_kg=true 时自动补)

### 1.3 与已有 KG 模块的关系

- 输入种子:`RagasRegressionCase`(已有评测体系的 case)
- 调用 `KGSearcher`(`app/rag/kg/search/searcher.py`)
- 关联 `KgEntity / KgEventEntity / KgRelation / KgSourceEvent` 模型
- Hardcase 候选可来自 feedback(用户差评)+ parse-risk 派生
- 与 `app/rag/kg/snapshot.py` 同一 KG 数据但**未联动**

### 1.4 10 大缺口

1. ❌ **metric 维度过窄**:仅 5 个,业界 KG-RAG ≥15 个未实现
2. ❌ **KG 本体质量 metric** 完全缺(孤立节点 / 重复实体 / 关系密度 / 置信度分布)
3. ❌ **LLM 抽取质量评测** 缺(extraction precision/recall vs 人工标注)
4. ❌ **多跳推理诊断** 缺(对齐 ToG/PoG/Plan-on-Graph 的步骤级评测)
5. ❌ **端到端链路诊断** 缺(question → KG search → context → answer 全链路 trace)
6. ❌ **Hardcase 闭环训练** 缺(主动学习反哺 → 抽取/检索改进)
7. ❌ **per-case 子图可视化** 缺(钻取时不展示具体子图,与 /graph 9084 行不联动)
8. ❌ **时序漂移监控** 缺(KG 质量随时间变化趋势)
9. ❌ **成本 / 延迟分布** 缺(KG search p50/p95/p99)
10. ❌ **诊断报告导出** 仅 JSON,缺客户可读 HTML

---

## 2. 业界 KG-RAG 诊断全景(2024-2026)

### A. 标准 benchmark(参考 / 适配,不直接接入)

| Benchmark | 类型 | 借鉴点 |
|---|---|---|
| **GraphRAG-Bench** (ICLR'26) | KG-RAG 端到端 | 已有 `graphrag_bench.py` 57 行雏形 |
| **WebQSP** (Microsoft) | 多跳 KGQA | semantic parser 风格 |
| **GrailQA** | KGQA + compositional | 多跳 + zero-shot |
| **LC-QuAD 2.0** | 大规模 KGQA | 复杂 SPARQL |
| **MetaQA** | 电影 KG QA(1-3 hop) | 多跳难度分级 |
| **MultiHop-RAG** | 多跳 RAG | 对齐 ablation plan |
| **ToG / PoG** trace | agentic search | **逐步诊断范式** |
| **CRAG** (Meta) | 综合 RAG | 已规划 |
| **HotpotQA / 2WikiMultiHop** | 多跳 QA | 已规划 |

### B. KG 本体质量 metric(学术)

| Metric | 用途 | 自研成本 |
|---|---|---|
| **Schema Coverage** | 实体类型 / 关系类型 vs ontology | 50 行 |
| **Density**(`E / N²`) | 图稀疏程度 | 10 行 |
| **Connectivity**(连通分量数) | 孤岛检测 | 50 行(BFS) |
| **Orphan Ratio**(孤立节点比) | 提取质量信号 | 20 行 |
| **Duplicate Entity Rate** | 同名实体融合质量(用 BGE 余弦) | 100 行 |
| **Avg Confidence** / **Confidence Distribution** | 边的置信度分布 | 50 行 |
| **Type Distribution Skew** | 类型不均衡 | 50 行 |
| **Triple F1**(已有 hardcase 思路) | 抽取 vs 人工 | 100 行 |
| **Path Accuracy** | 多跳路径正确性 | 150 行 |
| **Subgraph Coverage** | 子图召回 | 100 行 |
| **Centrality Drift**(对齐 snapshot plan) | 重要节点变化 | 100 行 |
| **Bridge Entity Recall** | 桥节点是否在答案中 | 50 行 |

### C. KG-RAG 诊断范式(论文)

- **ToG (ICLR'24)** beam search → 每步可诊断:expand / score / prune 是否合理
- **PoG (WWW'25)**:Plan-on-Graph 的步骤级 LLM 评分
- **D-RAG (EMNLP'25)**:Diagnostic RAG,显式归因 retrieval miss / generation miss
- **LazyGraphRAG** (Microsoft 2025):成本 -99.9% 但需诊断"何时退化"
- **HippoRAG** (NeurIPS'24)PPR 召回:诊断 PPR 步数 / damping
- **AAAI'26 AutoGraph-R1**:RL 训练 + 评测一体化

### D. 排除大包(用户约束)

| 工具 | 排除原因 |
|---|---|
| **DeepEval / TruLens / Phoenix** | 全套依赖太重(已在 evaluation plan 排除) |
| **GraphRAG visualizer**(MS Streamlit) | Streamlit 全栈太重 |
| **Neo4j Bloom / yWorks** | 商业 |
| **OpenKE** / **PyKEEN** | 偏 KG embedding 训练,与诊断不同场景 |
| **KGEval** (学术) | 论文工具非工程产品 |

**结论**:**全部自研** metric 实现,只复用现有 KG 模块 + RAGAS regression cases。

---

## 3. Gap 分析(MimirQ vs 业界 SOTA)

| 维度 | 业界 SOTA | MimirQ 现状 | Gap | 优先级 |
|---|---|---|---|---|
| 检索 IR metric 全套 | NDCG/MAP/Hit@K | 仅 hit@k/mrr/recall | 缺 NDCG / MAP | **P0** |
| KG 本体质量 metric | 学术标准 | ❌ | **完全缺**(产品差异化) | **P0** |
| LLM 抽取质量评测 | 内部 benchmark | ❌ | 抽取黑盒 | **P0** |
| 多跳推理诊断 | ToG/PoG step trace | ❌ | 与 KG-viz plan agentic-replay 协同 | **P0** |
| 端到端链路诊断 | D-RAG attribution | 仅归因主因 1 级 | 缺多级 attribution | P1 |
| Per-case 子图可视化 | GraphRAG visualizer | ❌(JSON only) | 不与 /graph 联动 | **P0** |
| 时序漂移监控 | yFiles temporal | ❌ | 缺 trend 看板 | P1 |
| 成本/延迟分布 | OTel | ❌ | 与 viz plan OTel 协同 | P1 |
| Hardcase → 训练闭环 | AutoGraph-R1 | ❌ | 缺反哺 | P2 |
| 客户 HTML 报告 | 商业 | ❌ JSON only | 与 snapshot plan 一致 | P1 |
| Triple F1 抽取评测 | 学术 | 已有 kg_hardcase 雏形 | 缺人工标注流水 | P1 |
| Path Accuracy | ToG/PoG | ❌ | 缺路径级评分 | P1 |
| 诊断结果分类钻取 | LangSmith | 仅 1 级 primary_cause | 缺多维切片 | P1 |
| Hardcase 多样性度量 | 学术 | ❌ | 防止 hardcase 集中 | P2 |
| KG 推荐 fix(LLM) | 商业 | ❌ | 给出可执行修复建议 | P3 |
| Online 监控告警 | OTel + Grafana | ❌ | 仅离线诊断 | P3 |

---

## 4. 推荐方案:四层自研架构

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 4 — 战略(P3,长尾)                                       │
│   - Hardcase → 训练闭环(主动学习)                            │
│   - LLM 推荐 fix(可执行修复建议)                              │
│   - Online 监控告警(SLO + Grafana 联动)                       │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3 — 时序与报告(P1,1 月)                                 │
│   - 时序漂移趋势图(metric × time)                             │
│   - 成本/延迟分布(p50/p95/p99)                                │
│   - 客户 HTML 单文件报告(对齐 snapshot plan)                  │
│   - Hardcase 多样性度量                                        │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2 — 多跳与归因深化(P0.B / P1)                            │
│   - **多跳推理诊断**(ToG/PoG step trace,与 KG-viz agentic-replay) │
│   - **多级 attribution**(retrieval/extraction/generation 三层)│
│   - Per-case 子图可视化(联动 /graph 9084 行)                   │
│   - Triple F1 / Path Accuracy / Subgraph Coverage 评测         │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1 — 度量补齐(P0,2-3 周)                                 │
│   - **KG 本体质量 metric 12 个**(density / orphan / duplicate / etc.) │
│   - **LLM 抽取质量评测**(precision / recall vs 人工)         │
│   - 检索 metric 补全(NDCG / MAP / Hit@K)                       │
│   - 前端 metric tile 5 → 18+,折叠为分类                        │
└──────────────────────────────────────────────────────────────────┘
```

**核心设计原则**:
1. **零新依赖**:全部自研在 `app/rag/evaluation/kg_*` + `web/lib/graph-diagnostics-*`
2. **复用 RAGAS cases**:不另建评测集,继续用 `RagasRegressionCase` 作为种子
3. **复用 9084 行 /graph**:per-case 钻取直接跳 `/graph?case_id=...` 加载子图,不另建画布
4. **复用 KG-viz plan algorithms**:Louvain / Quad-tree / PageRank / BFS k-hop
5. **复用 evaluation plan llm_judge**:LLM 评分走统一框架(P0 已规划)
6. **复用 snapshot plan content-addressed**:诊断 run 也走 blake3 去重 + GitOps 树

---

## 5. P0 落地任务(2-3 周纯自研)

### 5.1 KG 本体质量 metric 12 个(~500 行)

**新建** `app/rag/evaluation/kg_ontology_health.py`:
- `compute_density(G)`:`|E| / (|N| * (|N|-1))`
- `compute_connectivity(G)`:连通分量数 + 最大分量大小占比(BFS)
- `compute_orphan_ratio(G)`:0-degree 节点 / 总数
- `compute_duplicate_entity_rate(G, sim_threshold=0.92)`:用 BGE-M3(已有)算同名实体余弦,>阈值算重复
- `compute_avg_confidence(G)` + `confidence_distribution(G)`:边置信度均值 + 分位数(p10/p50/p90)
- `compute_type_distribution_skew(G)`:基尼系数衡量类型不均衡
- `compute_schema_coverage(G, ontology)`:出现的 type vs ontology 定义
- `compute_relation_density(G)`:平均出度
- `compute_bridge_node_ratio(G)`:Betweenness top-1% 节点占比
- `compute_centrality_distribution(G)`:PageRank top-10 集中度

**输出**:`KGOntologyHealthReport { density, orphan_ratio, duplicate_rate, ... }`

**前端**:`kg-diagnostics-page.tsx` quality view 增加"本体质量"分类区,12 个 metric tile

### 5.2 LLM 抽取质量评测(~400 行)

**新建** `app/rag/evaluation/kg_extraction_eval.py`:
- 输入:小批人工标注 chunks(50-100 个,带 ground-truth 实体/关系)
- 跑当前抽取 pipeline → 输出实体/关系
- 计算:
  - Entity Precision/Recall/F1
  - Relation Precision/Recall/F1(triple 级别)
  - 错误分类:`missed / spurious / wrong_type / wrong_predicate`
- 输出 confusion matrix
- 与 hardcase deterministic 同源思路,可复用 `_collapse_ws` 等工具

**前端**:`kg-extraction-quality-panel.tsx`(~200 行)展示 P/R/F1 + confusion matrix(echarts heatmap)

### 5.3 检索 IR metric 补全(~150 行)

**修改** `app/rag/evaluation/kg_search_diagnostics_metrics.py`(72 → ~250 行):
- 已有:hit_at_k / mrr / recall
- 新增:NDCG@k / MAP / Hit@1 / Hit@3 / Hit@5 / Hit@10 / Precision@k
- 输出扩展 `KGSearchRunMetrics`(schema 兼容,旧字段保留)

### 5.4 多跳推理诊断(~500 行)

**新建** `app/rag/evaluation/kg_multihop_eval.py`:
- 输入:case + KG search trace(对齐 KG-viz plan agentic-replay 数据源)
- 计算:
  - **Path Accuracy**:LLM-Judge 评估推理路径每一步是否正确(对齐 ToG)
  - **Bridge Entity Recall**:多跳问题的"桥节点"是否在 retrieval 结果
  - **Step-level Score**:每个 expand step 的命中率
  - **Hop Count Distribution**:实际跳数分布
- 标记 case 为 `1-hop / 2-hop / 3+-hop`

**前端**:在 `kg-diagnostics-page.tsx` per-case drilldown 加 step-by-step 视图

### 5.5 Per-case 子图可视化联动(~250 行)

**修改** `kg-diagnostics-page.tsx`:
- 每个 case 行加"在画布查看"按钮 → 跳 `/graph?case_id=xxx&mode=diagnostic`
- 传递 baseline.events / entities 作为子图过滤
- /graph 端识别 `?case_id` 参数,只渲染该 case 关联子图 + 高亮 ground-truth 边

**修改** `web/app/graph/use-graph-data-loading.ts`:
- 接收 case_id 参数,从 KG 诊断 API 拉子图

### 5.6 前端 metric tile 重构(~200 行)

**修改** `kg-diagnostics-page.tsx`(1174 行,部分区域改造):
- 当前 5 个 tile → 18+ 分类:
  - **检索质量**:hit@1/3/5/10 / mrr / ndcg@10 / map / recall / precision@10
  - **本体质量**:density / orphan_ratio / duplicate_rate / avg_confidence
  - **抽取质量**:entity F1 / relation F1
  - **多跳**:path_accuracy / bridge_recall
- 折叠/展开,默认 5 个核心 + "查看更多"

### 5.7 单测(~400 行)

- `tests/test_kg_ontology_health.py`:density / orphan / duplicate 经典图样例
- `tests/test_kg_extraction_eval.py`:正例 / 漏抽 / 多抽 / 类型错
- `tests/test_kg_multihop_eval.py`:1-3 hop case 路径正确性

---

## 6. P1 落地任务(1 月)

### 6.1 多级 attribution(~300 行)

**修改** `KGEvalAttribution`:
- 现 1 级 `primary_cause` → 多级:
  - `extraction_layer`:missing_entity / missing_relation / wrong_type
  - `retrieval_layer`:no_match / low_score / wrong_path
  - `ranking_layer`:not_in_top_k / order_wrong
  - `generation_layer`:context_ignored / hallucination
- 每级独立信号 + 决策树自动归因

### 6.2 时序漂移监控(~400 行)

**新建** `app/services/kg_diagnostics_trend.py`:
- 自动 daily snapshot 触发诊断 run
- 趋势图:每个 metric × 时间(7d / 30d / 90d)
- 异常告警:metric 7d 移动平均下降 >5% 触发 notice
- 前端 `kg-diagnostics-trend-chart.tsx`(~250 行)用 recharts(已有)

### 6.3 成本/延迟分布(~200 行)

**修改** `kg_search_diagnostics.py`:
- 每个 case 记录 `latency_ms` + `tokens_used`
- 输出 `summary.latency_p50/p95/p99` + `summary.cost_total`
- 前端 echarts 直方图

### 6.4 客户 HTML 单文件报告(~400 行)

**新建** `app/services/kg_diagnostics_report.py`:
- 单文件 HTML(对齐 snapshot plan 5.6.4 + Pre-POC scanner 三原则)
- 内嵌 echarts SVG / 表格 / 语义总结(LLM)
- Presidio 脱敏选项

### 6.5 Hardcase 多样性度量(~150 行)

**新建** `app/rag/evaluation/kg_hardcase_diversity.py`:
- 计算 hardcase 集合的 embedding 余弦相似度矩阵
- 输出 `diversity_score`(平均 1 - cos)
- 防止 LLM 生成的 hardcase 过于集中

### 6.6 Triple F1 完整流水(~300 行)

- **新建** 人工标注 UI:`web/app/datasets/[id]/triple-annotation/page.tsx`
- 每 chunk 标注 `triples: [(s, p, o), ...]`
- 后端 store + 与 5.2 评测对接

---

## 7. P2/P3(季度计划)

### P2

- **Hardcase 训练闭环**:
  - 收集 fail case 自动加入 RAGAS regression set
  - 反哺 chunk-level fine-tune(若用本地 embedding)
  - 主动学习选取最高信息量 case
- **LLM 推荐 fix**:基于诊断结果生成"建议修复"清单
  - "实体 X 与 Y 应合并"
  - "关系 P 在 chunk Z 中漏抽"
  - 一键应用 → 写入 KG
- **诊断结果切片**:按 query intent / domain / hop count 多维切片

### P3

- **Online 监控告警**:接入 Prometheus + Grafana(对齐 viz plan OTel)
- **SLO 自动评估**:每日定时跑诊断 → 对照 SLO 阈值
- **多 KG 对比 leaderboard**:多个抽取策略的诊断对照
- **AI 辅助归因**:LLM 自动生成"为什么这个 case 失败"的自然语言报告

---

## 8. 关键文件清单

**修改**(增强):
- `app/rag/evaluation/kg_search_diagnostics.py`(1068,加 IR metric + multihop hook)
- `app/rag/evaluation/kg_search_diagnostics_metrics.py`(72 → ~250,补全 IR metric)
- `app/api/schemas/kg_diagnostics.py`(149,扩 schema)
- `app/api/v1/evaluations.py`(暴露新 endpoints)
- `web/components/graph/kg-diagnostics-page.tsx`(1174 行重构 metric tile + 子图联动)
- `web/lib/api/evaluation.ts`(新方法)
- `web/app/graph/use-graph-data-loading.ts`(支持 case_id 参数)

**新建**(纯自研):
- `app/rag/evaluation/kg_ontology_health.py`(P0)
- `app/rag/evaluation/kg_extraction_eval.py`(P0)
- `app/rag/evaluation/kg_multihop_eval.py`(P0)
- `app/services/kg_diagnostics_trend.py`(P1)
- `app/services/kg_diagnostics_report.py`(P1)
- `app/rag/evaluation/kg_hardcase_diversity.py`(P1)
- `web/components/graph/kg-extraction-quality-panel.tsx`(P0)
- `web/components/graph/kg-diagnostics-trend-chart.tsx`(P1)
- `web/components/graph/kg-multihop-step-view.tsx`(P0)
- `web/app/datasets/[id]/triple-annotation/page.tsx`(P1)
- 单测:`test_kg_ontology_health.py` / `test_kg_extraction_eval.py` / `test_kg_multihop_eval.py` / `test_kg_hardcase_diversity.py`

**复用**(零修改 + 协同):
- `app/rag/evaluation/kg_hardcase_deterministic.py`(259 行)
- `app/rag/evaluation/kg_hardcase_generator.py`
- `app/services/hardcase_discovery_service.py`(467 行)
- `app/rag/kg/searcher.py`(KG search 引擎)
- `app/rag/kg/snapshot.py`(provenance 联动)
- `app/rag/embedding/`(BGE-M3 算 duplicate entity)
- 现有依赖:scipy / numpy / recharts / echarts(无新增)
- evaluation plan 的 `llm_judge.py`
- KG-viz plan 的 Louvain / PageRank / BFS k-hop
- snapshot plan 的 content-addressed + HTML 报告框架

**后端配合**:
- `app/services/security_redaction.py`(报告脱敏)
- `app/services/document_permission_service.py`(诊断 ACL)

---

## 9. 验证方法

1. **本体质量单测**:`pytest tests/test_kg_ontology_health.py -v` — density / orphan / duplicate 经典图样例
2. **抽取评测单测**:50 标注样例上 P/R/F1 输出合理(>0.7 baseline)
3. **多跳诊断单测**:1-3 hop case 路径正确性 + 桥节点识别
4. **API 烟测**:
   ```bash
   curl -X POST /api/v1/evaluations/kg/search/diagnostics \
     -d '{"dataset_id":"...","include_ontology_health":true,"include_multihop":true}'
   ```
5. **前端联调**:`/graph/diagnostics` 跑诊断 → quality view 显示 18+ metric tile → 点 case → 跳 `/graph?case_id=...` 显示子图 + 高亮 ground-truth
6. **多跳 step view**:展开 case → 显示 3-hop trace + 每步评分
7. **趋势图**(P1):查看 30d 趋势 → metric 下降时 banner 提示
8. **HTML 报告**(P1):导出 → 打开浏览器 → 单文件含 12+ metric + 表格 + LLM 总结
9. **完整验证**:`pnpm verify` + `pytest tests/test_kg_*.py -v` 全绿

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 12 个本体 metric 大 KG 慢 | 走 worker 异步;分级缓存(snapshot blake3 命中复用);>10w 节点采样 |
| LLM 抽取评测需人工标注 | P0 提供 50 样例脚手架;P1 上 UI 流水;Triple F1 不要求大规模 |
| 多跳诊断 trace 缺失 | 需 KG plan 的 agentic_beam_search 落地;未落地时降级到 1-hop |
| 子图可视化 case_id 参数泄漏 | ACL 严格透传(`document_permission_service`) |
| 客户报告 PII 泄露 | 默认 Presidio 脱敏(对齐 safety + Pre-POC + snapshot plan) |
| metric 18+ 信息过载 | 默认折叠 + 按重要度排序 + 5 个核心保留首屏 |
| Duplicate entity rate 误判 | 余弦阈值可调;输出"待人工确认"列表;不自动合并 |
| 趋势图历史数据缺失 | P1 先记录从今往后,P3 backfill 历史 |
| 报告 HTML 内嵌 echarts SVG 大 | 复用 snapshot plan 的 echarts SSR 方案 |
| Hardcase 多样性低 | diversity_score 阈值告警;触发时切换 deterministic 模式 |

---

## 11. 与已有调研的关系

- 与 `plans/rag-kg-deep-research-2026-q2.md`:本计划 5.4 多跳诊断**直接消费** KG plan P0 `agentic_beam_search.py` trace;ontology 一致性是其延伸
- 与 `plans/rag-kg-visualization-self-built-2026-q2.md`:5.5 子图联动复用其 Quad-tree LOD;P1 趋势图复用 viz plan 时序动画思路
- 与 `plans/rag-kg-snapshot-deep-dive-2026-q2.md`(刚完成):本计划诊断 run 持久化复用其 content-addressed + GitOps 树;影响分析联动
- 与 `plans/rag-evaluation-deep-dive-2026-q2.md`:LLM-Judge 框架(P0)是本计划多跳诊断的依赖;Triple F1 / Path Accuracy 是其 KG 专项 metric 的实现
- 与 `plans/rag-ablation-deep-dive-2026-q2.md`:诊断结果可作为 ablation 的目标 metric;统计显著性框架可复用
- 与 `plans/rag-poc-attribution-framework-2026-q2.md`:差评三分类(检索不到/答错/超纲)直接对接本计划多级 attribution
- 与 `plans/rag-eval-dataset-deep-dive-2026-q2.md`:诊断种子来自 RAGAS regression case,评测集 4 阶段建设直接受益
- 与 `plans/rag-pre-poc-scanner-2026-q2.md`:HTML 单文件报告原则一致
- 与 `plans/rag-safety-compliance-deep-dive-2026-q2.md`:Presidio 脱敏在客户报告强制
- 与 `plans/rag-auto-tagging-services-2026-q2.md` LLM tagger:抽取的标签可作为 type_distribution_skew 的输入

---

## 12. 关键洞察

1. **诊断不是"看 metric"而是"找根因"**——MimirQ 现状只显示 5 个 metric 数字,缺多级 attribution + 子图钻取,没法解答"为什么 fail";这是产品差异化的关键
2. **KG 本体质量被严重忽视**:大家只看 retrieval metric,但 KG 越用越脏(orphan / duplicate)是 RAG 退化的主因;P0 12 个本体 metric 是真护城河
3. **不引大包是对的**:KGEval / OpenKE / PyKEEN 都偏研究,生产环境自研 200-500 行 Python 完全覆盖
4. **多跳诊断与 KG-viz agentic-replay 同源**:trace 数据复用,前端动画 + 后端评分一份数据两个用途
5. **子图联动是 9084 行 /graph 的复利**:不另建画布,加一个 query 参数就能让诊断"看得见"
6. **Triple F1 评测必须建人工标注流水**:LLM 抽取评测无人工 ground truth 都是自欺;50 样例脚手架是 P0 必做
7. **时序漂移监控比一次性诊断更重要**:KG 是活的,P1 必须建趋势看板,否则线上回归看不到
8. **Hardcase 多样性是隐藏陷阱**:LLM 生成的 hardcase 容易"换汤不换药",多样性度量必须在 P1 加入

---

## 13. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口.

已落地:
- 后端闭环:KG diagnostics run 已支持执行、可选持久化、run 列表/详情、run diff 与 `/api/v1/evaluations/kg/quality/report` 聚合质量报告.
- 指标闭环:`compute_kg_hit_metrics` 新增 `ndcg` 与 `map`,`KGSearchRunMetrics` 和 summary 聚合新增 baseline/hardcase NDCG@K、MAP@K.
- 前端闭环:`/graph/diagnostics` 首屏显式展示 Hit Rate、MRR、Recall、NDCG@K、MAP@K、Hardcases,质量页继续承接抽取层聚合诊断.
- 测试闭环:补充 NDCG/MAP 单测与前端 source test,保持 run persistence schema 兼容.

暂缓:
- 人工标注驱动的 Triple F1 / extraction precision-recall.
- 多跳推理 step trace、Path Accuracy、Subgraph Coverage.
- per-case 子图联动、时序漂移趋势和客户 HTML 报告.
- Hardcase 主动学习/训练反哺与 LLM fix 建议.

Directive: 当前 KG diagnostics 先覆盖可落地的检索质量与抽取健康度;没有人工标注集前不要伪造 extraction F1 或自动修复闭环.
