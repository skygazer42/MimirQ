# 上下文扩展与二次重排方法论（2026 Q2）

> **编写日期**：2026-04-18
> **定位**：第 11 份 RAG 专项。解析切块专项（第 6 份）讲"**如何切得更好**"，本文讲"**切已既成，检索端如何补救**"—— 聚焦庖丁科技提出的 **"重排-扩展-重排"三步检索算法**，一种切块无关的纯检索端优化，在 855 问评测集上把召回率从 **42% → 71% → 89%**。
> **核心论断**：不存在适用所有未来提问的完美切块；必须在**检索层**模仿人类"**扫视**"能力——先定位关键片段，再按分数扩展邻近上下文，最后整体重排。
> **交叉引用**：第 6 份解析切块专项（切块端）、第 10 份 IBM 冠军方案（小块检索 + 大块喂食）、第 8 份 POC 归因专项（差评三分类的"检索不到 24%"直接对应）、第 4 份评测集专项（855 问 / 11.3 相关段落 的数据集设计）。

---

## 1. Context：RAG 切块的不可解矛盾

### 1.1 切块是**工程妥协**，不是**设计选择**

- 模型输入长度有限 → 必须切
- 切得越小 → 语义匹配越精确，但**上下文完整性越差**
- 切得越大 → 上下文完整但召回精度差、检索模型处理不了
- **没有最优 chunk size**；且"最优"**取决于用户怎么问**（事前不可知）

### 1.2 切块失效三分类法（**极具穿透力的分析框架**）

| 失效类型 | 表现 | 典型案例 |
|---|---|---|
| **语义缺失** | 关键词被切到另一块，上下文独立后失去锚点 | 《民法典》第 123 条定义与条目被切开 |
| **语义歧义** | 同一词在文档不同位置指代不同实体 | 《募集说明书》"公司"在 179 页 / 522 页分别指不同主体 |
| **结构信息丢失** | 切块破坏了文档结构（标题 / 章节 / 作者归属） | 《小学生作文集》同一作文被切成 4 块，无标题锚 |

这三种失效**切块端无法根治**：再细分 / 再加规则也总会有边界问题。

### 1.3 案例 1：《民法典》第 123 条（语义缺失）

**切块现象**：
- 块 1：含"知识产权"标题 + 前 4 项
- 块 2：后 4 项 + 无标题锚

**问题**："根据知识产权定义，哪些对象可享有专有权利？"
- 块 1 被命中（因为有"知识产权"关键词）
- 块 2 相似度低被过滤（缺少锚词）
- **LLM 只答出前 4 项，后 4 项遗漏**

### 1.4 案例 2：《募集说明书》"公司"歧义

**切块现象**：
- 179 页：公司董事会由 9 人组成
- 522 页：公司董事局由 14 人组成
- 132 页："共同债务人一：华发集团"
- 499 页："共同债务人二：华发股份"

**问题**："华发股份董事会有多少位董事？"
- 仅看 179 / 522 两段无法区分
- **理想切块**：132–179 页（48 页）一块，499–522 页（24 页）一块
- **但这超出检索模型处理长度**

**结论**：切块粒度不可调和——粗了超限，细了歧义。

### 1.5 案例 3：《小学生满分作文集》（结构信息丢失）

**切块现象**：作文"石元达"被切成 4 块
- 只有块 1、2 含作者名
- 块 3、4 因相似度低被过滤

**问题**："石元达的作文全文是什么？"
- 初步检索只召回块 1、2
- **块 3、4 永久丢失**

---

## 2. 三种检索流程量化对比（**核心增量**）

在 50 文档 × **855 问 × 平均 11.3 相关段落 / 问题** 评测集上：

| 模式 | 做法 | 召回率 | 相对计算成本 |
|---|---|---|---|
| **Basic**（no_rerank） | 纯向量初步检索 | **42%** | 1× |
| **Contextual**（上下文重排） | 初步检索 → 整体评估模式重排 | **71%** | ~1.5× |
| **Expanded**（重排-扩展-重排） | 初步检索 → 第一次重排 → 按分扩展 → 第二次重排 | **89%** | ~3.5× |

**关键洞察**：
- Basic → Contextual：**+29pp**（上下文重排的红利）
- Contextual → Expanded：**+18pp**（扩展机制的增量红利）
- Expanded 成本 3.5×，但对**完整性要求高的长文档场景**是划算的

---

## 3. 六种重排 baseline 详解（对标业界）

| Baseline | 重排范式 | 代表 | 输入形式 |
|---|---|---|---|
| **no_rerank** | 无 | 向量直接返回 | 相似度 TopK |
| **bge_rerank** | **逐个评估** | BGE-M3 reranker | 每次输入 1 个 (query, chunk) pair |
| **jina_rerank** | **整体评估** | Jina Reranker v3 | 多 chunk 拼接成 60k tokens → 1 次输入 |
| **context_rerank** | **整体评估**（庖丁长上下文 reranker） | 庖丁自研 | 同 jina，实现细节不同 |
| **extend_rerank** | **扩展后整体评估** | 庖丁方案②（次优） | 向量分数扩展 → reranker 整体输入 |
| **rerank_extend_rerank** | **两阶段扩展**（SOTA） | 庖丁方案③（最优） | reranker 评分 → 扩展 → 再 reranker |

### 3.1 逐个评估 vs 整体评估（关键范式差异）

**逐个评估**：
```
for chunk in candidates:
    score[chunk] = reranker(query, chunk)   # 独立打分
```
- 问题：**无法感知 chunk 间语义关联**
- 切块后的"块 2 是块 1 的延续"这种信号**完全丢失**

**整体评估**：
```
context = concat_dedup_sort(candidates)     # 60k tokens
scores  = reranker(query, context)          # 一次输入联合评估
```
- **reranker 在整体语境中打分**，能感知"块 2 是块 1 延续"
- Jina Reranker v3 和庖丁 reranker 是此范式代表
- **前提**：需要 reranker 原生支持长上下文（60k+）

### 3.2 与 Listwise LLM Rerank（RankGPT）的区别

| 维度 | 整体评估 Reranker | Listwise LLM Rerank (RankGPT) |
|---|---|---|
| 模型 | 专用 reranker 小模型（~1B） | 通用大 LLM |
| 输入 | 拼接的长文本 + query | 多候选排序指令 |
| 输出 | 每块分数 | 重排序列 |
| 成本 | 低（小模型） | 高（GPT-4o 级） |
| 延迟 | ~50ms | 秒级 |
| 产业代表 | Jina v3 / 庖丁 | RankGPT / RankZephyr |

**工程结论**：**整体评估 reranker 是目前 Pareto 前沿**——准度逼近 LLM rerank，成本和延迟接近经典 reranker。

---

## 4. 重排-扩展-重排算法深挖（**SOTA 三步法**）

### 4.1 算法伪代码

```python
def expanded_rerank_retrieve(query, top_k_final=20):
    # Step 1: 初步向量检索
    candidates = vector_search(query, top_k=50)  # 例如取 50

    # Step 2: 第一次重排（整体评估模式）
    context_60k = concat_dedup_by_doc_order(candidates)
    first_scores = long_context_reranker(query, context_60k)

    # Step 3: 按分数扩展（核心创新）
    expanded_candidates = set(candidates)
    for chunk in candidates:
        score = first_scores[chunk]
        if score >= high_threshold:        # 如 0.7
            span = large_span              # 如 ±3 块
        elif score >= mid_threshold:       # 如 0.4
            span = mid_span                # 如 ±1 块
        else:
            continue                       # 不扩展
        for neighbor in get_adjacent_chunks(chunk, span):
            expanded_candidates.add(neighbor)

    # Step 4: 第二次重排（整体评估模式）
    new_context = concat_dedup_by_doc_order(expanded_candidates)
    final_scores = long_context_reranker(query, new_context)

    # Step 5: 按最终分截 top_k
    return topk(final_scores, k=top_k_final)
```

### 4.2 三个工程细节

1. **扩展范围与分数挂钩**（非均匀扩展）：分越高扩展越大，**避免噪声扩散**
2. **去重 + 按原文顺序拼接**：重排模型看到的是"尽可能接近原文"的语境
3. **两次 reranker 调用**：成本 2× reranker，但总召回率 +18pp

### 4.3 为什么"先扩展后重排"不够？为什么必须"重排后扩展再重排"？

- **先扩展再重排**（extend_rerank）：
  - 扩展依据是**向量分数**（不够精准）
  - 低质 chunk 可能被扩展 → 引入噪声
- **重排后扩展再重排**（rerank_extend_rerank）：
  - 扩展依据是**第一次重排分数**（整体评估过）
  - **只对真正相关的 chunk 扩展** → 噪声少、增益大

**这是关键区别**：先重排再扩展 = **先精准识别后扩充上下文**，对应人类"找到关键段落再扫视前后文"。

### 4.4 在《作文集》案例中的作用链

1. 初步检索：召回块 1、块 2（含"石元达"）
2. 第一次重排（整体评估）：块 1、块 2 高分
3. **按分扩展**：因块 1、块 2 高分，把块 3、块 4（相邻）一并纳入
4. 第二次重排：块 1–4 联合评估
5. **最终 LLM 看到完整 4 块 → 答案完整**

---

## 5. 我方现状对标

### 5.1 我方已有的"扩展类"检索组件

| 文件 | 行数 | 机制 | 与本方法关系 |
|---|---|---|---|
| `retrieval/hierarchy_expand.py` | 365 | 基于**文档结构树**扩展（父子关系） | 🟡 不同维度（结构 vs 邻近） |
| `retrieval/contextual_followup.py` | 284 | 上下文跟进 | 🟡 或许已做相邻扩展？需确认 |
| `retrieval/evidence_gap.py` | 75 | 证据缺口检测 | 🟢 可触发扩展 |
| `retrieval/decomposition_chain.py` | 52 | 查询分解 | 🔵 互补 |
| `retrieval/colbert_ann.py` | 465 | ColBERT late interaction | 🔵 互补 |
| `retrieval/orchestrator.py` | 5188 | 编排 | 🟢 承接扩展的主位置 |

### 5.2 我方 reranker 栈

9 个 reranker（`app/rag/reranker/`），**但需确认是"逐个评估"还是"整体评估"模式**：
- `cross_encoder.py` → 多为逐个
- `colbert.py` → late interaction
- `llm_based.py` → 可能是逐个或 RankGPT 变体
- `hybrid.py` → 融合
- `ltr.py` → LTR

**Gap**：
- 未见**长上下文 reranker**（Jina Reranker v3 / 庖丁级别的整体评估模式）
- `hierarchy_expand` 走的是树型结构扩展，**没有"按 rerank 分数扩展邻近"**的机制
- 无**两次 reranker 调用的 pipeline**

### 5.3 关键结论

**我方有扩展（hierarchy_expand，结构维度）+ 9 种 reranker，但缺这三项**：

1. **整体评估 reranker**（Jina v3 或等价）
2. **按重排分数的邻近扩展机制**（非结构树扩展）
3. **两次 reranker 的 pipeline**（rerank-expand-rerank）

---

## 6. 建议优化（按优先级）

### 🥇 P0（1–3 周）

| # | 建议 | 预计收益 |
|---|---|---|
| 1 | `reranker/long_context_rerank.py`（接入 Jina Reranker v3 或 BGE-reranker-v2-m3，整体评估模式） | 对齐 Contextual 模式，+29pp 召回 |
| 2 | `retrieval/neighbor_expand.py`（按重排分数的邻近 chunk 扩展，分数阈值驱动） | 与 hierarchy_expand 互补 |
| 3 | `workflows/rerank_expand_rerank.py`（两次重排的编排工作流） | 完整 Expanded 模式，+18pp |
| 4 | 内部 855 问评测集构造（复用解析切块 / 评测集专项的 chunking_grid） | 量化验证 Basic/Contextual/Expanded 三档 |

### 🥈 P1（1–2 月）

| # | 建议 | 理由 |
|---|---|---|
| 5 | `hierarchy_expand` 与 `neighbor_expand` 融合：结构扩展 + 邻近扩展双轨 | 两种扩展维度互补 |
| 6 | Expanded 模式 profile：按 tenant / query_type 启用 | 成本感知（3.5× 成本并非所有场景划算） |
| 7 | 产品化三档 API：`mode ∈ {basic, contextual, expanded}`（对齐 ChatDOC Studio） | 对外暴露可选精度-成本档位 |
| 8 | 评测集合成：加入"**切块失效三类样本**"（语义缺失 / 歧义 / 结构丢失） | 针对性回归测试 |

### 🥉 P2（2–6 月）

| # | 建议 |
|---|---|
| 9 | 自研 / 微调长上下文 reranker（若 Jina v3 不够合身或成本高） |
| 10 | 评估 Lightweight 二次重排（第二次 reranker 可否小模型） |
| 11 | 扩展策略学习（分数阈值 / 扩展范围 per-tenant 自动调） |

### 观望 / 延后

- RankGPT 风格 listwise LLM rerank 作为主路径（成本与延迟不匹配生产）
- 多模态 reranker（图文混合场景）

---

## 7. 案例作为评测集样板（补评测集专项）

本文的三个案例 + 一个评测集规格，**直接可合入评测集专项 §4 Stage 2 合成模板**：

### 7.1 评测集规格参考

- **文档规模**：50 份长文档
- **问题规模**：855 问
- **标注粒度**：平均 11.3 相关段落 / 问题（细粒度 span-level）
- **指标**：召回率 @ 1k / 5k / 10k tokens 上下文截断

### 7.2 三类难题样板（补充评测集 Stage 2 的 8 维难点表）

| 难题类型 | 测试什么 | 模板 |
|---|---|---|
| **切块边界丢锚** | 关键词在块 A、定义在块 B，相似度断 | 《民法典》风格法条列表题 |
| **同指代不同实体** | "公司" / "他" 等在不同章节指代不同实体 | 《募集说明书》风格多主体混合题 |
| **多块聚合题** | 答案需多个邻近块拼接 | 《作文集》风格"全文是什么"题 |

**这三类用来测试"**检索完整性**"—— 与评测集专项 §3 的"**检索不到**"类（24% 差评根因）直接关联。

---

## 8. 与 10 份 plan 的交叉引用

| 本文章节 | 相关 plan |
|---|---|
| §1 切块失效三分类 | 解析切块专项 §7 Vectara 实证（切块端无法根治） |
| §2 42% / 71% / 89% | 综合报告 §7 重排层（补上整体评估 reranker） |
| §3 逐个 vs 整体评估 | 深度调研 §9 / IBM 冠军方案 §2.5（LLM rerank 加权） |
| §4 重排-扩展-重排 | Agentic 专项 §5 A-RAG hierarchical tools（互补） |
| §5 hierarchy_expand 对比 | 解析切块专项 §11 Small-to-Big / Parent-Doc |
| §6 P0 neighbor_expand | POC 归因专项 §4 超纲三级验证（低置信补前后文） |
| §7 评测集样板 | 评测集专项 §4 Stage 2 合成 |
| §7.2 三类难题 | 评测集专项 §3 差评三分类（检索不到类） |

---

## 9. 关键量化数字（可直接写入项目 PRD）

| 指标 | 数字 | 来源 |
|---|---|---|
| 评测集规模 | 50 文档 / 855 问 / 平均 11.3 相关段落 | 庖丁科技 |
| Basic（纯向量）召回 | **42%** | 同上 |
| Contextual（整体评估重排）召回 | **71%**（+29pp） | 同上 |
| Expanded（重排-扩展-重排）召回 | **89%**（+18pp） | 同上 |
| Expanded 相对成本 | **~3.5×** Basic | 同上 |
| 整体评估 reranker 长度 | 60k tokens | Jina v3 / 庖丁 |

---

## 10. 产品化参考（ChatDOC Studio）

- 网站：https://chatdoc.studio/
- **三档暴露**：Basic / Contextual / Expanded
- **工程启示**：向终端用户暴露"精度-成本"档位，让客户按场景选。我方也可在 API 加 `retrieval_mode` 参数或 `retrieval_profile` 配置（呼应综合报告 §6 retrieval profiles）。

---

## 11. 参考资料

### 技术栈
- [Jina Reranker v3](https://jina.ai/reranker/) —— 长上下文整体评估 reranker
- [BGE Reranker v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- [ChatDOC Studio（庖丁科技）](https://chatdoc.studio/)
- [BGE-M3 Embedding](https://huggingface.co/BAAI/bge-m3)

### 本项目相关 plan
- `plans/rag-capability-gap-2026-q2.md` §7 重排层
- `plans/rag-deep-research-2026-q2.md` §9 重排层
- `plans/rag-eval-dataset-deep-dive-2026-q2.md` §3 差评三分类 + §4 Stage 2 合成
- `plans/rag-parsing-chunking-deep-dive-2026-q2.md` §11 Small-to-Big / Parent-Doc（切块端视角）
- `plans/rag-poc-attribution-framework-2026-q2.md` §4 超纲三级验证
- `plans/rag-ibm-champion-blueprint-2026-q2.md` §2.3 小块检索 + 大块喂食（类似思路不同实现）
- `plans/rag-agentic-reasoning-deep-dive-2026-q2.md` §5 A-RAG hierarchical tools

---

## 12. 结论

1. **切块端无法根治碎片化**——必须在检索端补救
2. **整体评估 reranker 是 Pareto 前沿**（Jina v3 / 庖丁 reranker），准度逼近 LLM rerank、成本逼近经典 cross-encoder
3. **"重排-扩展-重排" 三步算法** 让 RAG 模仿人类"扫视"能力：先定位关键段落，再按分数扩展邻近，最后整体评估；召回率 42% → 89%，成本仅 3.5×
4. **我方最紧迫的 P0 三项**：
   - `long_context_rerank.py`（接入 Jina Reranker v3）
   - `neighbor_expand.py`（按重排分数的邻近扩展）
   - `rerank_expand_rerank.py`（两阶段编排）
5. **评测集补齐**：本文三大案例（语义缺失 / 歧义 / 结构丢失）可直接作合成模板，配合评测集专项的 855 问规模基准，让我方量化自证 Basic/Contextual/Expanded 三档差距
6. **产品化启示**：三档模式对外暴露（Basic / Contextual / Expanded），呼应成本-精度权衡需求

**落地建议**：
- **本周**：确认 `contextual_followup.py` 是否已做邻近扩展，若是则升级、若否则新建
- **2 周内**：接入 Jina Reranker v3 作为整体评估 baseline；构造内部 100 问小规模评测集验证 Basic / Contextual 两档
- **1 月内**：Expanded 模式完整 pipeline 上线；扩展到 500 问评测集

---

> **RAG 专项体系至此共 11 份 plan，合计约 6800+ 行**：
> - 第 1–4 份：综合对标 + 深度调研 + 评测集 + KG
> - 第 5–7 份：Agentic / 解析切块 / 安全合规
> - 第 8 份：POC 归因框架（运营手册）
> - 第 9 份：Pre-POC Scanner（入库前预检）
> - 第 10 份：IBM 冠军方案工程蓝图
> - 第 11 份：**上下文扩展与二次重排（本文）**
>
> 覆盖：**理论对标 + 量化 benchmark + 方法论 + 工程范式 + 运营手册 + 检索端算法创新** 全链路。

---

## 13. 可独立拆的子 plan

- `plans/long-context-rerank-jina-v3.md`
- `plans/neighbor-expand-by-score.md`
- `plans/rerank-expand-rerank-workflow.md`
- `plans/internal-855-question-benchmark.md`
- `plans/retrieval-mode-three-tier-api.md`（API 层面 Basic/Contextual/Expanded 三档）

---

## 14. 2026-05-01 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口.

已落地:
- 核心工作流已落地:`app/rag/workflows/rerank_expand_rerank.py` 串起初检、扩展和二次 rerank.
- 上下文扩展已产品化为可控策略:`app/rag/retrieval/neighbor_expand.py`,`app/rag/retrieval/sibling_expand.py`,`app/rag/retrieval/contextual_followup.py`,`app/rag/chunking/contextual_enrichment.py`.
- 配套测试覆盖主要边界:`tests/test_rerank_expand_rerank_workflow.py`,`tests/test_neighbor_expand.py`,`tests/test_sibling_expand.py`,`tests/test_retriever_sibling_expand_route.py`,`tests/test_contextual_followup.py`,`tests/test_contextual_enrichment.py`.
- 前端检索配置与诊断页面已能显式查看/调整相关策略,不再需要用户手写后端 ID 或 JSON 才能验证.

暂缓:
- 不做所有 query 默认扩大上下文,避免成本、延迟和噪声同时上升.
- 不做独立 855 问公开榜单化,现阶段以内部回归集和用户 bad case 驱动即可.

Directive: 后续扩展策略必须通过 retrieval profile 或实验开关进入,不得改成全局默认强扩展.
