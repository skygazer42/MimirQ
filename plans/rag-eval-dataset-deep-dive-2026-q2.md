# RAG 评测集深度调研与建设路线（2026 Q2）

> **编写日期**：2026-04-18
> **背景**：我方知识问答系统含两路：
>   1) 普通检索（small-to-big = 向量 + ES）
>   2) 知识图谱（含 schema）
> **方案权衡**：
>   1) 意图分发 → 简单走向量，结构/多跳走 KG
>   2) RAGFlow 式双路并行 + 合并
>   3) Agentic RAG 分解迭代
> **用户观察**：方案 1 意图不准；方案 2 结果冲突；方案 3 分解错 + 慢
> **核心主张**：**RAG 的第一步不是选架构，是建评测集**。没有评测，所有架构讨论都是空话。"先松后紧" = 先搭最小能区分的评测，再逐步扩规模和收紧指标。
> **交付目标**：一份可直接落地的评测集建设路线 + 业界评测集完整借鉴清单 + 三方案的实证评估设计。

---

## 1. 为什么"评测集优先"不是口号，是铁律

### 1.1 三方案各自的失败模式都是**可评测的**

| 方案 | 声称问题 | 评测集应测量的量 |
|---|---|---|
| ① 意图分发 | "意图不准" | 路由准确率（routing accuracy / macro-F1）+ 误路由导致的端到端下降（Δfaithfulness / Δcitation） |
| ② 双路并行合并 | "会冲突" | 两路 top-k 的**冲突率**（同一实体给出矛盾事实的比例）+ 合并后的净增益（vs 单路最优） |
| ③ Agentic 分解 | "分解错、慢" | 子查询分解 F1（vs 标注路径）、平均迭代步数、P95 延迟、token cost、失败率 |

**没有评测集，以上每个问题都只能靠"感觉"判断 → 架构讨论会陷入无限的 a/b/c 循环。**

### 1.2 学术界同样的教训

- **CRAG**（Meta，arXiv:2406.04744）：即使 SOTA LLM + RAG，准确率也仅 **44%**（无 RAG 时 34%）—— 证明"感觉良好"的系统真实表现远低于预期
- **KGQAGen 2025 审计**：WebQSP 这种经典 KBQA 基准，**事实正确率仅 52%**，静态 split 被 LLM 记忆化导致虚高
- **Vectara NAACL 2025**（arXiv:2410.13070）：切块配置的影响 ≥ embedding 选择；若无评测集，工程师永远在"换 embedding 而非调切块"里打转
- **Synthetic RAG Eval 警告**（arXiv:2508.11758）：合成基准**系统性低估任务难度**（因问题简单、表层重合多）→ 合成可起步但必须混真实用户流量

### 1.3 "先松后紧"的工程哲学映射

| 阶段 | 规模 | 标注严格度 | 能回答的问题 |
|---|---|---|---|
| 松（Stage 1）| 50–200 条 | 人工粗标 | 方案 1/2/3 在少量代表性样例上**方向**谁更好 |
| 中（Stage 2）| 500–1000 条 | 合成 + critique filter | 回归测试、参数调优 |
| 紧（Stage 3）| 3000–5000 条 | 合成 + 人工复核 + 领域扩展 | 上线决策、A/B 实验 |
| 极紧（Stage 4）| 动态 + 对抗 | 自动生成 + 红队 hard negative | 防 LLM 记忆、防静态过拟合 |

**关键洞察**：Stage 1 的 200 条**比 Stage 3 的 5000 条对决策更重要**，因为它决定你是否在"对的方向"上继续。

---

## 2. 业界 RAG 评测集全景（9 大类）

### 2.1 综合基准（通用能力画像）

| 基准 | 规模 | 特点 | 关键链接 |
|---|---|---|---|
| **RAGBench** | **100K** | 5 领域（生医 / 通用 / 法律 / 客服 / 金融），含 **TRACe** 可解释指标；重要发现：**finetuned RoBERTa 比 LLM judge 更准** | [HF: galileo-ai/ragbench](https://huggingface.co/datasets/galileo-ai/ragbench) |
| **CRAG**（Meta） | 4409 Q-A | **5 领域 8 类型**，含 web 与 **KG mock APIs**，SOTA 仅 34–44% | [GitHub](https://github.com/facebookresearch/CRAG/) / [arXiv:2406.04744](https://arxiv.org/abs/2406.04744) |
| **BenchmarkQED**（MS 2025） | 自动 | 自动 query 生成 + eval toolkit，LazyGraphRAG 领先 | [MSR blog](https://www.microsoft.com/en-us/research/blog/benchmarkqed-automated-benchmarking-of-rag-systems/) |
| **MS MARCO** | 1M | 通用段落检索，仍是 embedding 训练的事实标准 | — |
| **BEIR** | 15+ 数据集 | 零样本检索权威 | Thakur, NeurIPS 2021 |

### 2.2 多跳推理（对应我方 KG 路 / Agentic 方案）

| 基准 | 规模 / 跳数 | 价值 |
|---|---|---|
| **MultiHop-RAG**（COLM 2024） | 新闻领域多跳 | **首个专为多跳 RAG 设计**的基准 |
| **HotpotQA** | 113K，Wiki 2 跳 | 含 distractor 版本（4–8 干扰段），压力测试检索准确度 |
| **MuSiQue** | 2–4 跳 | 严格去 shortcut，防 LLM 作弊 |
| **2WikiMultiHop** | Wiki 多跳 | 需组合型推理 |
| **BRIDGE**（arXiv:2603.07931） | 长多模态多跳 | ColPali 在多跳下**显著降级**（关键警告） |

**借鉴要点**：HotpotQA distractor 设置是三方案之间**最佳的冲突测试场**——哪种方案能在相似但错误的段落中挑出正确证据。

### 2.3 KGQA（对应我方 KG 路）

| 基准 | 规模 | 跳数 | 警告 |
|---|---|---|---|
| **WebQSP** | 4737 | ≤2 | **事实正确率仅 52%** |
| **CWQ** | 34699 | ≤4 | 组合推理，静态 split 被记忆 |
| **GrailQA** | 大规模 | — | **i.i.d / compositional / zero-shot 三层**，评估泛化最佳 |
| **MetaQA** | — | — | 模板化，低复杂度问题多（25% 答案正确） |
| **KGQAGen-10k**（2025） | 10K | 动态 | LLM 引导、SPARQL 可验证，缓解记忆污染 |
| **Dynamic-KGQA** | 每次生成不同 | 动态 | 统计稳定，防 LLM 过拟合 |

**借鉴要点**：如果我方 KG 有 schema，**完全可以仿 KGQAGen 流程**：用 SPARQL/Cypher 从 KG 随机游走 → LLM 生成自然语言问题 → 反向执行验证答案 → 得到可信的多跳 QA 对。

### 2.4 路由 / 自适应 RAG（**最切合用户场景**）

| 基准 / 论文 | 规模 | 核心设计 |
|---|---|---|
| **RAGRouter-Bench**（arXiv:2602.00296） | **7727 queries** | **分三类：reasoning 52.9% / factual 30.0% / summary 17.1%**；所有 corpora 覆盖所有 query 类型，实现受控交叉比较 |
| **Lightweight Router Baseline**（arXiv:2604.03455） | — | TF-IDF + SVM：**macro-F1 0.928, accuracy 93.2%, 省 28.1% token**；**词法特征比 sentence embedding 高 3.1 F1** |
| **Adaptive-RAG**（Jeong NAACL 2024） | — | T5-Large 做 3 类复杂度 router：no-retrieval / single-hop / multi-hop |
| **MBA-RAG**（COLING 2025） | — | Bandit approach，按 question complexity 自适应选管线 |
| **REIC**（KDD 2025, arXiv:2506.00210） | — | RAG-enhanced intent classification，大规模意图识别 |

**关键借鉴（直接打脸方案 1 的"意图不准"）**：
- RAGRouter-Bench 论文给出的基线 —— **TF-IDF + SVM 就能 93% 准确率**；如果意图分类仅 60–70%，说明：
  - ① 路由特征设计差（该用关键词 + 问题长度 + 是否含实体名等词法特征，而非只用 embedding）
  - ② 训练集太小（他们用 7K+ 样本）
  - ③ 评测口径错（把"不确定"也算错了）
- **不是路由方法论不行，而是我方还没建评测集去优化它**

### 2.5 混合检索评测（对应方案 2 的"冲突"问题）

| 基准 / 结论 | 数据 |
|---|---|
| **T²-RAGBench**（arXiv:2506.12071） | 32908 文表 triple；10 种检索策略对比 |
| — 最强组合：**Hybrid + Cohere Rerank** | Recall@5=**0.816**, MRR@3=**0.605** |
| — Hybrid RRF 单独 | Recall@5=0.695（+17.4% vs BM25） |
| — BM25 vs dense (text-embedding-3-large) | 金融域 **BM25 优于 dense**（0.644 vs 0.587） |
| — **HyDE 反而伤害**金融 | 精确数字、LLM 编造 |
| **NVIDIA Graph+Vector**（财务） | **96% faithfulness** |
| **RRF 调参**（2026 实践） | k=60 是 TREC 级默认，100–300 页的小库用 **k=10–20** |

**对方案 2 的诊断**：
- 方案 2 "会冲突" 的真正原因：**两路的 top-k 分数不在同一尺度上**（向量的 cosine vs BM25 vs KG 的 path score）。
- 业界答案是 **RRF**（Reciprocal Rank Fusion），它**不看分数，只看排名位置**，天然消除尺度冲突。
- 若 RRF 后仍有冲突，用 **cross-encoder rerank** 作第二层融合（T²-RAGBench 证明 MRR 从 0.433→0.605，**+39.7%**）。
- 也就是说："两路会冲突"不是方案 2 的问题，是**融合策略没做对**。

### 2.6 中文 RAG 评测（关键本地化）

| 基准 | 来源 | 特点 |
|---|---|---|
| **CRUD-RAG**（arXiv:2401.17043, TOIS 2025） | IAAR-Shanghai | **最主要中文 RAG benchmark**，覆盖 **CRUD 四任务**（Create/Read/Update/Delete），评测检索器 + context 长度 + KB 构建 + LLM 四要素 |
| **DuReader** | ACL 2018 | 真实用户 query，MRC 经典 |
| **CMRC 2018** | HFL/HIT | Span 抽取式 |
| **DRCD** | — | 繁体中文 MRC |
| **CMMLU / C-MTEB** | — | 中文知识 / embedding 基准 |

**借鉴要点**：
- CRUD-RAG 的 CRUD 四任务设计**非常贴近企业场景**（不光 QA，还包括增/更/删知识后系统能否自洽）
- 其"知识库构建"评测维度直接覆盖了我方双路系统的**入库质量**问题

### 2.7 领域特定（企业落地必需）

| 基准 | 规模 | 领域 |
|---|---|---|
| **FinanceBench** | 150 Q | 10-K/10-Q/8-K/earnings |
| **FinQA / TAT-QA / DocFinQA** | — | 金融文表 / 长文档 |
| **LegalBench-RAG**（arXiv:2408.10343） | **6858 Q-A，79M 字符** | NDA / M&A / 商业合同 / 隐私政策，**法律专家人工标注** |
| **LegalBench-RAG-mini** | 精简版 | 快速迭代 |
| **WixQA**（arXiv:2505.08643） | — | **企业客服场景**，多数据集 |
| **MedQA / MedRAG / PubMedQA** | — | 生医 |

**借鉴要点**：
- LegalBench-RAG 的关键设计：**强调"最小高相关片段"而非整文档 ID**——直接对应我方 small-to-big 设计（小粒度检索 + 大粒度生成）
- 若我方有垂类（政务/金融/医疗），应先做**领域子集 500 条**，再扩展通用

### 2.8 合成数据生成方法论（评测集构造核心）

| 工具 / 方法 | 要点 |
|---|---|
| **RAGAS evolving** | 单文档 seed → LLM 按推理 / 多上下文 / 条件等维度进化 |
| **Red Hat SDG Hub** | Topic 提取 → 问题生成 → 问题进化 → 答案生成 → groundedness 过滤 |
| **NVIDIA NeMo Curator** | 3 组件：relevance / difficulty / groundedness |
| **HF Cookbook critique agents** | 三维打分：**groundedness / relevance / standalone**，任一低分即剔除 |
| **RAGEval**（ACL 2025） | **Schema-based**：三个新指标 **Completeness / Hallucination / Irrelevance** |
| **Know Your RAG**（arXiv:2411.19710） | 提出问题 taxonomy：fact / summary / reasoning / unanswerable |
| **KGQAGen** | SPARQL 执行可验证，防 LLM 幻觉 |

**借鉴要点（我方可直接抄的 pipeline）**：
```
Doc chunk → LLM 问题生成 → 问题进化（Ragas）
  → Multi-agent critique（groundedness/relevance/standalone）
  → groundedness 过滤（answer 必须来自 chunk）
  → Difficulty 分层（单跳/多跳/摘要/不可答）
  → 人工复核抽样 10%
  → (KG 路) SPARQL 反向执行验证
```

### 2.9 评测工具链

| 工具 | 特点 | 局限 |
|---|---|---|
| **RAGAS** | 4 指标（context precision / recall / faithfulness / answer relevancy）、无需 ground truth、生态成熟 | LLM-judge 噪声大 |
| **TruLens** | RAG Triad、feedback functions、OpenTelemetry | — |
| **Phoenix**（Arize） | 原生 OTEL、交互式 trace、prompt management | 单一依赖 |
| **DeepEval** | pytest 原生集成、CI/CD 友好 | — |
| **Langfuse** | OSS、多租户、cost tracking | — |
| **WandB RAG Eval** | 2026 benchmark 最高 Top-1 **94.5%** | 二元分粗糙 |

**关键警告（2025–2026 最新研究）**：**5 款评测工具（WandB / TruLens / RAGAS / Phoenix / DeepEval）都无法区分"实体对但事实错"的 hard negative vs 正确上下文**——RAG 可以拿 0.95 faithfulness 但给错答案。所以**自动评测只是 sanity check**，**人工评测和对抗样本不能省**。

---

## 3. 针对我方双路系统的重点借鉴清单

### 3.1 必须对齐的 5 个基准

| 借鉴对象 | 对齐点 | 行动 |
|---|---|---|
| **RAGRouter-Bench** | reasoning/factual/summary 三分类 + 路由 F1 | Stage 2 评测集**必须包含**这三类标签 |
| **T²-RAGBench** | 文表混合 + 10 种策略横评 | Stage 3 加入表格/结构化数据 |
| **CRUD-RAG** | CRUD 四任务、中文企业场景 | Stage 2 中文子集借鉴其分类维度 |
| **HotpotQA distractor** | 干扰段设置 | Stage 2 加入"相似但错"的 hard negative |
| **LegalBench-RAG** | 最小高相关片段标注 | Stage 3 若有法律/合规数据集，标注粒度对齐其 span-level |

### 3.2 可借鉴的**生成框架**（非数据集本体）

- **KGQAGen**：利用我方 KG schema 自动生成多跳 QA，**无需人工标注**（是最快的 KG 路评测来源）
- **RAGEval schema-based**：schema 驱动合成，Completeness/Hallucination/Irrelevance 三指标天然贴 KG 场景
- **HF Cookbook critique 三维过滤**：作为所有合成样本的默认守门员

---

## 4. "先松后紧" 四阶段建设路线

### 📍 Stage 1（第 1 周）—— **最小可行评测集（50–200 条）**

**目标**：在 1 周内得到"方案 1 vs 2 vs 3"的方向性结论。

**数据来源**：
- 采样 50 条**真实生产日志 query**（必须，否则评测完全失真）
- 补 50 条内部 domain 典型问题（PM / 运营写）
- 补 50 条**对抗样例**（故意写歧义 / 多跳 / 打错字 / 无答案）

**标注**：
- 每条人工打 3 项：① query_type ∈ {factual, multi_hop, structured, summary, unanswerable}；② gold_answer（短答案 or "需信息源"）；③ gold_chunk_ids（可多个）
- 不要求完美，allow "uncertain" 标签占 10%

**指标（只看 4 项）**：
- **Retrieval Recall@10**（gold chunk 是否进前 10）
- **Answer EM/F1**（短答案匹配）
- **Citation Coverage**（答案引用是否含 gold chunk）
- **P95 延迟** + **单次 token 成本**

**跑三方案**：
- 每方案跑 200 条，出一张四维雷达图
- 特别关注**方案间结论是否一致**（若都输给 vanilla RAG，说明方案都没调好，先回去调单路）

**退出条件**：明确三方案**在哪类 query 上相对最优 / 最劣**。

### 📍 Stage 2（第 2–4 周）—— **合成扩展到 500–1000 条**

**目标**：回归测试、调参能用的稳定评测集。

**合成 pipeline**（照抄 Red Hat SDG Hub + HF critique）：
1. 从入库 chunk 中**分层抽样**（按文档类型、长度、chunk 所在 hierarchy 层）
2. 对每 chunk 用 LLM 生成 3–5 问（提示词要求覆盖 **fact / multi_hop / summary / unanswerable** 四类）
3. Ragas 风格问题进化（加推理 / 多上下文 / 条件）
4. **KG 路专用**：从 schema 随机游走 2–4 跳，生成结构化问题，反向 SPARQL/Cypher 执行验证答案
5. **Critique 三过滤**：groundedness + relevance + standalone（任何 < 3/5 即剔除）
6. 分层平衡（factual : multi_hop : summary : unanswerable ≈ 40:30:20:10）
7. 10% 人工复核

**新增指标**：
- **Routing Accuracy**（方案 1 专用：预测 query_type 是否正确）
- **Fusion Conflict Rate**（方案 2 专用：两路 top-5 的矛盾对数 / 总对数）
- **Decomposition F1**（方案 3 专用：生成的子查询 vs 人工分解的子查询）
- **Faithfulness / Answer Relevancy / Context Precision**（RAGAS 三件套）

**退出条件**：三方案在 500+ 条上分数稳定（跨 3 次运行 std < 5%）。

### 📍 Stage 3（第 2–3 月）—— **3000–5000 条 + 领域扩展**

**目标**：上线前的正式评测集，支持 A/B 实验。

**扩充方向**：
- 加入 **HotpotQA distractor 风格** 的 hard negative：对每个 multi-hop 问题加入 2–4 段"实体对但事实错"的干扰段
- 加入领域子集（若业务涉及）：金融 ~ FinanceBench、法律 ~ LegalBench-RAG、客服 ~ WixQA 风格
- 加入 **中文 CRUD 四任务**（对齐 CRUD-RAG）
- 加入**时序 / 时效**样本（query 带时间条件，测 temporal KG）

**新增对抗样本**：
- **Prompt injection 样本**（测 InputGuard）
- **PII 泄露 trap**（测 OutputGuard）
- **噪声检索**（故意给全错的 context，测 LLM 是否拒答而非 hallucinate）

**新增指标**：
- **Hard Negative Resistance**（在干扰段存在时的 Recall@5 下降幅度）
- **Abstain Rate**（无答案场景的主动拒答率，目标 ≥ 80%）
- **Cost per Correct Answer**（每答对一题的 token × 单价）

**退出条件**：方案选型可基于 ≥ 95% 统计显著性的 A/B 结论。

### 📍 Stage 4（季度级 + 持续）—— **动态 + 对抗常态化**

**目标**：防 LLM 记忆、防静态过拟合、发现 regression。

**动态化**：
- 参照 Dynamic-KGQA / KGQAGen，每季度**自动重新生成** 20% 样本（保留 80% 稳定基准对比历史）
- 接入**生产流量 shadow eval**：每日采样 500 条真实 query，离线重跑历史版本 + 当前版本 diff
- 自动收集"用户点踩"的 session 进隔离区，每周人工复核 → 进对抗子集

**红队 / 对抗**：
- 季度一次 jailbreak 红队（LLM-based 攻击样本生成）
- Hard negative mining：对当前模型的失败样例找"邻居样例"批量生成
- Memory poisoning 测试（对 agentic 方案）

---

## 5. 评测维度矩阵（直接用作 dashboard 列标题）

| 维度 | 指标 | 方案 1 | 方案 2 | 方案 3 |
|---|---|---|---|---|
| **路由/决策** | routing_accuracy | ★ 主指标 | — | decomposition_f1 |
| **检索质量** | recall@k, mrr, ndcg | ✓ | ✓ | ✓ |
| **融合质量** | conflict_rate, net_gain_over_best_single | — | ★ 主指标 | — |
| **答案质量** | answer_em, answer_f1, faithfulness | ✓ | ✓ | ✓ |
| **引用质量** | citation_coverage, citation_precision | ✓ | ✓ | ✓ |
| **拒答能力** | abstain_rate（unanswerable 样本） | ✓ | ✓ | ✓ |
| **抗干扰** | hard_negative_recall_drop | ✓ | ✓ | ✓ |
| **延迟** | p50 / p95 / p99 | ✓ | ✓ | ★ 弱点 |
| **成本** | tokens_in/out per query, cost per correct | ✓ | ✓ | ★ 弱点 |
| **稳定性** | 同一 query 三次跑的 std | ✓ | ✓ | ★ 弱点 |
| **可解释** | 能否输出决策 trace | ✓（路由日志） | ✓（融合权重） | ✓（分解树） |

**铁律**：**每次架构变更，必须同时跑这 11 个指标**；任何一项劣化 > 10% 要在评审会专门答辩。

---

## 6. 三方案的实证设计建议

### 6.1 基于相同评测集的平行对照

**不要改方案之间的 retriever / chunker**。唯一变量是**编排层**：
- 方案 1：`IntentRouter → {VectorRetriever | KGRetriever}`
- 方案 2：`VectorRetriever ∥ KGRetriever → RRF → Rerank`
- 方案 3：`QueryDecomposer → iter({VectorRetriever | KGRetriever} by agent) → Merge`

### 6.2 按 query_type 切片报指标（**不要只看总分**）

| query_type | 预测：最优方案 |
|---|---|
| factual（简单） | 方案 1 分向量路（最快最便宜） |
| multi_hop | 方案 2（两路信息叠加）或方案 3 |
| structured（按 schema 查询） | 方案 1 分 KG 路 |
| summary | 方案 2（覆盖更广） |
| unanswerable | 方案 2（投票拒答更稳） |

**验证思路**：若切片报告与预测一致，说明三方案可**按 query_type 组合使用**（混合架构）；若不一致，则评测集或方案实现有问题。

### 6.3 建议最终架构（根据业界经验预判）

**大概率最优**：**Hybrid = 方案 1 + 方案 2 的分层组合**
- 第一层：轻量路由（TF-IDF+SVM，参考 RAGRouter-Bench baseline 93% 准确率）分 factual / complex
- factual → 向量路 + small-to-big 单路（省时省钱）
- complex → 向量 + KG 双路 + RRF + rerank（方案 2 模式）
- **只在必要时（unanswerable / 极复杂）升级到方案 3 agentic**（成本可接受的尾部场景）

**这个结构等效于 Adaptive-RAG（NAACL 2024）+ RAGRouter-Bench 的工程落地**。

---

## 7. 建设执行路线图（6 周）

### Week 1 —— Stage 1
- D1–D2：从生产日志采样 50 条 + PM 补 100 条 + 对抗 50 条
- D3–D4：三人并行人工标注（query_type / gold_answer / gold_chunk_ids），每天晨会对齐标注分歧
- D5：写 `evaluation/stage1_runner.py`，跑三方案，出报告

### Week 2 —— Stage 2 启动
- 搭合成 pipeline：`evaluation/synthetic/{generator,evolver,critic}.py`（对齐 Ragas + HF Cookbook）
- KG 路：`evaluation/synthetic/kg_walker.py` 随机游走 + SPARQL 验证
- 目标：产 500 条种子，10% 人工复核

### Week 3–4 —— Stage 2 扩充 + 指标补齐
- 扩至 1000 条，平衡分层
- 实现 routing_accuracy / conflict_rate / decomposition_f1 三项方案专属指标
- 搭 Grafana dashboard 展示 11 维雷达

### Week 5 —— 方案 A/B 实验
- 三方案在 Stage 2 评测集上各跑 3 次，Mann-Whitney U 检验
- 写"三方案对比报告"，含切片分析

### Week 6 —— Stage 3 启动
- hard negative 生成（对 Stage 2 失败样本做邻居 mining）
- 领域扩展（确定一个首发领域）
- 接入 shadow eval 每日 diff

---

## 8. 工程实现骨架（我方目录建议）

```
app/rag/evaluation/
├── datasets/                     # 评测集本体（JSONL）
│   ├── stage1_seed.jsonl
│   ├── stage2_synthetic.jsonl
│   ├── stage3_domain/{finance,legal,support}.jsonl
│   └── hard_negatives.jsonl
├── synthetic/                    # 合成 pipeline
│   ├── generator.py              # LLM 问题生成
│   ├── evolver.py                # Ragas 风格进化
│   ├── critic.py                 # 三维 critique 过滤
│   ├── kg_walker.py              # KG 随机游走
│   └── hard_negative_miner.py    # 对抗样本
├── metrics/
│   ├── retrieval.py              # recall/mrr/ndcg
│   ├── answer.py                 # EM/F1/faithfulness
│   ├── routing.py                # routing_accuracy (方案 1)
│   ├── fusion.py                 # conflict_rate (方案 2)
│   ├── decomposition.py          # decomp_f1 (方案 3)
│   ├── abstain.py                # 拒答率
│   └── cost.py                   # token/cost
├── runners/
│   ├── scheme_a_runner.py        # 方案 1 跑法
│   ├── scheme_b_runner.py        # 方案 2
│   ├── scheme_c_runner.py        # 方案 3
│   └── batch_compare.py          # 并行三方案
├── reports/
│   ├── template.py               # Jinja 报告模板
│   └── slicer.py                 # 按 query_type 切片
├── shadow_eval/
│   ├── sampler.py                # 生产流量采样
│   └── diff_runner.py            # 历史 vs 当前 diff
└── redteam/
    ├── prompt_injection_suite.py
    └── hallucination_trap.py
```

---

## 9. 常见陷阱与规避（踩坑清单）

1. **用 GPT-4o 同时做 generator + judge** → 自评偏差，必须用两个不同模型
2. **所有 query 都同一长度** → 短 query 不被测
3. **只评 top-1 答案** → multi-hop 场景应测答案完整性
4. **Ground truth 来源单一人** → 至少 2 标注 + Cohen κ ≥ 0.7
5. **评测集和训练 / few-shot 样本混用** → 数据泄露
6. **只关注平均分** → 必须按 query_type 切片，否则掩盖结构性失败
7. **上线后不再维护评测集** → Stage 4 的动态化不是可选项
8. **合成样本占 > 80%** → 必然高估，真实流量 ≥ 30% 是底线
9. **指标互锁不管**（比如 faithfulness 上涨但 recall 下降） → 必须看多维联动，不能 cherry-pick
10. **忘记成本维度** → token × QPS × 单价 = 真账单，方案 3 agentic 容易撑爆预算

---

## 10. 关键参考资料清单

### 核心基准（必读）
- [RAGBench (arXiv:2407.11005)](https://arxiv.org/html/2407.11005v1) / [HF 数据集](https://huggingface.co/datasets/galileo-ai/ragbench)
- [CRAG (arXiv:2406.04744)](https://arxiv.org/abs/2406.04744) / [GitHub](https://github.com/facebookresearch/CRAG/)
- [MultiHop-RAG (arXiv:2401.15391)](https://arxiv.org/abs/2401.15391) / [GitHub](https://github.com/yixuantt/MultiHop-RAG/)
- [BenchmarkQED (MSR 2025)](https://www.microsoft.com/en-us/research/blog/benchmarkqed-automated-benchmarking-of-rag-systems/)

### 路由相关（**最切题**）
- [RAGRouter-Bench (arXiv:2602.00296)](https://arxiv.org/html/2602.00296v2)
- [Lightweight Query Routing (arXiv:2604.03455)](https://arxiv.org/abs/2604.03455)
- [REIC KDD 2025 (arXiv:2506.00210)](https://arxiv.org/pdf/2506.00210)
- Adaptive-RAG (Jeong, NAACL 2024)
- MBA-RAG (COLING 2025)

### 多跳与 KGQA
- [Diagnosing KG-RAG Datasets (OpenReview)](https://openreview.net/pdf?id=Vd5JXiX073) ——KGQAGen-10k 所在
- WebQSP / CWQ / GrailQA（Freebase 系）
- [GraphWalker (arXiv:2603.28533)](https://arxiv.org/html/2603.28533)
- [Fine-Grained Difficulty Matrix EMNLP 2025 Findings](https://aclanthology.org/2025.findings-emnlp.236.pdf)
- [BRIDGE (arXiv:2603.07931)](https://arxiv.org/html/2603.07931)

### 混合检索
- [T²-RAGBench (arXiv:2506.12071)](https://arxiv.org/html/2506.12071v1)
- [From BM25 to Corrective RAG (arXiv:2604.01733)](https://arxiv.org/html/2604.01733)
- [Towards Practical GraphRAG (arXiv:2507.03226)](https://arxiv.org/html/2507.03226v3)

### 中文
- [CRUD-RAG (arXiv:2401.17043)](https://arxiv.org/abs/2401.17043) / [GitHub](https://github.com/IAAR-Shanghai/CRUD_RAG) / [ACM TOIS 2025](https://dl.acm.org/doi/10.1145/3701228)
- [Chinese-RC-Datasets](https://github.com/ymcui/Chinese-RC-Datasets)

### 领域
- FinanceBench / FinQA / TAT-QA / DocFinQA
- [LegalBench-RAG (arXiv:2408.10343)](https://arxiv.org/pdf/2408.10343)
- [WixQA (arXiv:2505.08643)](https://arxiv.org/abs/2505.08643)
- [FinSage (arXiv:2504.14493)](https://arxiv.org/pdf/2504.14493)

### 合成方法论
- [RAGEval ACL 2025](https://aclanthology.org/2025.acl-long.418.pdf)
- [Know Your RAG (arXiv:2411.19710)](https://arxiv.org/html/2411.19710v1)
- [Can we Evaluate RAGs with Synthetic Data (arXiv:2508.11758)](https://arxiv.org/html/2508.11758) ——**重要警告：合成基准低估任务难度**
- [HF Cookbook RAG Evaluation](https://huggingface.co/learn/cookbook/en/rag_evaluation) ——三维 critique agent 实现范本
- [NVIDIA NeMo Curator SDG blog](https://developer.nvidia.com/blog/evaluating-and-enhancing-rag-pipeline-performance-using-synthetic-data/)
- [Red Hat SDG Hub](https://developers.redhat.com/articles/2026/02/23/synthetic-data-rag-evaluation-why-your-rag-system-needs-better-testing)
- [AWS Bedrock Synthetic RAG](https://aws.amazon.com/blogs/machine-learning/generate-synthetic-data-for-evaluating-rag-systems-using-amazon-bedrock/)

### 评测工具
- RAGAS (arXiv:2309.15217)
- TruLens / Arize Phoenix / DeepEval / Langfuse / WandB / Portkey
- [RAG Eval Frameworks 2026 Compare (atlan)](https://atlan.com/know/llm-evaluation-frameworks-compared/)

### 综合教程
- [Qdrant RAG Eval Guide](https://qdrant.tech/blog/rag-evaluation-guide/)
- [Label Your Data 2026 Metrics](https://labelyourdata.com/articles/llm-fine-tuning/rag-evaluation)

---

## 11. 结论与行动

### 核心论断
1. **选架构之前先建评测集**。三方案的优劣只有在指标上才能说清，否则永远是各说各话。
2. **"意图不准 / 冲突 / 分解错"这三个观察都是评测集能量化的命题**，而不是放弃方案的理由。业界基线（TF-IDF+SVM 93% / RRF / Decomposition F1）都说明这些问题**有工程解**，前提是有评测集去优化。
3. **最终最优大概率是混合架构**（轻量 router + 双路并行 + agentic 兜底），和 Adaptive-RAG / RAGRouter-Bench 的路线一致——这恰好是评测集会把我们推向的结论。

### 下一步（排序的 action）
1. **本周内**：拉通产品 / 算法 / 前台客服，采 50 条真实 query + 100 条 PM 代表性问题，开动 Stage 1
2. **D+5**：Stage 1 报告出炉，三方案粗略排序
3. **W+2**：合成 pipeline 上线，Stage 2 达 500 条
4. **W+4**：11 维 dashboard 上线，方案 A/B 实验启动
5. **W+6–8**：Stage 3 领域扩展 + shadow eval 接入生产流量
6. **季度后**：Stage 4 动态化 + 红队常态化

### 建议组织承诺
**把评测集团队与算法团队平权**（甚至评测集团队投入人头 ≥ 算法团队的 50%）。业界把 RAG 质量做到 top 的团队（Meta CRAG、微软 BenchmarkQED、IAAR CRUD-RAG）都把评测当作一级公民。**没有好的评测集，再好的算法都只是盲飞。**

---

> 后续可独立拆的子 plan：
> - `plans/eval-stage1-seed-200.md`（Stage 1 执行细节）
> - `plans/eval-synthetic-pipeline.md`（Stage 2 合成链路实现）
> - `plans/eval-dashboard-11dim.md`（Grafana dashboard 设计）
> - `plans/eval-kg-walker-from-schema.md`（KG 路评测生成工具）
> - `plans/eval-shadow-daily-diff.md`（生产流量 shadow eval）
