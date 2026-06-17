# 超图增强 KG-RAG PoC 实施计划（政务"高效办成一件事"子集）

> **For agentic workers:** REQUIRED SUB-SKILL — 用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务执行。步骤用 `- [ ]` 复选框跟踪。
> **项目惯例**：本 plan 落 `plans/`，沿用既有 plan 风格（落地目录+行数估计 / Day 拆解 / 验证 metric / 陷阱 / 决策门槛）。借鉴对象：[Hyper-Extract](https://github.com/yifanfeng97/Hyper-Extract) / [Hyper-RAG (Nature Comms 2026)](https://www.nature.com/articles/s41467-026-71411-1)。

**Goal:** 在政务"高效办成一件事"子集上，量化"超边整体召回（hyper）"相对"现有二元 KG（baseline）"的检索/答案收益，2-3 周给出 go/no-go 结论。

**Architecture:** 不改表结构——复用现有 `KgSourceEvent`(超边) + `KgEventEntity(weight, role)`(超边-节点带角色权重) 这一**已存在的超边骨架**。只做两件事：(1) 抽取侧把"一件事"文本抽成**完整 n 元超边**（role/weight 齐全）；(2) 检索侧新增 `hyper` mode，命中任一构成实体即**召回整条超边**。评测全部复用现有 `compute_kg_hit_metrics` + `golden_eval_cases.json` + `changzhou_gov_golden_eval.py`。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2 (PG) / Milvus / 现有 KG 抽取-检索-评测栈。不引入任何新第三方大包（对齐"优先自研"约束）。

---

## 0. 背景与动机（为什么做、为什么是它）

- **业界证据**：Hyper-RAG（Nature Communications 2026）在 NeurologyCrop + 9 数据集上，超图召回比 GraphRAG **+6.3%**、比 LightRAG **+6.0%**，且 **query 越复杂越稳**；轻量版 Hyper-RAG-Lite **2× 速度** 仍 +3.3%。核心论点：超图建模 **n 元（beyond-pairwise）关系**，避免二元三元组拆散信息。
- **命中我们的真实短板**：200/300 题政务复测里，残余质量短板集中在"信息分散 / 期望来源不一致"。政务"一件事"天然是 n 元关系（一件事 = 多部门 + 多材料 + 多前置条件 + 多区差异共同成立），二元 `KgRelation` 会把它拆散 → 正是超边能补的地方。
- **我们的独特低成本优势**：`app/rag/kg/models.py:50-104` 的 `KgSourceEvent` + `KgEventEntity(weight, role)` **已经是超边数据结构**。我们不需要像论文那样从零建超图存储——只需把它"用足"。

## 1. 范围与非目标（防止 PoC 膨胀）

**In scope：**
- 数据子集：政务 `knowledge_section == "02高效办成一件事"`（+ 必要时少量 `06各区常见问题` 做地域 n 元对照）。
- 抽取侧 `hyperedge` 增强 + 检索侧 `hyper` mode。
- A/B 量化对照（baseline 二元 vs hyper 超边）+ 决策结论。

**Out of scope（明确不做）：**
- ❌ 不改 PG 表结构（超边骨架已存在）。
- ❌ 不引入 Hyper-Extract / Hyper-RAG 框架本体（v0.1.1 早期、license 未明、与"优先自研"冲突）；只借其 `examples/hyper_rag_demo.py` 思路。
- ❌ 不上重版超图，对标 **Hyper-RAG-Lite**（轻量、单跳超边召回）。
- ❌ 不做时空图 / 6 域模板（参考价值中等，本 PoC 不碰）。
- ❌ 不做全量重抽取——只对"一件事"子集重抽。

## 2. 落地文件结构（create/modify + 行数估计）

| 操作 | 路径 | 责任 | 估计 |
|---|---|---|---|
| Create | `app/rag/kg/extraction/hyperedge_extractor.py` | "一件事"→完整 n 元超边（event + 全 role 关联） | ~240 |
| Modify | `app/rag/kg/extraction/backend_router.py:11,29` | `_VALID_BACKENDS` 加 `"hyper"`；`resolve_extraction_backend` 分支 | +~15 |
| Modify | `app/rag/kg/extraction/config.py:49` | `ExtractConfig` 加 `extract_hyperedges: bool` | +~4 |
| Create | `app/rag/kg/search/hyperedge_recall.py` | 命中任一实体→召回整条超边（event+全关联实体） | ~200 |
| Modify | `app/rag/kg/search/query_mode.py:8` | `_ALLOWED_MODES` 加 `"hyper"` + 触发正则 | +~12 |
| Modify | `app/rag/kg/search/recall.py:135` | `RecallSearcher.search` 接入 hyper 分支 | +~30 |
| Create | `app/rag/evaluation/hyperedge_ab_runner.py` | baseline vs hyper A/B 对照 + bootstrap CI + per-case | ~220 |
| Create | `plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_yijianshi.json` | "一件事"子集评测集（≥40 题，标 evidence + key_points） | 数据 |
| Create | `tests/rag/kg/test_hyperedge_extractor.py` | 抽取单测 | ~120 |
| Create | `tests/rag/kg/test_hyperedge_recall.py` | 召回单测 | ~120 |
| Create | `tests/rag/evaluation/test_hyperedge_ab_runner.py` | A/B runner 单测 | ~90 |
| Modify | `app/core/config.py` | `KG_HYPEREDGE_ENABLED`/`KG_HYPEREDGE_MAX_FANOUT` 等开关（默认关） | +~8 |

新增代码合计 ~1100 行 + 评测数据。**不删除、不改动任何现有抽取/检索默认路径**（hyper 全程 opt-in，默认 false）。

## 3. 任务分解（TDD：测试先行 / 频繁 commit）

### Task 0：建立 baseline 基准（先有对照，再谈提升）

**Files:**
- Read: `scripts/changzhou_gov_golden_eval.py`、`app/rag/evaluation/kg_search_diagnostics_metrics.py:14`
- Create: `golden_eval_yijianshi.json`（先用现有 cases 过滤 `02高效办成一件事`）

- [ ] **Step 1**：从 `golden_eval_cases.json` 过滤出 `knowledge_section=="02高效办成一件事"` 的 case，统计数量。
  - Run: `python -c "import json;d=json.load(open('plugins/pipelines/changzhou-gov-service-knowledge/golden_eval_cases.json'));print(sum(1 for c in d['cases'] if c['expected'].get('metadata',{}).get('knowledge_section')=='02高效办成一件事'))"`
  - 预期：得到一个数字 N。**若 N < 30 → 进入 Task 1 补充**；若充足直接用。
- [ ] **Step 2**：对该子集跑现有检索（baseline 二元 KG），用 `compute_kg_hit_metrics` 记录基线 `mrr/recall/ndcg/map@5` + `retrieval_effective_context_rate`。
  - Run: `python scripts/changzhou_gov_golden_eval.py --cases golden_eval_yijianshi.json --mode auto` （**baseline 必须用生产默认 mode（`auto`），不要武断选 `local`——否则对照不公平**；记录实际命中的 mode）
  - Expected: 输出一份 baseline JSON，记录于 `/tmp/hyper_poc_baseline_<date>.json`。
- [ ] **Step 3 Commit**：`git commit -m "test(kg): add 高效办成一件事 golden subset + baseline metrics"`

### Task 1：补足"一件事"评测子集（仅当 Task 0 不足）

**Files:** Modify `golden_eval_yijianshi.json`；用 `app/rag/evaluation/test_generator.py`（662 行，已存在）。

- [ ] **Step 1**：用 `test_generator` 对"一件事"文档合成候选问题（覆盖 8 难点维度：多部门/多材料/前置条件/时态/否定/跨实体比较/数值单位/区差异）。
- [ ] **Step 2**：**人工校验**每题的 `evidence_chunk_ids` 与 `answer_key_points`（防合成偏差，对齐 POC 三原则）。补到 ≥40 题。
- [ ] **Step 3**：schema 校验（复用 `app/rag/evaluation/datasets/validator.py`）。
  - Run: `pytest tests/rag/evaluation/ -k golden -q` Expected: PASS
- [ ] **Step 4 Commit**：`git commit -m "test(kg): expand 一件事 golden subset to 40 cases (human-verified)"`

### Task 2：超边增强抽取

**Files:** Create `hyperedge_extractor.py`；Modify `backend_router.py:11,29`、`extraction/config.py:49`。

- [ ] **Step 1（测试先行）**：写 `tests/rag/kg/test_hyperedge_extractor.py`：给定一段"一件事"文本（含办理地点/电话/收费/材料/适用区），断言抽出 **1 条 event 超边** 且其 `KgEventEntity` 关联实体数 ≥5、每条带非空 `role`。
  - Run: `pytest tests/rag/kg/test_hyperedge_extractor.py -v` Expected: FAIL（模块不存在）
- [ ] **Step 2**：实现 `HyperedgeExtractor`，接口对齐现有抽取器（`async def extract_from_sections(...)`，见 `hybrid_extractor.py:24`）。核心：用一个"超边抽取" prompt，把一件事抽成 `{event:{title,summary,content}, members:[{entity,role,weight}...]}`，落 `KgSourceEvent` + `KgEventEntity`。复用 `entity_verifier`/`alias` 做实体归一。
- [ ] **Step 3**：`backend_router.py` —— `_VALID_BACKENDS` 加 `"hyper"`；`resolve_extraction_backend` 加分支返回 `HyperedgeExtractor`。`config.py` 的 `ExtractConfig` 加 `extract_hyperedges: bool = False`。
- [ ] **Step 4**：Run 测试至 PASS。`pytest tests/rag/kg/test_hyperedge_extractor.py -v`
- [ ] **Step 5**：对"一件事"子集实际重抽一遍（`requested_backend="hyper"`），抽样人工检查超边质量（fanout、role 完整度）。
- [ ] **Step 6 Commit**：`git commit -m "feat(kg): add hyperedge extraction backend (opt-in)"`

### Task 3：超边检索 mode（`hyper`）

**Files:** Create `hyperedge_recall.py`；Modify `query_mode.py:8`、`recall.py:135`。

- [ ] **Step 1（测试先行）**：写 `tests/rag/kg/test_hyperedge_recall.py`：构造一个含 1 超边（event+5 实体）的小图，query 只命中其中 1 个实体，断言 hyper recall 返回**整条超边的全部 5 个实体 + event content**（baseline local 只返回命中实体邻域）。
  - Run: `pytest tests/rag/kg/test_hyperedge_recall.py -v` Expected: FAIL
- [ ] **Step 2**：实现 `HyperedgeRecall`。召回入口**双通道**：(a) 实体命中 → 经 `KgEventEntity` 反查所属 event(超边)；(b) `KgSourceEvent.content_vector`（`models.py:68` 已有）语义直召超边——**先确认该向量是否已同步至 Milvus，未同步则本 PoC 退化为仅 (a) 单通道，不阻塞结论**。召回该 event 下全部成员实体 + event.content，按 `weight` 排序、`KG_HYPEREDGE_MAX_FANOUT` 截断（控噪）。**工程要点**：批量 `IN` 查询反查 event 与成员避免 N+1；多个命中实体落同一超边时按 `event_id` **去重**。
- [ ] **Step 3**：`query_mode.py` `_ALLOWED_MODES` 加 `"hyper"`；`recall.py:RecallSearcher.search` 在 `mode=="hyper"` 时走 `HyperedgeRecall`。`config.py` 加 `KG_HYPEREDGE_ENABLED=False` / `KG_HYPEREDGE_MAX_FANOUT=12`。
- [ ] **Step 4**：Run 测试至 PASS。
- [ ] **Step 5 Commit**：`git commit -m "feat(kg): add hyper retrieval mode (whole-hyperedge recall, opt-in)"`

### Task 4：A/B 对照评测 runner

**Files:** Create `hyperedge_ab_runner.py`；Create `tests/rag/evaluation/test_hyperedge_ab_runner.py`。

- [ ] **Step 1（测试先行）**：写单测，喂入两组伪结果（baseline/hyper），断言 runner 正确算出 per-mode `mrr/recall/ndcg/map@5` + **bootstrap 95% CI** + **per-case 差异表**。
  - Run: `pytest tests/rag/evaluation/test_hyperedge_ab_runner.py -v` Expected: FAIL
- [ ] **Step 2**：实现 runner：对"一件事"子集分别用 `mode=local`(baseline) 与 `mode=hyper` 跑检索，复用 `compute_kg_hit_metrics` + `summarize_graphrag_bench`；加 bootstrap CI（自研，~30 行，对齐项目 ablation 严谨性要求）+ paired 差异 + per-case 钻取 + 延迟 p50/p95 对照。
- [ ] **Step 3**：Run 测试至 PASS。
- [ ] **Step 4**：跑全量"一件事"子集 A/B，产出 `/tmp/hyper_poc_ab_<date>.json` + 单文件 HTML 报告（复用 `poc_runner/reports/html_renderer.py`，对齐 FILE_A023 单文件三原则）。
- [ ] **Step 5 Commit**：`git commit -m "feat(eval): hyperedge A/B runner with bootstrap CI + per-case"`

### Task 5：结论与 go/no-go

- [ ] **Step 1**：对照 §4 决策门槛判定。
- [ ] **Step 2**：把结论 + 数字写回本 plan 末尾"## 9. PoC 结论"，并在 `competitive-assessment-opensource-kb-2026-06.md` 的 KG 章节追加一句实测结论。
- [ ] **Step 3 Commit**：`git commit -m "docs(kg): hyperedge PoC conclusion + decision"`

## 4. 评测协议与决策门槛（客观，防 FloTorch 陷阱）

**主指标**（"一件事"子集，@5）：`recall` / `ndcg` / `answer_key_points 命中率` / `retrieval_effective_context_rate`（gate≥0.9）/ `retrieval_noise_rate`（gate≤0.1）。
**对照**：baseline(`mode=local` 二元) vs hyper(`mode=hyper` 超边)，**同一子集、同一 embedding、同一 reranker**，仅检索路径变量不同。
**严谨性**：bootstrap 95% CI + paired 差异 + per-case 钻取（不只看聚合均值）。

| 结论档 | 判据 | 行动 |
|---|---|---|
| ✅ 强 go | hyper 比 baseline `recall@5` 或 `key_points` **≥ +5pt** 且 CI 不跨 0，且 `noise_rate` 未破 gate、p95 延迟增幅 ≤ +30% | 落 P1 产品化（hyper 作为政务默认增强） |
| 🟡 弱 go | 提升 **+2~5pt** | 仅作为 `mode=hyper` 可选项，限"一件事"类查询启用 |
| 🔴 no-go | 提升 **< +2pt** 或 noise 破 gate 或延迟暴涨 | 归档结论，不产品化（诚实记录，避免"为超图而超图"） |

## 5. 时间线（2-3 周，~13 工作日）

- **D1-2**：Task 0 baseline + 判断子集是否充足。
- **D3-4**：Task 1 补评测集（若需）+ 人工校验。
- **D5-8**：Task 2 超边抽取（含重抽 + 人工抽检）。
- **D9-11**：Task 3 超边检索 mode。
- **D12**：Task 4 A/B runner + 跑全量。
- **D13**：Task 5 结论 + HTML 报告 + go/no-go。

## 6. 风险与陷阱

- **召回噪声**：整条超边召回可能带入无关成员 → 用 `KG_HYPEREDGE_MAX_FANOUT` + `weight` 排序控噪，并以现有 `retrieval_noise_rate` gate 把关。
- **合成集偏差**：Task 1 合成题必须人工校验 evidence，否则提升是假象。
- **抽取成本**："一件事"文档长，超边抽取 token 高 → 仅限子集，监控 token；对标 Lite 不做多跳。
- **数据模型够不够**：默认假设 `KgSourceEvent/KgEventEntity` 够用；若抽取中发现需要"超边类型/超边间关系"，**先记录、不擅自改表**，纳入结论再议。
- **默认路径零影响**：hyper 全程 opt-in（`KG_HYPEREDGE_ENABLED=False` 默认），确保不影响现有 200/300 题表现。
- **对照公平性**：baseline 用生产默认 mode（`auto`），非武断 `local`，否则提升是伪差。
- **向量同步前提**：event 语义直召依赖 `KgSourceEvent.content_vector` 已入 Milvus；未同步则退化为"实体命中→反查超边"单通道，先出结论再议是否补向量。
- **查询性能**：超边反查用批量 `IN`、event 级去重，避免 N+1；监控 hyper mode p95 增幅（门槛 ≤ +30%）。

## 7. 验证（完成定义）

- [ ] 所有新增单测 PASS：`pytest tests/rag/kg/test_hyperedge_extractor.py tests/rag/kg/test_hyperedge_recall.py tests/rag/evaluation/test_hyperedge_ab_runner.py -v`
- [ ] 现有 KG/检索测试不回归：`pytest tests/rag/kg -q` 全绿。
- [ ] 默认配置下（hyper 关闭）政务 golden 主集 metric 与 PoC 前一致（无回归）。
- [ ] 产出 A/B 报告（JSON + 单文件 HTML）+ 明确 go/no-go。

## 8. 与既有 plan 的边界

- 不替代 `rag-kg-deep-research-2026-q2`（ToG/PoG/PPR 那条 agentic 主线）——超边是**召回单元**维度的增强，与 agentic 图搜索正交，可叠加。
- 与 `context-expansion`（chunk 邻近扩展）正交：超边是**实体语义**层扩展，邻近是**chunk 物理**层扩展。
- 若 go，产品化时与 `industry_rules`（行业规则库）协同：政务"一件事"的 role 模板可沉淀进规则库。

## 9. PoC 结论（执行后回填）

- _待 Task 5 回填：baseline vs hyper 数字、CI、go/no-go、产品化建议。_
