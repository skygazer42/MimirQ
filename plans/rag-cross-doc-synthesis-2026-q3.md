# 跨文档融合 + 冲突主动呈现（能力 P0 #1，2026 Q3）

> 把 `claim_nli_verifier` 215 行 + `claim_verifier` 216 行 + `faithfulness` 82 行 已有的 *单 claim* 矛盾判定能力，**升级为跨文档主动呈现的合成层能力**。客户问"招股书说研发投入 ¥2 亿，年报说 ¥3 亿"时，RAG 主动告诉用户"两个来源数字不一致"而不是简单拼接。
>
> 创建日期：2026-05-08
> 来源：`rag-gap-and-recommendations-summary-2026-q2.md` 第 5.2 节真 GAP / 用户对话 2026-05-08 聚焦能力
> 优先级：P0（能力 #1）
>
> **核心一句话**：底层武器（NLI verifier）已就位 215 行，缺的是 *workflow 层的跨文档协调 + UI 主动呈现*；2 周 ~600 行可让 RAG 从"返回 chunks"升级到"识别 + 呈现冲突"。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | 现状盘点（NLI 已落地但未集成主路径） |
| 第 2 章 | 核心能力定义（什么是"跨文档融合"） |
| 第 3 章 | 算法设计（聚类 + pairwise NLI + 三类输出） |
| 第 4 章 | 落点设计（4 个） |
| 第 5 章 | UI 设计（前端如何呈现冲突） |
| 第 6 章 | 评测集 |
| 第 7 章 | 1-2 周里程碑 |
| 第 8 章 | 风险 + 范围之外 |

---

## 1 现状盘点

### 1.1 已有底层能力（不重做）

| 模块 | 文件 | 行数 | 能力 |
|---|---|---|---|
| Claim NLI Verifier | `app/rag/core/claim_nli_verifier.py` | 215 | 单 claim 三标签判定（entailment / contradiction / neutral） |
| Claim Verifier | `app/rag/core/claim_verifier.py` | 216 | claim 抽取 + 验证 |
| Faithfulness | `app/rag/core/faithfulness.py` | 82 | LLM 生成与 source 一致性 |
| Context Denoise | `app/rag/core/context_denoise.py` | — | retrieval 后 prompt 前去重去噪 |

### 1.2 关键缺失：合成层（synthesis layer）

`claim_nli_verifier` 仅在 *评测* 路径使用（faithfulness check），**未在主检索路径触发跨文档对比**：
- ❌ 未对 retrieval 结果按 source 聚类
- ❌ 未对不同 source 的同主题 claim 做 pairwise NLI
- ❌ 未在 LLM prompt 中注入"冲突标注"信号
- ❌ 前端不展示"两个来源说法矛盾"

**结果**：客户问跨文档对比 / 矛盾时，MimirQ 与普通 chunk-level RAG 一样，简单拼接 → LLM 自行调和 → 用户看不到冲突来源。

### 1.3 真正缺失的 4 件事

1. **Source-aware aggregation**：retrieval 后按 `document_id` / `source_path` / `version` 聚类
2. **Pairwise NLI 调度**：跨 source 抽取同主题 claim 对，调 `claim_nli_verifier`
3. **三类输出 schema**：agreement / disagreement / unique
4. **UI 前端标注**：chat 中明确呈现"⚠️ 两个来源数字不一致"

---

## 2 核心能力定义

### 2.1 输入 / 输出契约

**输入**：
- query（用户问题）
- retrieved_chunks（list[Document]，已含 source metadata）

**输出**：
```python
@dataclass(frozen=True)
class CrossDocSynthesis:
    schema: str = "mimirq.cross_doc_synthesis.v1"
    query: str
    sources: list[SourceCluster]          # 按 source 聚合的 chunks
    claims_by_source: dict[str, list[Claim]]  # 每 source 抽出的 claim
    agreements: list[ClaimAgreement]      # 跨 source 一致的事实
    disagreements: list[ClaimDisagreement]  # 跨 source 矛盾的事实
    unique_claims: dict[str, list[Claim]]  # 仅出现在某一 source 的 claim
    coverage_score: float                 # 共识 / 总 claim
```

### 2.2 三类输出语义

| 类别 | 含义 | UI 表现 |
|---|---|---|
| **Agreement** | ≥ 2 个 source 表达同一 claim 或 entailment 关系 | ✅ 绿色"多源一致" |
| **Disagreement** | ≥ 2 个 source 表达 contradiction 关系 | ⚠️ 红色"来源冲突" |
| **Unique** | 仅 1 个 source 提及，其他 source neutral 或未提 | ℹ️ 蓝色"仅 X 来源提及" |

### 2.3 适用场景

- "招股书 vs 年报 vs 第三方研报"对比
- "新版法规 vs 旧版法规"差异
- "甲方合同 vs 乙方合同"条款冲突
- "学术论文 A vs 论文 B" 结论对比

### 2.4 不适用场景（明确）

- 单文档查询（不涉及 *跨* 源）
- chunk-level fact 查询（如"X 是多少"，不需要对比）
- 数学推理 / 公式（属于 P1 #3 Math RAG）

---

## 3 算法设计

### 3.1 5 步 Pipeline

```
Step 1: retrieval → chunks[]
Step 2: cluster_by_source(chunks) → sources[]
Step 3: extract_claims(source) for each source → claims_by_source
Step 4: pairwise_nli(claim_a, claim_b) for cross-source pairs → relations
Step 5: classify into agreements / disagreements / uniques
```

### 3.2 步骤详解

#### Step 2：Source 聚类

按 `document_id` / `source_path` 聚合，但需 *版本感知*：
- 同 `source_path` 不同 `version` → 视为不同 source
- 同 `document_id` 不同 page → 视为同一 source
- 复用 `app/rag/retrieval/contract.py` 的 metadata schema

#### Step 3：Claim 抽取（复用现有）

- 复用 `app/rag/core/claim_verifier.py` 的 claim 抽取
- 每 source 限抽 top-K（默认 K=5）以控成本
- 对短 chunk（< 50 token）跳过抽取

#### Step 4：Pairwise NLI（核心）

- 对每对（source_a, source_b）的 claim 笛卡尔积，先做轻量过滤（topic similarity ≥ 阈值）才调 NLI
- 调 `app/rag/core/claim_nli_verifier.py:verify_claim_pair`（需新增此接口）
- 结果三标签：entailment / contradiction / neutral
- 成本控制：N source × M claim 笛卡尔积爆炸 → topic 预过滤后只保留 top-K 对

#### Step 5：分类聚合

- contradiction → disagreements（按强度排序）
- entailment with ≥ 2 sources → agreements
- neutral 且仅 1 source 提及 → uniques
- 输出 `CrossDocSynthesis` schema

### 3.3 性能 / 成本控制

| 维度 | 控制 |
|---|---|
| LLM 调用次数 | 默认上限 50 次 / query（可配置） |
| Topic 预过滤 | embedding 余弦相似度 ≥ 0.5 才进入 NLI |
| 缓存 | (claim_a_hash, claim_b_hash) → NLI 结果，blake3 24h Redis |
| 降级 | LLM 失败时 fallback 到不做 cross-doc |

### 3.4 示例输出（金融场景）

Query: "X 公司 2024 年研发投入"

Sources: 3 个（招股书 / 年报 / 第三方研报）

```json
{
  "agreements": [
    {"claim": "研发投入主要投向 AI 与自动化方向", "sources": ["招股书", "年报"]}
  ],
  "disagreements": [
    {
      "topic": "研发投入金额",
      "claims": [
        {"source": "招股书", "value": "¥2 亿"},
        {"source": "年报", "value": "¥3 亿"}
      ],
      "severity": "high"
    }
  ],
  "uniques": {
    "第三方研报": [{"claim": "研发投入将增加 50% 在 2025 年"}]
  }
}
```

---

## 4 落点设计（4 个）

### 4.1 落点 A：新 workflow `cross_doc_synthesis.py`

**文件**：`app/rag/workflows/cross_doc_synthesis.py`

**与现有 workflow 关系**：
- 与 `crag_streaming` / `self_rag` 同级注册到 `app/rag/workflows/factory.py`
- 通过 settings 开关：`RAG_CROSS_DOC_SYNTHESIS_ENABLED=false` 默认关
- 路由：`system_router` 检测到 query 含跨源关键词（"对比 / 不同 / 矛盾 / 差异"）时启用

**复用资产**：
- `app/rag/workflows/base.py:BaseWorkflow`
- `app/rag/core/claim_nli_verifier.py`
- `app/rag/core/claim_verifier.py`
- `app/rag/embedding/`（topic 预过滤）

**新增**：~250 行

### 4.2 落点 B：扩 `claim_nli_verifier.py` 加 pairwise 接口

**文件**：`app/rag/core/claim_nli_verifier.py`

**新增**：
- `verify_claim_pair(claim_a, claim_b, ...)` 公开接口
- 批量并发版本 `verify_claim_pairs_batch`（asyncio.gather）

**工作量**：~80 行（不动 215 行核心逻辑）

### 4.3 落点 C：Schema + API

**文件**：
- `app/api/schemas/cross_doc_synthesis.py` — Pydantic schema
- `app/api/v1/cross_doc.py` — endpoint：`POST /cross-doc-synthesis`

**API 接口**：
```
POST /api/v1/cross-doc-synthesis
{
  "query": "...",
  "chunks": [...],   // 或 retrieval_request
  "config": { "max_pairs": 50, "topic_threshold": 0.5 }
}
→ CrossDocSynthesis JSON
```

**新增**：~150 行

### 4.4 落点 D：前端 UI 冲突标注

**文件**：
- `web/components/cross-doc-synthesis/`
  - `agreement-card.tsx` — 绿色"多源一致"卡
  - `disagreement-card.tsx` — 红色"来源冲突"卡（含 side-by-side diff）
  - `unique-card.tsx` — 蓝色"仅 X 提及"卡
- 在 `web/components/chat-area.tsx` 中 chat 消息回答前注入 synthesis 卡片

**复用**：
- `web/components/chunk-preview/components/empty-state.tsx` 的卡片设计语言
- `web/components/graph/kg-snapshots-page.tsx` 的 diff 视觉

**新增**：~250 行

### 4.5 工作量汇总

| 落点 | 行数 | 工时 |
|---|---|---|
| A workflow | 250 | 4 day |
| B NLI 扩接口 | 80 | 1 day |
| C Schema + API | 150 | 2 day |
| D 前端 UI | 250 | 4 day |
| 测试 | 100 | 2 day |
| **合计** | **~830 行** | **~13 day / 2 周** |

---

## 5 UI 设计

### 5.1 Chat 消息中的呈现

```
用户：X 公司 2024 年研发投入是多少？

助手回答：
─────────────────────────────────
| ⚠️ 来源冲突（高严重度）         |
| 招股书：¥2 亿                   |
| 年报：¥3 亿                     |
| → 建议核实：以年报披露口径为准   |
─────────────────────────────────
| ✅ 多源一致（2 个来源）          |
| 主要投向：AI 与自动化方向        |
| 来源：招股书、年报               |
─────────────────────────────────
| ℹ️ 仅第三方研报提及              |
| 2025 年将增加 50%               |
─────────────────────────────────

[完整回答内容]
```

### 5.2 设计原则

- **冲突优先**：disagreement 卡片置顶，最先看到
- **side-by-side diff**：复用 `kg-snapshots-page` 的 diff 视觉
- **一键溯源**：每个 claim 可点击跳到原文 page
- **严重度分级**：high（数值不一致 / 法规条款矛盾）/ medium / low
- **可折叠**：默认展开 disagreement，agreement / uniques 可折叠

### 5.3 i18n 文案

```ts
CrossDocSynthesis: {
  agreement: { title: '✅ 多源一致', description: '{count} 个来源表达一致' },
  disagreement: { title: '⚠️ 来源冲突', description: '{count} 个来源说法矛盾' },
  unique: { title: 'ℹ️ 仅 {source} 提及' },
  severity: { high: '高', medium: '中', low: '低' },
  cta: { verify: '点击核实', expand: '展开详情' },
}
```

---

## 6 评测集

### 6.1 自建评测集

`evaluation/poc_runner/cross_doc_bench/`：
- 50 个跨文档查询
- 5 类场景：财报对比 / 法规版本 / 合同条款 / 学术结论 / 政策口径
- 每查询：3-5 个 source + 标注 *预期 disagreement / agreement / unique*

### 6.2 评测 metric

| Metric | 含义 |
|---|---|
| **Disagreement recall** | 标注的"应该发现的冲突"找到多少 |
| **Disagreement precision** | 系统标的冲突中有多少是真冲突 |
| **Agreement F1** | 一致性识别准确率 |
| **Unique discrimination** | unique vs neutral 分类准确率 |
| **End-to-end latency** | 含 NLI 调度的完整 pipeline p95 |

### 6.3 决策门槛

| 评测结果 | 决策 |
|---|---|
| Disagreement recall ≥ 80% + precision ≥ 75% | **GA**，默认对跨源 query 启用 |
| 60-80% | router 仅在明确触发时启用（"对比 / 矛盾"等关键词） |
| < 60% | 复盘算法 / 调 NLI prompt |

---

## 7 1-2 周里程碑

### Day 1-2（NLI pairwise 接口 + workflow skeleton）
- [ ] 扩 `claim_nli_verifier.py` 加 `verify_claim_pair` + batch 接口（80 行）
- [ ] 新建 `app/rag/workflows/cross_doc_synthesis.py` skeleton + 注册到 factory
- [ ] 单元测试覆盖 pairwise NLI

### Day 3-5（Pipeline 核心）
- [ ] Source 聚类
- [ ] Claim 抽取（复用 claim_verifier）
- [ ] Topic 预过滤（embedding 相似度阈值）
- [ ] Pairwise 调度 + 缓存

### Day 6-7（Schema + API）
- [ ] `cross_doc_synthesis.py` schema
- [ ] `POST /api/v1/cross-doc-synthesis` endpoint
- [ ] integration test

### Day 8-10（前端 UI）
- [ ] `web/components/cross-doc-synthesis/` 3 个 card 组件
- [ ] 注入 chat-area
- [ ] i18n + 视觉与 kg-snapshots-page diff 对齐

### Day 11-12（评测 + GA）
- [ ] 自建 50 题评测集
- [ ] 跑全量 + HTML 报告
- [ ] 决策门槛触发后 GA

### Day 13-14（buffer + 文档）

---

## 8 风险 + 范围之外

### 8.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLM 调用爆炸 | N×M 笛卡尔积成本失控 | topic 预过滤 + 上限 50 pairs/query |
| NLI 误判 | 假冲突 / 漏冲突 | 自一致性 K=3 投票（与 P0 #2 协同） |
| UI 信息过载 | 客户被太多卡片淹没 | 默认折叠非冲突 / 严重度排序 |
| 中文 NLI 质量 | 中文 entailment 评判难 | 选 BGE-zh / Qwen NLI / Claude |
| 与现有 reasoning 冲突 | LLM 本来就会"自然处理"冲突 | 显式 + 隐式互补，UI 给用户选择权 |

### 8.2 范围之外

- 不做 numerical reasoning（"差额是多少"）—— 留给 Math RAG (P1 #3)
- 不做时序冲突（"先后顺序") —— KG snapshot
- 不做单文档自相矛盾 —— 已有 faithfulness check
- 不做用户输入 vs RAG 结果的冲突 —— 不同维度
- 不做 5+ source 全笛卡尔（成本过高）—— top-3 source

### 8.3 不要的东西

- ❌ 不要在所有 query 上启用（仅跨源 query 触发）
- ❌ 不要把 disagreement 隐藏（这就是核心价值）
- ❌ 不要让 LLM 自行调和冲突（让用户决定）
- ❌ 不要做"自动可信度排序"（A 比 B 可信？太主观）

---

## 9 与既有 plan 协同

| plan | 协同 |
|---|---|
| `rag-evaluation-deep-dive-2026-q2.md` | Citation + Atomic Fact 与本 plan 共用 claim 抽取 |
| `rag-self-consistency-2026-q3.md`（P0 #2） | NLI 投票降误判 |
| `rag-feedback-loop-2026-q3.md`（P0 #5） | 用户标"这是真冲突 / 假冲突" 反哺训练 |
| `rag-multimodal-math-chart-2026-q3.md`（P1 #3） | 数值冲突时联动 Math 验证 |
| `rag-kg-snapshot-deep-dive-2026-q2.md` | KG diff overlay 复用视觉 |
| `industry-rules-productization-2026-q2.md`（P0-1） | 行业规则可定义"哪些场景必须查冲突" |

---

## 10 关键洞察

1. **底层武器已就位**：NLI verifier 215 行 + claim_verifier 216 行 + faithfulness 82 行 已是合成层基础
2. **缺的是 workflow 协调**：本 plan 不重做 NLI，仅做"调度 + 聚合 + 呈现"
3. **冲突主动呈现是真差异化**：大多数 RAG 让 LLM 自行调和，MimirQ 主动标注 = 给用户决定权
4. **与 P0 #2 self-consistency 强协同**：单次 NLI 易误判，多次 voting 降误差
5. **客户场景验证**：财报对比 / 法规版本 / 合同条款 是 B 端 RAG 三大刚需
