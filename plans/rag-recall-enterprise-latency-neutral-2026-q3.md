# 召回强化·延迟中性计划（2026-Q3）——一次编码三路召回 + 分级路由 + 冲突感知融合

> 日期：2026-07-13 ｜ 来源：2026-07-13 召回策略专查（见 memory `2026-07-code-reality-check.md` 补充节）
> 定位：**在不压低召回速度的前提下，把默认召回形态从"1.5 通道、无重排、2024 底座"提升到企业级**。核心判断：现状默认链路从未做过延迟优化（跨海 embedding API + 应用层融合 + 缓存全关），所以存在一个罕见窗口——**提质与提速可以同时发生，这不是 trade-off**。

## Context（现状诊断，全部已核实）

- 账面四通道，默认 ~1.5 通道：SPARSE(`config.py:1103`)/COLBERT(`:1126`)/BM25 二级(`:1077`)默认关且 provider 为 deterministic 桩；lexical DB 在 hybrid 下仅 fallback(`:1071`)
- `ENABLE_RERANKER: False`(`config.py:1729`)；HyDE/multi-query/rewrite/intent-router 全关；语义缓存/候选缓存也默认关(`:190-197`)
- 默认 embedding = `text-embedding-3-small`(`config.py:338`)，注册表里 bge-m3/Qwen3-0.6B 躺平未用；ZH/EN 语言路由字段留空(`:342-344`)
- 决策脑薄：`complexity_classifier.py` 27 行正则 + `engine.py:467` 长度打分，却决定 top_k 10↔40 与 agentic 门控(`engine.py:955`)
- 知识冲突整合 = 0（全库仅 `kg/api/routes.py:71` HTTP 409）
- **关键资产已就位但未接线**：pymilvus==2.6.11（原生 sparse+hybrid_search 全支持，代码零使用）；`bge_m3_triplet.py` 三态 payload 骨架（schema `mimirq.bge_m3_triplet.v1`，未接真模型）；`matryoshka.py` 已有按复杂度标签选维函数（256/512/1024）；影子 collection 蓝绿迁移先例(`indexer.py:116`)；通道预算离线消融闭环(`config.py:1159`)；显著性检验全套(`regression_run_significance.py` 271 行)

## 设计原则：延迟中性三定律

1. **配对记账**：每加一个贵环节，必须先省一个更贵的（本计划最大的"省"= embedding 本地化 + 融合下沉服务端）。
2. **贵活路由化**：重排/扩展/agentic 只给需要它的查询，靠分级路由把均摊延迟压住；简单查询走 fast path。
3. **下沉优先**：能在单次前向做的不做两次调用（triplet 一次编码出三态），能在 Milvus 服务端做的不在应用层做（原生 hybrid 融合）。

每项变更过双门禁：质量（显著性检验）+ 延迟（**硬约束，2026-07-14 用户确认：不得影响查询速度**——默认路径 p50/p95 不得高于变更前基线，原"≤5% 容忍带"作废；任何增时环节必须在其抵消项**实测落地之后**才可进默认路径，否则只能进 opt-in profile 或异步旁路）。

---

## P0（第 1-2 周）：默认形态达标 + 建立双基线（零/极少新代码）

### P0-1 延迟与质量双基线（一切"中性"承诺的前提）
- 从 `mimirq.retrieval_trace_pass.v1` trace 与 metrics 拉近 30 天检索段 p50/p95 分布，按 stage 拆解（embed/ann/fusion/rerank/expand）。
- 质量基线：政务自建集 + CRUD-RAG 中文子集，recall@10 / nDCG@10 / citation_coverage。
- 产出：SLO 草案（建议检索段 p95 ≤ 800ms 起谈）+ 本文档延迟账表用实测数替换估算数。

### P0-2 三个决策性 A/B（复用显著性栈，全是"改一行默认值"级收益）
1. **embedding 默认切换**：`text-embedding-3-small` → `BAAI/bge-m3`，测 siliconflow 与本地 vllm 两种部署形态，中文集优先。预期质量 +（中文代差）且延迟 **-**（本地 GPU ~10-30ms vs 跨海 API 100-300ms）。同时把 `EMBEDDING_MODEL_ZH/EN`(`config.py:342`) 语言路由配起来。
2. **重排默认开启**：`ENABLE_RERANKER=True` + `cross_encoder`（bge-reranker-v2-m3，top-20 GPU ~80ms），先仅 balanced/quality profile。**前置硬条件（先省后花）：A/B① embedding 本地化已落地且实测净省 ≥ 重排增耗，否则 cross_encoder 只留在 opt-in 的 quality profile，不进默认路径。**
3. **HyDE on/off**：证实有害则"默认关"从直觉升级为证据并写入文档；证实有益则仅 quality profile 开。

### P0-3 官方三档 profile（收敛 800+ 配置项的态空间）
| profile | 通道 | 重排 | 扩展 | 目标延迟(检索段) | 场景 |
|---|---|---|---|---|---|
| `fast` | dense(256d MRL) | 无 | 无 | p95 <200ms | 简单事实/高并发/Dify fast 路径 |
| `balanced`（新默认） | dense+sparse hybrid | cross_encoder top-20→10 | neighbor | p95 <500ms | 主力 |
| `quality` | 全通道+KG | rerank-expand-rerank + llm 加权 | parent-child 连坐 | p95 <1500ms | 复杂多跳/合规问答 |
- 每档端到端测过并挂独立 SLO；对外（含 Dify 路径）只暴露 profile，`CHAT_DEFAULT_RETRIEVAL_PROFILE`(`config.py:1557`) 机制现成。
- 灰度与回滚 = 切 profile，不再动散装开关。

### P0-4 装配端零成本项
- **首尾重排**：最强证据放 context 首尾（抗 lost-in-the-middle），纯排序 <1ms。
- **context ≤8K 软约束**：超限收紧 rerank 截断（Chroma context-rot 证据），配合已有 Context Cliff 监测。

### P0-5 缓存默认开启评估
- semantic cache（0.95 阈值）与 candidate cache 默认 on，TTL 从 30s 调到分钟级按 tenant 评估；Dify warmup(`config.py:773`) 模式推广到主链路。

---

## P1（第 3-8 周）：三个创新操作

### P1-1 【创新①】一次编码、三路召回（Tri-Pass Retrieval）
**命题：通道 ×3，编码成本 ×1，融合下沉服务端——SPLADE 通道去桩且延迟净零。**
- 做法：
  1. bge-m3 单次前向同时输出 dense + sparse(learned lexical weights) + colbert 三态，接进 `bge_m3_triplet.py` 既有 payload 骨架（现在 sparse_fn/colbert_fn 都是可注入空位）。
  2. 索引侧 collection 增加 `SPARSE_FLOAT_VECTOR` 字段，走影子 collection 蓝绿迁移（`indexer.py:116` 先例），colbert 态落多向量存储供重排用。
  3. 查询侧一次 `hybrid_search`（AnnSearchRequest×2 + 服务端 RRFRanker/WeightedRanker，pymilvus 2.6.11 原生支持），替代"dense 请求 + 应用层 BM25 fallback + 应用层融合"。
- 为什么这算创新：业界通行做法是 dense 模型 + 独立 SPLADE 模型 + 独立 ColBERT 模型三次编码三路调用；我们用 bge-m3 的三态输出把编码摊薄成一次，且中文 learned sparse 对政务术语/文号/机构名的精确匹配显著强于纯 dense——**这一条同时解决"通道桩"与"中文精确召回"两个问题**。
- 延迟账：编码 ±0（本来就要编 dense）；服务端两路 ANN 约 +10-20ms；省应用层 lexical fallback 分支与融合一轮 -10-30ms → **净 ≈ 0**。
- 切默认门槛：recall@10 ≥ +3pt 且 p95 增幅 ≤5%。应用层 `budgeted_rrf` 保留为跨 Milvus/KG 通道的上层融合（两层融合各司其职）。

### P1-2 【创新②】延迟感知分级路由（决策脑升级）
**命题：27 行正则退役；把"延迟预算剩余"变成路由信号——业界罕见的预算意识调度。**
- L0 规则短路：no-retrieval 意图直接旁路（已有，`orchestrator.py:2008` 入口）。
- L1 轻分类器：fasttext/线性头级别（<10ms CPU），输出 {simple / structured / multi_hop / out_of_scope} + 语种。训练数据 = POC 差评三分类埋点 + query 日志弱标注（反馈基建已有）。替换 `complexity_classifier.py` 与 `engine.py:467` 长度打分。
- L2 映射 + 预算调度：
  - label→profile：simple→fast（**直接接 `matryoshka.py` 的 `resolve_matryoshka_dimension`**，256d 粗检索，函数已按 label 写好，纯接线）；multi_hop→quality（agentic 门控从"长度阈值 250"改为分类器信号）。
  - **预算降级**：trace 各 stage 时长实时可得，剩余预算不足时自动砍最贵可选环节（二次 rerank → expand → 多样化），砍单记入 trace 供归因。
- 延迟账：+10ms 全量；简单查询（预计 60-70% 流量）跳过 ~80ms 重排与扩展 → **均摊净降 ~30-40ms**，且 p95 长尾受预算调度保护。

### P1-3 【创新③】冲突感知融合（政务差异化，Astute RAG 轻量版）
**命题：把"证据一致性"做成相关性/多样性/通道配额之外的第四融合信号——纯 RAG 产品几乎无人内建，政务法规版本冲突是刚需。**
- 融合后 top-k 内：规则+GLiNER（KG extraction 已有资产）抽取 {文号、日期、数值、机构} → 同实体跨文档分组 → 规则级矛盾检测（数值不等 / 日期新旧 / 文号修订链）→ 输出 `conflict_flag` + 时效排序建议。
- 装配端策略：新版本优先、被修订文档降权并标注"已被 X 号文修订"；citation 携带冲突标记；前端可视化留接口。
- 不用 LLM，<5ms；与 `RAG_TEMPORAL_INTENT_ENABLED` 及 provenance 钩子衔接。检出率/误报率进评测集（政务集补 50 题版本冲突专项）。硬约束下若实测同步开销超出噪声带，冲突检测整体移至装配后异步段，仅做标注、不阻塞首响。
- 二期（可选）：冲突组内才触发一次小 LLM 仲裁（仅 quality profile，且异步标注不阻塞首响）。

### P1-4 观测与门禁固化
- 检索段 p50/p95、zero-hit 率、冲突检出率接告警（`OBS_ANOMALY_*` 骨架已有 `config.py:1549`，补检索侧阈值）。
- 每 profile 独立 SLO 面板；路由砍单率/降级率入 router_layers 观测（已有）。

---

## P2（第 9-12 周，按门槛触发）

1. **MUVERA**：ColBERT 通道去桩（FDE 单向量化，对标 PLAID recall +10%/延迟 -90%），triplet 的 colbert 存量直接可用；门槛 = quality profile nDCG +2pt。
2. **投机式重排**：流式场景 fast 候选先行生成、重排并行、完成后校正引用（CRAG streaming 基础已有）——p95 长尾专项，感知延迟趋近 fast profile。
3. **拆 `run_retrieval`**：`orchestrator.py:2008→3800+` 近 2000 行单函数拆为 stage 类编排（ingestion `processor.py` 先例）。这是后续所有迭代的安全前提，放 P2 只因不阻塞收益，不代表不重要。
4. **Qwen3-Reranker 入工厂做 challenger**（factory 现无 qwen3）：只在评测栈跑，赢过 bge-reranker-v2-m3 再上量。

## 延迟预算总账（估算，P0-1 基线落地后用实测替换）

| 变更 | Δ质量 | Δ延迟（p50 视角） |
|---|---|---|
| embedding 本地化 bge-m3 | 中文 +5-8pt（待测） | **-70 ~ -250ms** |
| Tri-Pass 服务端 hybrid | +3-6pt（待测） | ≈ 0（+10-20 服务端，-10-30 应用层） |
| cross_encoder 重排（仅 balanced/quality ≈40% 流量） | +5-10pt | +80ms × 40% ≈ +32ms 均摊 |
| L1 路由 + fast path 分流 | 间接 + | +10ms 全量 − 80ms×60% ≈ **-38ms 均摊** |
| 冲突感知融合 | 政务差异化 | +5ms |
| 首尾重排 + 8K 约束 | +1-3pt | ≈ 0 |
| **合计** | **显著提升** | **p50 预期净降；p95 受预算调度保护** |

## 不做什么（同样重要）

- 不把 LLM 放进召回热路径：HyDE/LLM-rerank 仅 quality profile，且倾向异步。
- 不引 PageIndex TOC tree（既有决策，见 `rag-pageindex-deep-dive`）。
- 不做全图 GraphRAG 扫描；KG 仍走 agentic 定向搜索。
- 不为"通道数"本身加通道：任何新通道必须过 `channel budget policy` 消融闭环(`config.py:1159`)的份额证明。

## 验证与发布

- 每项变更：`regression_run_significance.py` 显著性 + 延迟双门禁 → 影子流量 1 周 → 单 tenant 灰度 → 全量；回滚 = 切 profile。
- 评测集：政务自建集（补 50 题版本冲突专项）+ CRUD-RAG 中文子集；报告延迟-质量 Pareto 图（消融基建已有）。

## 与既有 plans 的关系

- 吸收执行：`rag-retrieval-modernization-2026-q2.md`（Qwen3/MUVERA/HyDE 验证三 P0 在此落地）；`rag-robustness-knowledge-conflict-2026-q2.md`（Astute 轻量版 = P1-3）。
- 依赖配合：`cn-benchmark-baseline-2026-q2.md`（评测集）；`rag-four-subsystem-audit-2026-07.md`（观测项 P1-4 对齐）。

> 一句话：**用"本地化省下的 200ms"去买"重排与三路召回"，用分级路由把贵活只花在难查询上，用冲突感知做出政务市场买单的差异化——质量、速度、卖点三线同涨，全部构建在已核实存在的资产上。**
