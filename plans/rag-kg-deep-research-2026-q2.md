# RAG × 知识图谱深度调研报告（2026 Q2）

> **编写日期**：2026-04-18
> **背景**：用户提出 5 条关于 KG-RAG 的核心论断，要求用 2024–2026 业界前沿文献逐条验证，并给出我方 KG 栈（`app/rag/kg/`）的对标 gap 与借鉴方向。
> **本文定位**：前三份 plan 的 **KG 专项深化** —— `rag-capability-gap-2026-q2.md` 给出 16 章分层对标；`rag-deep-research-2026-q2.md` 给出 23 章带 benchmark 数字；`rag-eval-dataset-deep-dive-2026-q2.md` 给出评测集路线；本文专注 **KG 这一维度**，回答"怎么用 KG、为何不转 SPARQL、与普通检索路怎么协同"。

## 用户的 5 条论点（本文逐条验证）

1. **KG 是 RAG 的一个数据源**：既可结构化查询也可直接 RAG
2. **不需要转 SPARQL / Cypher**，做"**实体链接 + 采路径**"就行
3. **路径采样不需要太准**，**LLM 够强**，自己读子图做 MRC 就是 KG-RAG
4. **转 Cypher 泛化性很差**，检索式 + LLM 比语义解析更稳
5. **图谱最大用处是网络分析 / 多跳推理 / 路径发现**；这里的"多跳"是**图谱上的多跳**（不同于文本多跳）

**本文结论（先行）**：**5 条论点全部被 2024–2026 业界主流路线验证**。本文逐条给出文献、量化对比、我方落地建议。

---

## 第 1 章　方法论：KG-RAG 的三派系

KG-RAG 在 2024–2026 的演进已清晰收敛到三条路线：

### 1.1 符号式（text-to-SPARQL / text-to-Cypher） —— **渐衰**

- **代表**：早期 KBQA（T5 系微调）、Text2SPARQL 竞赛历届方案
- **机制**：NL → 逻辑形式（SPARQL/Cypher）→ 在 KG 上执行 → 回填答案
- **失败模式（详见 §4）**：triple-flip、compositional generalization 崩、OOV entity linking 崩、cross-schema 换 KG 就废、catastrophic forgetting
- **2025 状态**：Text2SPARQL Challenge 2025 冠军 **mKGQAgent 明确声明不做 SFT**，转向 agentic 路线，说明业界已放弃端到端 seq2seq 生成

### 1.2 神经式（GNN-RAG / D-RAG / 嵌入检索）—— **有位，但边缘**

- **代表**：GNN-RAG（ACL 2025）、D-RAG（EMNLP 2025）、图嵌入 + ANN 召回
- **机制**：GNN 在稠密子图上找候选答案 + 最短路径 → verbalize 给 LLM
- **定位**：在大规模 KG 上做高效初筛（GNN 优势场景），但**解释性弱、难灵活应对新问题类型**

### 1.3 Agentic / LLM-as-Searcher（**2024+ 主流**）

- **代表**：**Think-on-Graph (ToG, ICLR 2024)、ToG-2.0、Paths-over-Graph (PoG, WWW 2025)、Plan-on-Graph、FiDeLiS、GoG、KnowPath、RAR、R2-KG、ODA**
- **机制**：LLM 作为 agent，在 KG 上 **beam search / 迭代探索**实体与关系 → 采样多条候选路径 → verbalize → LLM MRC 回答
- **训练-free**：不改 LLM 参数，不做 SFT，plug-and-play
- **与用户论点对应**：**完全印证**用户"链接 + 采路径 + LLM MRC"主张

**三派系对标表**

| 维度 | 符号式 | 神经式 | Agentic (LLM-as-Searcher) |
|---|---|---|---|
| 是否需要 SFT | ✅ 要 | ✅ 要 | ❌ 不要 |
| 泛化性（新 schema / OOD） | ❌ 差 | 🟡 中 | ✅ 好 |
| 解释性 | ✅ 执行可审 | ❌ 黑盒 | ✅ 路径可审 |
| 更新成本（KG 改动） | 🟡 要重训 | 🟡 要重训 | ✅ 零成本 |
| 在大 KG 上效率 | ✅ 执行快 | ✅ GNN 快 | 🟡 LLM 调用贵 |
| 问题复杂度上限 | ❌ 模板化 | 🟡 中 | ✅ 多跳多实体 |
| 2024–2026 文献占比 | ↓ 低 | → 平 | ↑ 高 |

---

## 第 2 章　用户 5 论点的业界验证

### 论点 1：KG 是 RAG 的一个数据源 —— ✅ 强验证

- **Graph RAG Survey（ACM TOIS 2025，DOI 10.1145/3777378）** 明确定义 GraphRAG = RAG 的子类，以图结构元素（nodes / triples / paths / subgraphs）作为检索目标
- **2026 enterprise 共识**：生产级 RAG 同时维护 **向量嵌入 + KG + 层级索引**，KG 是一种索引形式
- **Microsoft GraphRAG / LightRAG / LinearRAG / PathRAG / LazyGraphRAG** 都不假设 KG 是唯一源，是**补充源**

### 论点 2：不需要转 SPARQL / Cypher，做链接 + 采路径 —— ✅ 强验证

- **ToG**（ICLR 2024）：LLM 作 agent 做 beam search 探索 KG，**无 SPARQL 生成**
- **PoG / Paths-over-Graph**（WWW 2025）：三阶段动态多跳路径探索 + 3 步剪枝（图结构 / LLM / SBERT 组合剪枝）
- **Plan-on-Graph**：子目标分解 → guide 子图构建 → 多跳路径探索 → 反思自纠正
- **mKGQAgent（Text2SPARQL 2025 冠军）**：尽管该赛道叫 Text2SPARQL，冠军方案本质是 **LLM agent + planning + entity linking + query refinement**，非监督微调

### 论点 3：路径采样不需要太准，LLM 够强 —— ✅ 强验证（含量化）

- **PoG vs ToG**：PoG 的核心创新是**三步剪枝**使路径"够好即可"，结果反而：
  - 比 ToG 平均 +18.9% accuracy（5 个 KGQA 基准）
  - **PoG + GPT-3.5-Turbo 超过 ToG + GPT-4 达 23.9%**
  - Token 用量 **-50%**，精度偏差仅 ±2%
- **Plan-on-Graph**：LLM calls **-40.8%**，output tokens **-76.2%**，speedup **4×**
- **GNN-RAG**：GNN 不追求最短路径唯一性，而是给 LLM 多条候选 verbalized 路径

### 论点 4：转 Cypher 泛化差 —— ✅ 强验证

- **MCWQ 基准**（Multilingual Compositional Wikidata Questions）：跨语言 compositional generalization **全线失败**，负相关强：accuracy vs compound divergence
- **Triple-flip**：T5 系主流失败模式，(subj, rel, obj) 常被预测为 (obj, rel, subj)
- **OOV entity linking**：大本体上训练集覆盖不全即崩
- **Cross-schema**：换 KG 即废
- **Semantic but not syntactic**：在大 KG 上（如 Mondial），LLM 生成语法对但语义错的 SPARQL（ARUQULA 报告，arXiv:2510.02200）
- **Text2SPARQL 2025 冠军走 agentic**：验证"端到端生成 SPARQL"路线集体遗弃

### 论点 5：图谱最大用处是网络分析 / 多跳 / 路径发现 —— ✅ 强验证（含商业案例）

| 数据点 | 来源 |
|---|---|
| GraphRAG **80% vs vanilla RAG 50%** | Lettria / AWS，2024 Dec |
| 企业基准 **3.4× 提升** | Diffbot 2023 |
| 全局问题 **72–83% comprehensiveness** | Microsoft 2024 |
| 某投资机构：**billions of traversals/day, sub-150ms 延迟** | 2026 enterprise 报告 |
| **MultiFraud** HGNN 反欺诈多任务框架（供应链金融） | ScienceDirect 2023 |
| **HKTGNN** 供应链风险 hierarchical knowledge transferable GNN | arXiv:2411.08550 |
| **LazyGraphRAG** 索引成本降到原 **0.1%** | Microsoft 2025 |
| 2026 杀手级场景：**fraud rings / supplier dependencies / counterparty exposure / root-cause** | 多份 2026 enterprise 综述 |
| **Federated Graph RAG**（跨医院、跨银行协作） | 2026 趋势 |

**关键区分（非常重要）**：
- **文本多跳**（HotpotQA / MuSiQue）= 需要多段文本证据拼接，但不一定在图上走多跳
- **图谱多跳**（WebQSP / CWQ / GrailQA）= 在 KG 上**必须走 N 条边**才能到答案

KG-RAG 的独特价值是**图谱多跳**，用文本 RAG 做 K-hop 路径发现是**不可能**的。

---

## 第 3 章　路径采样 vs 语义解析的量化对比

### 3.1 PoG vs 各 baseline（WebQSP / CWQ / GrailQA）

| 方法 | WebQSP | CWQ | GrailQA | 备注 |
|---|---|---|---|---|
| Direct GPT-4 | — | — | — | 无 KG 辅助 |
| ToG + GPT-3.5 | baseline | baseline | baseline | ICLR 2024 |
| ToG + GPT-4 | +≈10 | +≈10 | +≈10 | 代价：token ×2+ |
| **PoG + GPT-3.5** | **>ToG+GPT-4 +23.9%** | 同趋势 | 同趋势 | token -50% |
| PoG + GPT-4 | 最高 | 最高 | 最高 | SOTA |
| Plan-on-Graph + GPT-4 | 超 ToG | 超 ToG | **超所有 KG-augmented LLM SFT baseline** | LLM calls -40.8% |

**工程洞察**：**路径采样 + LLM MRC 的 Pareto 前沿比 text-to-SPARQL 优越一个量级**，因为：
1. 采样方法 plug-and-play，不需要 SFT
2. 模型升级自动获益（GPT-3.5 → GPT-4 不需要改 pipeline）
3. 解释性由 verbalized path 天然提供
4. KG schema 变更零成本（不需要重训）

### 3.2 text-to-SPARQL 的工程代价（综合失败模式）

| 成本项 | 描述 |
|---|---|
| SFT 数据构造 | (NL, SPARQL) 对标注 = 专家时间 |
| Schema 绑定 | 每换 KG 要重新训 |
| Cross-lingual | 每加一种语言要大量扩展 |
| 语法 → 语义差距 | 语法对不等于语义对，需额外 execute-and-verify 层 |
| Error propagation | 实体 / 关系错一个 → 查询全错 |
| LLM 更新 | LLM 升级可能 regress（catastrophic forgetting） |
| 维护 | 线上模型 regression 需持续回归测试集支撑 |

**相比之下 agentic 路径探索**：零 SFT、零 schema 绑定、零语言绑定、LLM 换就升级、维护仅测 prompt。

---

## 第 4 章　不转 Cypher 的失败模式清单（给工程师的警告）

| 失败模式 | 症状 | 论文 |
|---|---|---|
| **Triple-flip** | (subject, relation, object) 与 (object, relation, subject) 互换 | MDPI Applied Sciences |
| **Compositional generalization** | 训练见过"A(B)"+"C(D)"，见"A(D)"崩 | MCWQ TACL |
| **OOV entity** | 训练集没见过的实体 → linking 失败 | 多个 KBQA survey |
| **Cross-schema** | 换 Wikidata 为自建 KG 即废 | SPARQL-QA-v2 |
| **Cross-lingual** | 中文训好英文仍差 | MCWQ |
| **Semantic valid syntax invalid** | 语法对查询出空 / 查询错 | ARUQULA |
| **Multi-relation path confusion** | 多跳关系链中间某步错 | 多个 2025 KBQA |
| **Aggregation / filter 失败** | COUNT / FILTER / ORDER BY 被生成错 | CypherBench |

**工程建议**（如果已经有 text-to-Cypher 模块）：**保留它做"简单单跳结构化查询"的快速通道**（问"X 的 Y 属性是什么"），**复杂多跳 / 多实体一律走 agentic 路径探索**。

---

## 第 5 章　子图 → LLM 的 5 种表示方式

路径采样后，如何把子图喂给 LLM？

### 5.1 Verbalized triples（最常用）

```
(张三, 任职于, ACME) (ACME, 子公司, BigCorp) (BigCorp, 位于, 上海)
↓
张三任职于 ACME；ACME 是 BigCorp 的子公司；BigCorp 位于上海。
```

优势：LLM 对自然语言最友好；劣势：失结构感。

### 5.2 Path string

```
张三 --任职于--> ACME --子公司--> BigCorp --位于--> 上海
```

优势：保留路径感，适合多跳；劣势：多实体融合差。

### 5.3 Graph prompt（JSON/YAML）

```yaml
entities:
  - id: 张三
    type: 人
  - id: ACME
    type: 公司
relations:
  - (张三, 任职于, ACME)
  - (ACME, 子公司, BigCorp)
```

优势：结构保真；劣势：prompt 长、LLM 容易忽略。

### 5.4 Community report（Microsoft GraphRAG 风格）

对子图 / 社区用 LLM 生成摘要，作为 context。

优势：可预计算 + 高层问题表现好；劣势：细节丢失。

### 5.5 Reasoning chain（RAR 风格）

对齐 KG path 和自然语言步骤，形成可解释推理链。

优势：可审 + 可用作训练数据；劣势：生成成本高。

### 5.6 业界 best practice

**混用**：简单事实 → verbalized triples；多跳 → path string + verbalized triples 组合；全局摘要 → community report；需解释 → reasoning chain。

**我方现状**：`app/rag/kg/community.py` 已有 community report（LLM 摘要），但**其他 4 种表示是否在 `search/expand.py` 里规范化输出，需确认**。

---

## 第 6 章　网络分析 / 多跳 / 路径发现的杀手级场景

### 6.1 金融反欺诈

**查询示例**：
- "找出在过去 90 天内与张三有间接资金往来的所有实体（最多 3 跳）"
- "这笔交易与历史已标记的欺诈环路有多少重合节点？"

**为什么 KG 必需**：text RAG 根本无法表达"3 跳内的资金路径"。

**业界**：
- **MultiFraud**（ScienceDirect）：HGNN 做供应链金融反欺诈
- 某投行 **billions of traversals/day + <150ms 延迟**
- **Federated GraphRAG**：2026 将出现跨行联合反欺诈，同时保护客户隐私

### 6.2 供应链依赖

**查询示例**：
- "若供应商 A 停产，下游哪些成品受影响？风险敞口多少？"
- "关键零件 X 的替代供应商，按质量、成本、地理风险排序"

**业界**：HKTGNN 做层级化风险评估。

### 6.3 合规与反洗钱（KYC/AML）

**查询示例**：
- "该账户的实际控制人穿透 5 层，是否含 PEP（政治暴露人）？"
- "公司 A 与公司 B 的最短关联路径是什么？是否经过制裁名单？"

### 6.4 根因分析（IT Ops / 生产）

**查询示例**：
- "服务 X 延迟飙升，从 X 出发向上游追溯 3 跳，哪些服务 / 配置变更与告警时间窗相关？"

### 6.5 医药与研发

**查询示例**：
- "药物 A 通过几条代谢通路与疾病 B 相关？每条通路的证据强度？"
- "症状 X + 药物 Y + 病史 Z 的联合推理"

### 6.6 法律检索

**查询示例**：
- "本案引用的 5 个判例，它们引用的先例的先例是什么？"
- "合同条款 A 与法规 B / C / D 的冲突路径"

### 6.7 组织 / 人员网络

**查询示例**：
- "两位员工的协作路径（经过项目 / 产品 / 代码库）"
- "离职员工 X 的工作依赖 transfer 给谁"

**共同特征**：所有杀手级场景都需要**显式路径 + 可解释 + K 跳遍历**。纯文本 RAG 无能为力。

---

## 第 7 章　2024–2026 关键论文完整梳理

### 7.1 LLM-as-Searcher 家族（核心）

| 论文 | 年 | 核心贡献 |
|---|---|---|
| **Think-on-Graph (ToG)** (arXiv:2307.07697) | ICLR 2024 | 奠基作：LLM beam search on KG，无 SFT，9 基准 6 SOTA |
| **ToG-2.0** (arXiv:2407.10805) | 2024 | 结构化 + 非结构化紧耦合迭代，LLaMA-2-13B 达 GPT-3.5 水平 |
| **Paths-over-Graph (PoG)** (arXiv:2410.14211) | WWW 2025 | 三阶段动态路径 + 3 步剪枝，比 ToG +18.9% |
| **Plan-on-Graph** | KDD 系 | Guidance/Memory/Reflection，token -76% |
| **FiDeLiS** | 2025 | 可验证推理步骤锚定 |
| **Generate-on-Graph (GoG)** | 2025 | Thinking-Searching-Generating，LLM 作 Agent + KG |
| **KnowPath** | 2025 | 内外知识协作 + 可解释子图 |
| **Reason-Align-Respond (RAR)** | 2025 | LLM reasoning 与 KG 路径对齐 |
| **R2-KG** | 2025 | 双 agent：Operator 收集 + Supervisor 决策 |
| **Observation-Driven Agent (ODA)** | 2025 | 观察-行动-反思循环 |

### 7.2 神经式

| 论文 | 年 | 贡献 |
|---|---|---|
| **GNN-RAG** (aclanthology 2025.findings-acl.856) | ACL 2025 | GNN 稠密子图推理 + 最短路径 verbalize |
| **D-RAG** (aclanthology 2025.emnlp-main.1793) | EMNLP 2025 | 可微子图采样 + Gumbel-Softmax + 可微 prompt 构建 |

### 7.3 图构建 / 成本优化

| 论文 / 系统 | 年 | 贡献 |
|---|---|---|
| **Microsoft GraphRAG** | 2024 | 社区检测 + LLM community reports，企业基准 86% vs 32% |
| **LazyGraphRAG** | 2025 Jun | 索引成本降到原 **0.1%** |
| **LightRAG** (OpenReview bbVH40jy7f) | 2024–25 | 双层检索，token -6000×，延迟 -30% |
| **HippoRAG / HippoRAG2** | NeurIPS 2024 | PPR 神经生物启发，10–30× 便宜 |
| **PathRAG** | 2025 | flow-based pruning，context -44% |
| **OG-RAG** | 2025 | 本体约束，减幻觉 40% |
| **LinearRAG** (Oct 2025) | — | Relation-free graph construction，线性复杂度 |
| **LEGO-GraphRAG** (VLDB) | 2025 | 模块化子图 / 路径 / 检索三组件 |
| **AutoGraph-R1** | AAAI 2026 | 端到端 RL KG 构建 |
| **AGRAG / SUBQRAG** | 2026 | 自适应推理 + 子问题驱动 |
| **GFM-RAG** | NeurIPS 2025 | Graph Foundation Model for RAG |
| **"You Don't Need Pre-built Graphs for RAG"** | AAAI 2026 | 挑战"必须预建图"的自适应推理结构 |

### 7.4 Text2SPARQL / Cypher（保留知识）

| 系统 | 状态 |
|---|---|
| **mKGQAgent** | Text2SPARQL 2025 冠军，agentic + 无 SFT |
| **ARUQULA / SPINACH** (arXiv:2510.02200) | LLM agent 遍历 KG 生成 SPARQL |
| **Multi-Agent GraphRAG** (arXiv:2511.08274) | Text2Cypher 也在 agentic 化 |
| **S2CLite** | Nov 2025 | SPARQL-Cypher 互译，schema-agnostic |
| **Spider4SSC** | — | NL/SQL/SPARQL/Cypher 四元数据集 |

### 7.5 综述与基准

| 论文 | 年 |
|---|---|
| **Graph RAG Survey** (ACM TOIS, DOI 10.1145/3777378) | 2025 |
| **Awesome-GraphRAG** (GitHub DEEP-PolyU) | 持续更新 |
| **GraphRAG-Bench** (ICLR 2026) | 2026 |
| **KGQAGen-10k** | 2025 |
| **CypherBench**（5 域） | 2025 |

---

## 第 8 章　我方 KG 栈现状对标

### 8.1 模块盘点（2026-04-18 核对）

```
app/rag/kg/
├── engine/{core,config,enums,models}.py
├── extraction/
│   ├── extractor.py / hybrid_extractor.py / gliner_extractor.py
│   ├── alias.py / entity_verifier.py
│   ├── relation_processor.py / relation_verifier.py
│   ├── skill_processor.py / backend_router.py
│   ├── parser.py / processor.py / config.py / evidence.py
├── loading/processor.py
├── search/
│   ├── recall.py / expand.py / searcher.py
│   ├── graph_embeddings.py / ranking/
│   ├── query_mode.py / relation_scoring.py
│   ├── cache.py / tracker.py / utils.py
├── quality/
│   ├── kg_completeness_scorer.py
│   └── kg_denoiser.py
├── community.py       (LLM community reports ✓)
├── ontology.py        (schema 存在 ✓)
├── provenance.py
├── snapshot.py        (temporal 基础 ✓)
├── pipeline.py
├── repository.py, schemas.py, models.py, api/, utils.py
```

### 8.2 已实现对标（🟢）

| 能力 | 对标业界 | 本系统位置 |
|---|---|---|
| LLM 实体 / 关系抽取 + verifier | GraphRAG indexer | `extraction/*.py` |
| GLiNER + hybrid 抽取器 | 先进 | `gliner_extractor.py` / `hybrid_extractor.py` |
| Alias 归一 + relation / entity verifier | 工业级 | `alias.py` / `entity_verifier.py` / `relation_verifier.py` |
| 召回 + 扩展 + ranking | GraphRAG local/global 基础 | `search/{recall,expand,ranking}.py` |
| 图嵌入（GNN-RAG 基础） | GNN-RAG 前置 | `graph_embeddings.py` |
| Query mode 多模式 | 先进 | `query_mode.py` |
| Relation scoring | 先进 | `relation_scoring.py` |
| LLM community reports | **对齐 Microsoft GraphRAG** | `community.py`（已 verify 含 LLM） |
| Ontology / schema | 支撑多模式 | `ontology.py` |
| Provenance / snapshot | temporal / 审计基础 | `provenance.py` / `snapshot.py` |
| Denoiser / completeness scorer | 质量治理 | `quality/*.py` |
| Tracker / cache | 工程化 | `search/{tracker,cache}.py` |

**总结**：我方 KG 栈已是**完整的 GraphRAG-indexer 级管线**，对齐 Microsoft GraphRAG 的核心组件。

### 8.3 未实现 / 薄弱（🔴）

| 缺口 | 业界对标 | 影响 |
|---|---|---|
| **ToG 式 LLM-as-searcher beam search** | ToG ICLR 2024 | 多跳复杂问题退化到单跳扩展 |
| **Plan-on-Graph 子目标分解 + 自纠正** | Plan-on-Graph | token 成本高、错误累积 |
| **HippoRAG Personalized PageRank** | HippoRAG NeurIPS 2024 | 多跳召回性能落后 |
| **Microsoft DRIFT search**（query→community→local expand） | GraphRAG | 全局问题性能落后 |
| **Path verbalizer 独立模块 + quality 报告** | ToG / PoG | 子图喂 LLM 质量不可控 |
| **网络分析 API**（K-hop / 路径发现 / centrality / 社区归属） | 生产级 KG 产品 | fraud / supply chain 场景无法支撑 |
| **LazyGraphRAG 低成本索引** | Microsoft 2025 | 索引成本占据大头 |
| **AAAI 2026 no-pre-built-graph 自适应推理** | AAAI 2026 | 依赖预建图，更新不及时 |
| **text-to-Cypher 简单查询快速通道**（若要保留，需与 agentic 协同） | Multi-Agent GraphRAG | 简单查询不必走 LLM-agent |
| **子图 → LLM 5 种表示的规范化输出** | 业界 best practice | 不同场景用同一表示会有性能差异 |
| **Federated GraphRAG 跨源** | 2026 趋势 | 未来合规 / 跨企业场景 |

---

## 第 9 章　Gap 清单（按优先级）

### P0（1–3 周，必须做）

| Gap | 对标 | 收益 |
|---|---|---|
| **LLM-as-searcher agentic beam search**（ToG 风格） | arXiv:2307.07697 | 多跳复杂问题质量飞跃，训练-free |
| **Path verbalizer 统一模块**（5 种表示） | ToG / PoG 实践 | 子图喂 LLM 质量可控，A/B 可测 |
| **子目标分解 + 反思**（Plan-on-Graph 风格） | Plan-on-Graph | LLM 调用 -40%，token -76% |

### P1（1–2 月，高 ROI）

| Gap | 对标 | 收益 |
|---|---|---|
| **Personalized PageRank 召回** | HippoRAG NeurIPS 2024 | 多跳召回成本降 10–30× |
| **DRIFT search**（community → local） | Microsoft GraphRAG | 全局问题回答质量提升 |
| **网络分析 API**（K-hop / 路径发现 / centrality） | 生产级 KG 产品 | fraud / supply chain / KYC 场景 |
| **LazyGraphRAG 成本模式** | Microsoft 2025 | 索引成本降到 0.1% |
| **GraphRAG-Bench 内部小跑** | ICLR 2026 | 量化我方 vs LightRAG vs HippoRAG |

### P2（2–6 月，补强）

| Gap | 对标 | 收益 |
|---|---|---|
| **SubQRAG 子问题动态** | SubQRAG 2026 | 动态 graph RAG |
| **AutoGraph-R1 自动图构建** | AAAI 2026 | 降低人工 schema 成本 |
| **GFM-RAG foundation model** | NeurIPS 2025 | 等代码 |
| **LinearRAG relation-free** | Oct 2025 | 构建成本更低 |
| **Federated GraphRAG PoC** | 2026 趋势 | 合规前瞻 |

---

## 第 10 章　建议优化（代码粒度）

### P0-1：`app/rag/kg/search/agentic_beam_search.py`

**对标**：ToG ICLR 2024

**接口**：
```python
async def agentic_beam_search(
    query: str,
    topic_entities: list[str],
    max_depth: int = 3,
    beam_width: int = 3,
    llm: BaseLLMClient = ...,
) -> list[ReasoningPath]:
    """
    LLM 驱动的双 beam search（实体 + 关系）。
    训练-free，每一步 LLM 决定是扩展哪个实体和哪种关系。
    返回多条 verbalized 推理路径。
    """
```

**实现要点**：
1. 从 `topic_entities` 出发
2. 每步取当前 frontier，LLM 选 `beam_width` 条最相关关系
3. 展开到邻居实体，LLM 评估每条是否继续
4. max_depth 后或 LLM 判定答案充分即停
5. 输出所有幸存路径的 verbalized 版本

**预计收益**：复杂多跳问题 accuracy +15–25%（参考 ToG 论文）。

### P0-2：`app/rag/kg/search/path_verbalizer.py`

**对标**：ToG / PoG 实践 + 第 5 章 5 种表示

**接口**：
```python
class PathVerbalizer:
    def as_triples(self, subgraph: Subgraph) -> str: ...
    def as_path_string(self, path: Path) -> str: ...
    def as_graph_yaml(self, subgraph: Subgraph) -> str: ...
    def as_reasoning_chain(self, path: Path, query: str) -> str: ...
    # Community report 复用 community.py
```

**配套 quality 报告**：
- 每种表示在不同 query_type 下的 faithfulness / answer_relevancy
- 长度 / token 成本
- LLM readability 打分

### P0-3：`app/rag/kg/search/plan_on_graph.py`

**对标**：Plan-on-Graph

**机制**：Guidance（子目标分解）+ Memory（已探索记录）+ Reflection（自纠正）

**预计收益**：LLM calls -40%，tokens -76%（参考 Plan-on-Graph 论文）。

### P1-1：`app/rag/kg/search/pprank.py`

**对标**：HippoRAG NeurIPS 2024

**机制**：实体 + 关系权重 → PPR 分布 → top-K 节点作候选

**预计收益**：多跳召回成本降 10–30×。

### P1-2：`app/rag/kg/search/drift_search.py`

**对标**：Microsoft GraphRAG DRIFT

**流程**：query → community 摘要匹配 → 选 top 社区 → 内部 local expand

**预计收益**：全局问题 comprehensiveness +20%（参考 Microsoft）。

### P1-3：`app/rag/api/v1/network_analysis.py`

**新增 API 端点**：
```
POST /api/v1/kg/network/k_hop_neighbors
POST /api/v1/kg/network/shortest_path
POST /api/v1/kg/network/paths_between    (所有 K 跳内路径)
POST /api/v1/kg/network/centrality       (degree / betweenness / pagerank)
POST /api/v1/kg/network/community_of     (节点所属社区)
POST /api/v1/kg/network/connected_component
```

**收益**：fraud / supply chain / KYC 场景开箱可用。

### P1-4：`app/rag/kg/search/lazy_indexer.py`

**对标**：LazyGraphRAG Microsoft 2025

**机制**：按需构建而非全量预建；推迟 community report 生成到查询命中社区时

**收益**：索引成本降到 0.1%。

### P1-5：`app/rag/evaluation/graphrag_bench_runner.py`

**对标**：GraphRAG-Bench ICLR 2026

**功能**：在我方 KG 上跑 GraphRAG-Bench L1/L2/L3 子集，对比：
- 我方 KG 栈
- LightRAG（Clone 安装）
- HippoRAG（如可）
- Vanilla RAG（向量 baseline）

**输出**：accuracy × cost × latency 表 + 按复杂度切片报告

### P2-1：`app/rag/kg/extraction/auto_graph_r1.py`

**对标**：AAAI 2026 AutoGraph-R1

**等代码放出后跟进**。

### P2-2：`app/rag/kg/search/subqrag.py`

**对标**：SubQRAG 子问题驱动动态 GraphRAG

---

## 第 11 章　与"普通检索路"（small2big = 向量 + ES）的协同

呼应前一份评测集报告：三路协同架构建议。

### 11.1 分层架构

```
User Query
    ↓
[Layer 1: Lightweight Router]      ← TF-IDF + SVM（RAGRouter-Bench 93% 准确）
    ↓
分类到 query_type ∈ {factual, multi_hop, structured, summary, unanswerable}
    ↓
[Layer 2: 并行检索]
    ├─ factual / summary → small2big（向量 + ES）
    ├─ structured（按 schema 直查） → KG 路（简单路径 + verbalize）
    └─ multi_hop → KG 路（agentic beam search + verbalize）
    ↓
[Layer 3: 融合]
    ├─ 单路 → 直接 rerank top-k
    └─ 双路 → RRF fusion + cross-encoder rerank
                    ↓ 若仍冲突
                  LLM as arbiter（verbalized path + text chunk 双 context）
    ↓
[Layer 4: 生成 + 引用]
    LLM MRC over (text_chunks, verbalized_paths, community_report_if_summary)
    ↓
[Layer 5: 证据输出] citation both 文本 + KG path
```

### 11.2 关键设计原则

1. **KG 不是文本 RAG 的替代，是补充** —— 对应用户论点 1
2. **绝大多数用户问题用文本 RAG 就够** —— 不要强行走 KG
3. **KG 的入口是 query_type 判定**：structured / multi_hop / 网络分析专用查询 → KG
4. **KG 内部默认走 agentic**，不走 Cypher —— 对应用户论点 2/4
5. **LLM 做 MRC** 消费 verbalized paths + text chunks —— 对应用户论点 3
6. **多跳 = 图上多跳** —— 对应用户论点 5

### 11.3 实验设计（接上一份评测集报告）

用 Stage 2/3 评测集的 **query_type 切片** 测：

| query_type | 预期最优方案 | 验证方法 |
|---|---|---|
| factual | 纯向量（small2big） | 测 answer_em / cost / latency |
| summary | 向量 + community report | 测 comprehensiveness |
| structured（按属性查） | KG 简单路径 | 测 EM + 延迟 |
| multi_hop（图上多跳） | KG agentic beam search | 测 path F1 + answer EM |
| network_analysis（路径发现 / 邻域） | KG network API 直查 | 测返回路径完整性 |
| unanswerable | 任何路 + abstain | 测拒答率 |

### 11.4 与方案 A/B/C 的映射（用户之前提的三方案）

| 用户方案 | 本架构实现 |
|---|---|
| ① 意图分发 | 本架构 Layer 1 Router |
| ② 双路合并 | 本架构 Layer 2+3（RRF + rerank） |
| ③ Agentic 分解 | 本架构 KG 侧的 agentic beam search + Plan-on-Graph 兜底 |

**所以本架构 = 三方案的分层融合**，不需要二选一。

---

## 第 12 章　参考资料清单

### LLM-as-Searcher 家族
- [Think-on-Graph (arXiv:2307.07697)](https://arxiv.org/abs/2307.07697) ICLR 2024
- [ToG-2.0 (arXiv:2407.10805)](https://arxiv.org/abs/2407.10805)
- [Paths-over-Graph (arXiv:2410.14211)](https://arxiv.org/abs/2410.14211) WWW 2025
- [PoG GitHub](https://github.com/SteveTANTAN/PoG)
- Plan-on-Graph（KDD 系）
- FiDeLiS / GoG / KnowPath / RAR / R2-KG / ODA

### 神经式
- [GNN-RAG (ACL 2025)](https://aclanthology.org/2025.findings-acl.856.pdf)
- [D-RAG (EMNLP 2025)](https://aclanthology.org/2025.emnlp-main.1793.pdf)

### 图构建 / 成本
- [Microsoft GraphRAG](https://github.com/microsoft/graphrag)
- LazyGraphRAG（Microsoft 2025 Jun）
- [LightRAG (OpenReview)](https://openreview.net/forum?id=bbVH40jy7f)
- HippoRAG / HippoRAG2（NeurIPS 2024）
- [LEGO-GraphRAG (VLDB)](https://www.vldb.org/pvldb/vol18/p3269-cao.pdf)
- LinearRAG（Oct 2025）
- PathRAG / OG-RAG
- [AutoGraph-R1 / SUBQRAG / GFM-RAG](https://github.com/DEEP-PolyU/Awesome-GraphRAG) AAAI 2026 / NeurIPS 2025
- "You Don't Need Pre-built Graphs for RAG"（AAAI 2026）

### Text2SPARQL / Cypher（残余）
- [ARUQULA (arXiv:2510.02200)](https://arxiv.org/html/2510.02200v1)
- [Multi-Agent GraphRAG (arXiv:2511.08274)](https://arxiv.org/pdf/2511.08274)
- [Text-to-SPARQL Goes Beyond English (arXiv:2507.16971)](https://arxiv.org/html/2507.16971)
- mKGQAgent（Text2SPARQL 2025 冠军）
- [RGR-KBQA (COLING 2025)](https://aclanthology.org/2025.coling-main.205.pdf)
- S2CLite / Spider4SSC

### 综述与基准
- [Graph RAG Survey (ACM TOIS 2025)](https://dl.acm.org/doi/10.1145/3777378)
- [Awesome-GraphRAG](https://github.com/DEEP-PolyU/Awesome-GraphRAG)
- [GraphRAG-Bench (ICLR 2026)](https://github.com/GraphRAG-Bench/GraphRAG-Benchmark)
- WebQSP / CWQ / GrailQA / KGQAGen-10k / CypherBench
- [Enterprise GraphRAG 2026 综述](https://www.programming-helper.com/tech/graphrag-2026-knowledge-graphs-rag-enterprise-ai)

### 企业 / 网络分析
- MultiFraud（ScienceDirect 2023）
- HKTGNN（arXiv:2411.08550）
- [NStarX 2026-2030 前瞻](https://nstarxinc.com/blog/the-next-frontier-of-rag-how-enterprise-knowledge-systems-will-evolve-2026-2030/)

### 本项目相关 plan（交叉引用）
- `plans/rag-capability-gap-2026-q2.md` —— 16 章分层对标
- `plans/rag-deep-research-2026-q2.md` —— 23 章带 benchmark
- `plans/rag-eval-dataset-deep-dive-2026-q2.md` —— 评测集建设路线
- **本文** `plans/rag-kg-deep-research-2026-q2.md` —— KG 专项深化

---

## 结论

1. **用户 5 条论点全部被 2024–2026 主流文献验证**：KG 是 RAG 的一个源、不必转 SPARQL/Cypher、路径采样 + LLM MRC 是主流、Text2SPARQL 泛化差、网络分析 / 多跳 / 路径发现是 KG 杀手级场景。
2. **我方 KG 栈已对齐 Microsoft GraphRAG 的 indexer 核心**（抽取 / 社区 / schema / provenance / snapshot / denoiser 都在），但**缺 agentic searcher 侧**（ToG / PoG / Plan-on-Graph）。
3. **最值得做的 P0** = `agentic_beam_search.py` + `path_verbalizer.py` + `plan_on_graph.py`；训练-free、3 周落地、效果显著。
4. **P1 围绕网络分析 API + PPR + DRIFT + LazyGraphRAG 降本** —— 把 KG 价值外放给业务侧。
5. **与普通检索路的协同** = 轻量 router + 双路并行 + 复杂查询 agentic 兜底（与用户之前提的三方案形成分层统一）。

**下一步**：将 P0 三项分别拆成 ~800–1500 行的独立实施 plan。

---

> **后续可独立拆的子 plan**：
> - `plans/kg-agentic-beam-search.md`（ToG 风格实现）
> - `plans/kg-path-verbalizer.md`（5 种表示 + 质量报告）
> - `plans/kg-plan-on-graph.md`（子目标分解 + 反思）
> - `plans/kg-pprank-retriever.md`（HippoRAG 风格）
> - `plans/kg-drift-search.md`（community → local expand）
> - `plans/kg-network-analysis-api.md`（K-hop / 路径 / centrality API）
> - `plans/kg-lazy-indexer.md`（LazyGraphRAG 模式）
> - `plans/kg-graphrag-bench-runner.md`（内部基准评测）
