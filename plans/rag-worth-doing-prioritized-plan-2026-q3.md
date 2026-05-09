# 本轮 RAG 计划项筛选结果（2026 Q3）

> 当前决策：本轮只推进两条线：
>
> 1. **Math / Formula / Chart RAG**
> 2. **Feedback Loop**
>
> 其他计划暂时不纳入本轮，不继续拆任务，也不作为近期执行入口。

## 0. 本轮范围

| 来源 plan | 本轮结果 | 说明 |
| --- | --- | --- |
| `rag-multimodal-math-chart-2026-q3.md` | **进入本轮** | 做 Stage 1：schema、Golden、轻量公式计算、报告切片。 |
| `rag-feedback-loop-2026-q3.md` | **进入本轮** | 做 Stage 1：feedback → hard negative / rules 候选；fine-tune 暂缓。 |
| `rag-cross-doc-synthesis-2026-q3.md` | 暂不纳入 | 暂时不做跨文档冲突呈现。 |
| `rag-self-consistency-2026-q3.md` | 暂不纳入 | 暂时不做 K-path / 多路径投票。 |
| `rag-agentic-memory-2026-q3.md` | 暂不纳入 | 暂时不做长期 Agentic Memory。 |
| `rag-gap-and-recommendations-summary-2026-q2.md` | 仅作背景 | 行业规则/中文 benchmark 后续可单独拆，不混入本轮。 |

## 1. Math / Formula / Chart RAG

来源：`plans/rag-multimodal-math-chart-2026-q3.md`

### 1.1 已完成，不再作为任务

| 原计划项 | 结果 | 说明 |
| --- | --- | --- |
| [x] 确认 Chart-to-Data / Formula OCR / Vision Reader / TAG bridge 已存在 | 已完成 | 现状已校准。 |
| [x] 确认 `chart_data` / `formula` chunk type 已有分类和子索引 | 已完成 | 后续继续复用。 |
| [x] 修复图表数值 query 被“多少/占比”等表格词误路由成 table 的问题 | 已完成 | Stage 0 已处理。 |
| [x] 保持显式 SQL / 聚合 table query 仍走 table | 已完成 | 回归边界正确。 |
| [x] 跑局部回归测试 | 已完成 | 后续保持测试即可。 |

### 1.2 本轮需要做

| 原计划项 | 本轮结果 | 调整后任务 | 理由 |
| --- | --- | --- | --- |
| [x] Chart data schema v1 + cache key | 已完成 | 定义稳定 schema：`chart_id`、`page`、`series`、`unit`、`confidence`、`source_image`、cache key | 图表数据没有稳定 schema，后续评测、引用、缓存都不稳。 |
| [x] 轻量 formula calculator（不引 Wolfram，SymPy 作为后续选项） | 已完成 | 做可控表达式 calculator，不接 Wolfram，不强依赖 SymPy | 先解决常见公式代入和简单计算，不把范围扩大到符号数学。 |
| [ ] 20-30 条 multimodal Golden 样本 | 需要 | 建 chart / formula / table-math 三类小样本集 | 先用小 Golden 证明这条线是否值得继续。 |
| [x] Golden 回归页接 chart/formula/table-math 切片 | 已完成 | 在 Golden 结果里展示图表、公式、表格数学的失败类型 | 没有切片就无法定位多模态错误。 |
| [ ] 报告展示：数值误差、证据命中、成本 | 需要 | 报告包含 tolerance、evidence hit、vision/compute 成本 | 数值类问题不能只看通用相关性。 |
| [ ] 默认对含图表 / 公式的 query 启用 | 需要但收窄 | 只在 router 命中 chart/formula 且数据集中存在相关 chunk 时启用 | 不做“所有含图表词都启用”，避免成本和误路由。 |
| [ ] 客户演示 demo | 需要 | 做 5-10 个真实财报/图表/公式问题 demo | 这条线适合用可视化 demo 验证价值。 |
| [ ] 配置文档 | 需要 | 说明 chart/formula/table 的路由边界、配置项、成本注意事项 | 防止后续误改 router 和成本策略。 |

### 1.3 本轮不做

| 原计划项 | 本轮结果 | 说明 |
| --- | --- | --- |
| [ ] SymPy / Wolfram 可选接入 | 暂缓 | 先预留接口，不接入外部重型求解器。 |
| [ ] ChartQA / PlotQA / DocGenome benchmark 适配 | 暂缓 | 先跑自建 Golden，公开 benchmark 后置。 |
| [ ] 大规模 badcase 反哺与缓存成本治理 | 暂缓 | 先做小规模 badcase 标记和基本 cache key。 |

## 2. Feedback Loop

来源：`plans/rag-feedback-loop-2026-q3.md`

### 2.1 本轮需要做

| 原计划项 | 本轮结果 | 调整后任务 | 理由 |
| --- | --- | --- | --- |
| [x] `dispatcher.py` skeleton + 监听 feedback insert | 已完成（收窄） | 做手动/定时 batch dispatcher，不做实时监听 | 实时监听会让反馈即时影响系统，风险偏高。 |
| [x] `hard_negative_promoter.py` + 复用 mining 接口 | 已完成 | 复用现有 mining，把负反馈转 hard negative 候选 | 这是 feedback 最直接的质量反哺入口。 |
| [x] HardNeg 端到端：差评 → JSONL 验证 | 已完成 | 从差评生成可审计 JSONL，并保留 dataset / conversation / message 来源 | 能证明 feedback 不是只存起来，而是进入评测资产。 |
| [ ] `rules_enricher.py` 差评 → glossary 候选 | 需要 | 只生成规则/术语候选，不自动生效 | 和行业规则后续产品化强相关，但要保留人工审核。 |
| [x] 与 P0-1 行业规则库 UI 集成（候选侧栏） | 已完成（收窄） | 本轮先提供候选数据/API；UI 可先接最小列表 | 不把行业规则整页重做混进本轮。 |
| [x] 端到端测试 | 已完成 | 覆盖 feedback → classify → hardneg/rules candidate | 反馈反哺链路必须避免污染数据。 |
| [x] 三元组构造逻辑 | 已完成（收窄） | 只做离线 export，不接训练 | 三元组数据有价值，但本轮不 fine-tune。 |
| [ ] A/B 评测集成（rag-ablation 框架） | 需要但收窄 | 只保留离线对比入口，不自动上线 | 后续可用于验证 reranker/检索策略，但本轮不做自动 promote。 |
| [x] `loop-dashboard.tsx` 三路指标 | 已完成（收窄） | 改成两路指标：HardNeg 候选、Rules 候选 | 本轮不做 fine-tune，所以不需要三路 dashboard。 |
| [x] 飞轮速度 baseline | 已完成（收窄） | 统计“负反馈 → 可用候选”的转化率 | 比抽象飞轮指标更可执行。 |
| [ ] 客户演示文档 | 需要 | 写最小演示：差评如何变成候选样本/候选规则 | Feedback Loop 很适合 PoC 解释。 |
| [ ] 完整 SOP | 需要但收窄 | 写最小 SOP：生成、审核、导出、回滚 | 不写厚文档。 |

### 2.2 本轮不做

| 原计划项 | 本轮结果 | 说明 |
| --- | --- | --- |
| [ ] `reranker_finetuner.py` 框架 | 暂缓 | 反馈量和 A/B 门禁不足，不写训练框架。 |
| [ ] sentence-transformers 微调代码 | 暂缓 | 暂不做模型训练。 |
| [ ] minio 上传 + model registry | 暂缓 | 没有训练闭环前不需要。 |
| [ ] 自动 promote 逻辑 | 不做 | 明确禁止自动上线。 |
| [ ] Prometheus 指标暴露 | 暂缓 | 先用 API/page summary。 |
| [ ] OTel 埋点 | 暂缓 | 当前不是链路追踪瓶颈。 |

## 3. 暂不纳入本轮

这些不是永久不做，只是当前不进入执行：

| 计划 | 暂不做的原因 |
| --- | --- |
| Cross-Doc Synthesis | 当前优先级不够，且假冲突/成本治理需要更多 Golden 基础。 |
| Self-Consistency | 成本和延迟较高，暂时不做 K-path 投票。 |
| Agentic Memory | 隐私、forget/export、错误记忆治理复杂，后置。 |
| MCP marketplace | 属于生态分发，不是本轮 RAG 质量闭环。 |
| Output Guard 模型扩容 | 属于安全合规专项，不和本轮混做。 |
| 公开 benchmark 全量适配 | 先做自建小 Golden，公开 benchmark 后续再评估。 |

## 4. 本轮最终执行清单

### 本次已落地（2026-05-08）

Math / Formula / Chart RAG：

- [x] Chart data schema v1 + stable cache key
- [x] 轻量 formula calculator（无 Wolfram / 无强制 SymPy）
- [x] Golden run summary 接入 `chart/formula/table_math/image/text` 切片统计
- [x] Golden 页面展示切片失败类型
- [ ] 20-30 条 multimodal Golden 样本
- [ ] 数值误差 / tolerance / 成本报告

Feedback Loop：

- [x] 负反馈 → HardNeg 候选 API（只读，不自动写入）
- [x] 负反馈 → 训练三元组候选
- [x] 负反馈 → Rules 候选（只读，不自动生效）
- [x] feedback → candidate 服务接线与端到端测试
- [x] 反馈页两路 dashboard summary 与转化率 baseline
- [x] batch dispatcher / JSONL 持久导出
- [ ] reranker fine-tune / model registry / 自动 promote

### Math / Formula / Chart RAG

- [x] Chart data schema v1 + cache key
- [x] 轻量 formula calculator
- [ ] 20-30 条 multimodal Golden 样本
- [x] Golden 回归页接 chart/formula/table-math 切片
- [ ] 报告展示数值误差、证据命中、成本
- [ ] router 命中 chart/formula 且存在相关 chunk 时启用
- [ ] 客户演示 demo
- [ ] 配置文档

### Feedback Loop

- [x] batch dispatcher
- [x] `hard_negative_promoter.py`
- [x] 差评 → HardNeg JSONL 验证
- [ ] `rules_enricher.py`
- [x] 规则/术语候选 API 或最小列表
- [x] feedback → candidate 端到端测试
- [x] 离线三元组 export
- [ ] ablation 离线对比入口
- [x] 两路 dashboard summary
- [x] 负反馈转可用候选转化率 baseline
- [ ] 客户演示文档
- [ ] 最小 SOP
