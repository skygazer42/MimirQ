# 后端 RAG 能力升级总索引（2026-Q3）——七域 plan 导航与开发顺序

> 日期：2026-07-13 ｜ 基于当日全后端核查（证据 file:line 见各分 plan）
> 范围：RAG 能力本身——解析 / 切块 / 入库 / 召回 / 治理 / 验证 / KG 七域。任务可靠性、多租户、限流等平台项不在此列（既定排除）。

## 七域 plan 清单

| 域 | plan | 一句话 | 核心缺口 |
|---|---|---|---|
| 召回 | `rag-recall-enterprise-latency-neutral-2026-q3.md` | 延迟中性三创新：Tri-Pass 一次编码三路召回 / 分级路由 / 冲突感知融合 | 默认形态弱、决策脑薄、知识冲突=0 |
| 治理 | `rag-governance-destub-2026-q3.md` | Guard 三桩换真模型 + 红队真基线 + 五类归因 + chunk-ACL | **红队在测桩，ASR 自欺**（政务宣称风险） |
| 验证 | `rag-verification-judge-2026-q3.md` | 独立 llm_judge 三防偏 + 金标 κ 自证 + ragas.py(2543 行)拆分 | 裁判散落且无抗偏机制 |
| 解析 | `rag-parsing-quality-harness-2026-q3.md` | parse_bench harness + Docling 装配 + 置信度传播 | 指标齐但 harness 是 13 行空壳 |
| 切块 | `rag-chunking-adaptive-2026-q3.md` | questions 字段补全 + 网格打分 + 自适应选择器 | 消费侧等 questions（factory.py:153）、策略无裁决尺 |
| 入库 | `rag-ingestion-incremental-2026-q3.md` | 分阶段重试 + 增量重嵌 + 死信运营 | 三个"全量思维"残留，费钱费时 |
| KG | `rag-kg-depth-2026-q3.md` | 全局实体消解 + 增量装载 + plan_on_graph 裁决制加厚 | 规划器 36 行、消解停在文档内 |
| 反馈 | `rag-feedback-loop-ops-2026-q3.md` | 差评三分类落库 + 反馈→评测集转化 + 微调数据定期化 | 闭环骨架已接线但三分类无结构化字段（models/feedback.py:41 自由文本） |

## 建议开发顺序（依赖驱动，非重要度排序）

```
第 1 批（并行，互不依赖，全是止血/地基）：
  ├─ 治理 P0：Guard 去桩 + 红队真基线        ← 对外宣称风险，独立可做
  ├─ 验证 P0：llm_judge + 金标 κ             ← 一切 A/B 的裁判前置
  ├─ 切块 P0-1：questions 生成               ← 3 人日小项，立即多处受益
  └─ 反馈 P0：三分类落库 + 评测 case 转化    ← 验证域"动态评测集"的活水源

第 2 批（依赖第 1 批裁判）：
  ├─ 召回 P0：双基线 + 三 A/B + 三档 profile  ← A/B 需 llm_judge
  ├─ 解析 P0：parse_bench harness + 标注集    ← 报告用统一裁判
  └─ 切块 P0-2：chunking grid（复用解析标注集）

第 3 批（依赖第 2 批产物）：
  ├─ 入库 P0：分阶段重试 + 增量重嵌           ← 增量重嵌是"生产切 embedding"前置
  ├─ 召回 P1：Tri-Pass + 分级路由 + 冲突融合  ← embedding 切换后收益最大化
  └─ KG P0：实体消解 + 增量装载              ← 增量装载吃入库 delta 三分类

第 4 批（按门槛触发）：
  └─ 各域 P1/P2：plan_on_graph 裁决、MUVERA、自适应切块、表格端到端…
```

## 三条贯穿性纪律（各 plan 共同约定）

1. **裁决制**：薄实现/存疑功能（plan_on_graph、HyDE、RAPTOR、late_chunking 双实现）一律给"证明自己或退场"的 A/B 门槛，不无限养着。
2. **闭环制**：离线评测结论必须闭环回线上配置（channel budget policy 模式推广到切块选择器、解析路由）。
3. **延迟红线**：任何质量增强不得破坏召回计划的延迟中性总账；贵活只进 quality profile。

## 已知未列入项（有意排除）

- 五巨文件拆分（retriever 9082 / integrations_dify 7616 / processor 6676 …）：`run_retrieval` 拆分在召回 plan P2-3，其余待功能改动错峰后单独立项，避免重构与功能互相踩。
- OTel 阶段级 span：观测专项，待与平台项一起规划（stage 速度告警的最小版已并入入库 plan P1-2）。
- Qwen3-Embedding 默认切换：不是独立 plan，是召回 plan P0-2① 的 A/B 结论执行。

## 后端覆盖度地图（2026-07-13 全量核查收口）

**已深查并立 plan（8 域）**：召回（retrieval/reranker/embedding/config 默认值全查）、治理（safety 三桩+红队+隔离）、验证（evaluation 全目录）、解析（parsing/quality+enrich+deepdoc 结构）、切块（chunking 策略+factory+matrix）、入库（processor/ingestion_run/dead_letter/indexer）、KG（search 20+ 模块/extraction/loading）、反馈（feedback_loop 三件+models/feedback）。

**已扫、无立项级缺口**：`app/query/`（287 行规范化/扩展工具层）、`rag/workflows/`（chain/crag_streaming/critic/flare/planner_worker 等全家桶）、`rag/agents/`（multi_agent/rag_agent）、`rag/memory/`（short/long_term）、`rag/middleware/`（含 pii.py 挂点——治理 plan 的 presidio 替换直接可挂）、`rag/output/`（空壳，装配在 engine/orchestrator 内）、`rag/pipelines/langgraph.py`。

**发现缺口但按门槛暂缓（记录在案）**：`app/connectors/` 仅 DB catalog（10 个 py），企微/钉钉/飞书/SharePoint 等企业数据源连接器为零——既定路线是 MCP 生态（`rag-agent-rag-boundary-2026-q4.md`）；**决策门槛：首个客户点名要企业 IM/网盘增量同步时立项**，届时与入库域增量重嵌（delta 三分类）对接 connector cursor 即可。

**明确排除（用户既定）**：任务队列可靠性、多租户、限流、测试覆盖、API 平台项。
