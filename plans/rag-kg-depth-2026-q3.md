# RAG KG 域纵深计划（2026-Q3）——plan_on_graph 加厚 + 全局实体消解 + KG 增量装载

> 日期：2026-07-13 ｜ 前置调研：`plans/rag-kg-deep-research-2026-q2.md`（ToG/PoG/GNN-RAG 对标）、`plans/rag-kg-hyperedge-poc-2026-q2.md`
> 定位：KG 检索武器库全（`kg/search/` 20+ 模块：agentic_beam/drift_search/pprank/subqrag/method_router/path_verbalizer/graph_embeddings/lazy_indexer），快照 diff/provenance/community 摘要治理也齐。剩下三块硬骨头：**规划器薄（plan_on_graph 36 行撑不起"多跳推理"宣称）、实体消解停在文档内（跨文档同名/别名分裂图谱）、KG 更新疑似全量重建**。KG 影响分析是既定"不可拷贝护城河"，这三块补上纵深才立得住。

## Context（2026-07-13 核实）

- **plan_on_graph.py 36 行**（`app/rag/kg/search/plan_on_graph.py`）：对标 PoG WWW'25 的自适应规划（子目标分解/路径探索/记忆回溯/自纠错）基本未实现，method_router 有路由位但该方法名不副实
- **实体消解现状**：`extraction/alias.py`（choose_alias_direction/extract_alias_candidates，:289-371）+ `extractor.py:243 _canonicalize_entities_for_chunk`——**均为抽取时、文档内**；跨文档全局消解（"住建局"="住房和城乡建设局"="市住建局"）未见独立模块，中文政务机构别名分裂是图谱质量第一杀手
- **KG 增量装载存疑**：`kg/loading/` 仅 processor.py + config.py；文档更新时 KG 是否全量重抽待跑通确认（与入库域增量重嵌同根）
- 资产：hyperedge 骨架（KgSourceEvent/KgEventEntity 不改表）、snapshot 精确 diff + JSON Patch、BFS k-hop 影响分析、GLiNER + auto_graph_r1 抽取、community LLM 摘要、KG reranker（reranker/kg.py）

## 落地设计

### P0-1 全局实体消解（图谱质量地基，先于一切推理增强）
- 新模块 `kg/resolution/`：三级流水线——
  1. **确定级**：alias.py 既有规则 + 机构别名词典（政务行业规则库联动，industry_rules 资产复用）
  2. **相似级**：entity embedding（graph_embeddings 已有）+ 名称编辑距离 + 类型一致性，阈值分"自动合并/待审"两档
  3. **待审级**：进人工审核队列（quarantine 机制复用，来源=`kg_resolution`）
- 合并语义：canonical entity + alias 边（不物理删除，provenance 保留原始 surface form，快照 diff 可回滚）。
- 验收指标：政务集机构实体的分裂率（同一真实机构对应节点数均值）从基线降 ≥50%；消解错误率（误合并）<2%——**误合并比漏合并危害大，阈值保守**。

### P0-2 KG 增量装载（与入库域 delta 重嵌同一节拍）
- 输入：入库域 P0-2 的 chunk 三分类（unchanged/modified/removed）→ KG 侧只对 modified/added chunk 重抽三元组；removed chunk 的三元组按 provenance 反查做**证据递减**（一条边失去全部来源 chunk 才删，多来源边只减计数）。
- 快照联动：增量装载产生的 diff 直接进 snapshot（精确 diff 已有），影响分析（BFS k-hop）自动评估波及面——"改一份文件，图谱哪些结论受影响"是护城河句式的落地。

### P1-1 plan_on_graph 加厚（36 行 → 真规划器）
- 对标 PoG 三件套，落在既有骨架上而非重写：
  1. **子目标分解**：复用 decomposition_chain（retrieval/ 已有）把多跳问题拆子问题序列
  2. **自适应探索**：每跳在 agentic_beam_search 与 pprank 间按子目标类型选择（method_router 扩展），路径带 path_verbalizer 证据串
  3. **回溯自纠**：子目标无证据支持时回退上一跳换方向（beam 状态栈），预算上限防失控（对齐召回计划的预算调度思想）
- 触发面收窄：仅 multi_hop 分类（召回计划 L1 分类器信号）+ quality profile 进入，不碰主链路延迟。
- 验收：自建多跳 30 题（2-3 跳政务因果/依据链）对比 agentic_beam 单法，hit@答案实体 +10pt 才转正；否则维持 beam 为主、PoG 下线——**给薄实现一个"证明自己或退场"的裁决机制**。

### P1-2 KG↔向量协同验证（把默认关的通道用数据裁决）
- `RAG_KG_QUERY_EXPANSION_ENABLED=False`(config.py:1183) 至今未验证：跑 KG 实体扩展 on/off A/B（消解完成后再跑——脏图谱扩展只会放大噪声，**P0-1 是本项前置**）。
- KG chunk 注入与 kg reranker 的份额进 channel budget policy 消融闭环，让 KG 通道在预算体系里挣自己的配额。

### P2 进阶
- hyperedge PoC 裁决（既定门槛 ≥+5pt 产品化）：事件级超边在"政策发布-修订-废止"链上与普通三元组对比。
- 本体质量门禁：ontology 漂移检测进 KG 诊断 metric（前端诊断 plan 的 18+ metric 后端补位）。
- 社区摘要增量刷新：consumer 是 drift_search，增量装载后受影响 community 才重摘要（LLM 成本控制）。

## 优先级矩阵

| 优先级 | 任务 | 工作量 | 落点 |
|---|---|---|---|
| P0 | 全局实体消解三级流水线 | ~6 人日 | `kg/resolution/`（新）+ alias/graph_embeddings 复用 |
| P0 | KG 增量装载 + 证据递减 | ~5 人日 | `kg/loading/processor.py` + provenance |
| P1 | plan_on_graph 加厚（裁决制） | ~6 人日 | `kg/search/plan_on_graph.py` + method_router |
| P1 | KG 扩展 A/B + 预算闭环 | ~3 人日 | 评测栈 + channel budget policy |
| P2 | hyperedge 裁决 / 本体门禁 / 社区增量 | 按门槛触发 | 既有骨架 |

## 验证与门槛
- 消解与增量先行（图谱干净且新鲜是推理增强的前提，顺序不可倒）。
- 所有 KG 检索增强以"multi_hop 子集 +10pt 且主链路延迟不变"为转正线；KG 永不进 fast/balanced 热路径（quality profile 专属）。

## 不做什么
- 不做全图 GraphRAG 式离线全量摘要问答（LazyGraphRAG 结论：按需构建更优，drift+lazy_indexer 已是正确形态）；不引 GNN 训练管线（graph_embeddings 轻量足够）；不改表（hyperedge 用既有事件表）。
