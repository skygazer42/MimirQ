# RAG 切块域升级计划（2026-Q3）——questions 字段补全 + 网格打分 + 自适应选择器

> 日期：2026-07-13 ｜ 前置调研：`plans/rag-parsing-chunking-deep-dive-2026-q2.md`、`plans/rag-chunk-preview-deep-dive-2026-q2.md`
> 定位：79 策略 18118 行是弹药库，但三个缺口让它打不准：**消费侧已期待的 questions 字段生成侧缺**（HyDE/multi-query 的原料）、**strategy_matrix 是静态规则不是打分出来的**、**没有网格 harness 证明哪个策略对哪类文档最优**。切块是"上游一错、下游全错"的杠杆位。

## Context（2026-07-13 核实）

- **questions 字段缺口有硬证据**：`app/rag/chunking/factory.py:153` 已检查 `meta.get("document_summary") or meta.get("document_questions")`——消费侧留好了位，生成侧 `llm_tagger.py`(213 行) 只出 summary+8 类标签，questions 未生成
- **strategy_matrix.py 1013 行**：静态选择矩阵（含 "auto" 字符串项），非按文档特征打分自选；chunking grid 打分 harness 缺
- 策略资产：late_chunking + late_chunking_jina 双实现、contextual_enrichment（Anthropic 式上下文补写）、parent_child、raptor、token_300_50、semantic min-floor 256、Context Cliff 2500 分级监测（quality_scorer.py）
- 上游联动：解析域 harness（`rag-parsing-quality-harness-2026-q3.md`）产出文档类型标签，是自适应选块的输入

## 落地设计

### P0-1 LLM 三字段补全：questions 生成（最快见效的一项）
- `llm_tagger.py` 扩展：每 chunk/文档生成 3-5 条"该内容能回答的问题"（中文），写入 `document_questions`——factory.py:153 的消费逻辑立即生效。
- 三个下游立刻受益：① HyDE 用真 questions 替代凭空生成的假设文档（直击"HyDE 可能有害"的噪声根源——检索空间里有真问题锚点）；② multi-query 扩展有种子；③ 问题-问题匹配通道（query 对 questions 的相似度）作为可选召回信号，成本仅一次离线生成。
- 成本控制：入库时批量生成（arq 异步，不阻塞主管线），失败降级为无 questions（现状）。

### P0-2 chunking grid 打分 harness（回答"哪个策略对哪类文档最优"）
- 结构对齐解析域 harness：`策略 × 文档类型` 网格，每格跑 切块→嵌入→检索→judge 评分（裁判用验证域统一 llm_judge），输出 recall@10 / faithfulness / 平均块长 / Cliff 触发率 / 成本 五指标。
- 首轮网格：5 策略（token_300_50 / semantic / parent_child / late_chunking / contextual_enrichment）× 4 文档类（法规条款/红头公文/长报告/表格密集），复用解析域 80 篇标注集。
- **两个 Q2 悬案借此裁决**：① Vectara 反直觉结论（fixed-size 常胜）在我们的中文政务语料是否成立；② late_chunking 双实现留谁。
- 前端 `/chunk-preview` 的"网格打分"P0（既定）以此为后端。

### P1-1 自适应切块选择器（strategy_matrix 升级为数据驱动）
- 输入：文档特征（类型标签/长度/表格密度/标题层级深度——解析侧全有）；决策：查 grid 网格结果表选最优策略；`strategy_matrix.py` 的静态规则降级为网格无数据时的 fallback。
- **本质是把 P0-2 的离线结论闭环回线上**（对齐检索侧 channel budget policy 的消融闭环模式，`config.py:1159` 先例）。
- 切换门槛：自适应 vs 现状默认在 holdout 集 +3pt 才默认开。

### P1-2 切块质量在线监测闭环
- Cliff 分级监测（已有）+ 块长分布漂移 + questions 覆盖率，进 ingestion 报告；劣化文档自动打回 reprocess 建议（与入库域 plan 的分阶段重试衔接——只重跑 chunk 阶段）。

### P2 进阶
- RAPTOR 生产化验证：已有实现但默认价值未证，网格里加一行裁决去留。
- 多粒度并存索引（同文档 128/512/2048 三粒度，按 query 复杂度选粒度）——与召回计划 MRL 粗精两段呼应，先出 RFC 再动手。

## 优先级矩阵

| 优先级 | 任务 | 工作量 | 落点 |
|---|---|---|---|
| P0 | questions 生成 + HyDE/multi-query 接线 | ~3 人日 | `llm_tagger.py` + query_expansion |
| P0 | chunking grid harness（5×4 首轮） | ~5 人日 | `evaluation/`（对齐 parse_bench 结构） |
| P1 | 自适应选择器（网格结果闭环） | ~4 人日 | `chunking/strategy_matrix.py` |
| P1 | 在线监测 + 打回建议 | ~3 人日 | quality_scorer + ingestion 报告 |

## 验证与门槛
- questions 上线即测：HyDE(真 questions) vs HyDE(生成) vs 无 HyDE 三臂 A/B——与召回计划 P0-2③ 合并跑，一次实验裁决两个 plan 的悬案。
- 网格报告是唯一策略话语权来源：今后任何"换默认切块策略"的讨论必须引用网格数据。

## 不做什么
- 不再新增切块策略（79 个远超需求，先用网格裁汰）；不做 LLM 逐块改写（成本不可控，contextual_enrichment 已够）；多粒度索引不在 Q3 动手（存储 ×3，先证收益）。
