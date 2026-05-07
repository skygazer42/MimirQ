# RAG PageIndex 深度调研 (2026-Q2)

> 评估 VectifyAI/PageIndex（28.9k stars，FinanceBench 98.7% accuracy）的 *vectorless + 不切块 + LLM 树搜索* 架构对 MimirQ 的借鉴价值；产出 4 落点接入路径 + 与 6 份既有 plan 的边界划分 + FinanceBench 评测复现方案。
>
> 创建日期：2026-05-07
> 作者：MimirQ RAG 调研
> 状态：调研草案，等待评测对标后决策是否落 P0
>
> **核心结论**：tree search 不替代任何已有方案，而是 *第三条独立路径*（vector hybrid / KG agentic / TOC tree），通过 router 共存。建议先建评测集再决定是否实现，预期适用边界 = 强结构长文档（财报/招股书/法规/教科书/技术手册）。

---

## 0 阅读路径

| 章节 | 用途 | 读者 |
|---|---|---|
| 第 1 章 | PageIndex 算法解构 + 上游源码摸排 | 工程实现者 |
| 第 2 章 | MimirQ 4 落点接入路径 + 复用资产清单 | 工程实现者 |
| 第 3 章 | **与 6 份既有 plan 划清边界**（核心） | 架构决策 / 避免双造 |
| 第 4 章 | FinanceBench 评测对标 + 决策门槛 | PM / 评测团队 |
| 第 5 章 | 风险 / 里程碑 / 范围之外 | PM / 时间表 |

---

## 1 PageIndex 算法解构

### 1.1 项目元数据

| 字段 | 值 |
|---|---|
| 仓库 | `VectifyAI/PageIndex` |
| Stars / Forks | 28,923 / 2,455 |
| 协议 | MIT |
| 主语言 | Python |
| 创建 | 2025-04-01 |
| 最近更新 | 2026-05-05 |
| 商业方 | Vectify AI |
| Topics | agentic-ai, agents, ai, ai-agents, context-engineering, llm, rag, reasoning, retrieval, retrieval-augmented-generation, vector-database |
| Homepage | pageindex.ai（含 Chat / MCP / API / Dashboard） |
| 杀手级 benchmark | FinanceBench 98.7% accuracy（Mafin 2.5 系统，arxiv 2311.11944） |

### 1.2 核心论点

> **"similarity ≠ relevance"** — 向量检索是相似度匹配，专业文档需要的是相关性匹配，相关性需要 *推理*。

灵感来自 AlphaGo —— 用 LLM 像人类专家一样在文档目录树上做 tree search。

### 1.3 两步算法

#### 步骤 ①：TOC 树构建（offline，per-document）

主入口 `run_pageindex.py`，关键参数：

| 参数 | 默认 | 含义 |
|---|---|---|
| `--model` | `gpt-4o-2024-11-20` | LLM 模型（litellm 多 provider） |
| `--toc-check-pages` | 20 | 前 N 页找 TOC |
| `--max-pages-per-node` | 10 | 单节点跨页上限 |
| `--max-tokens-per-node` | 20000 | 单节点 token 上限 |
| `--if-add-node-id` | yes | 节点编号 |
| `--if-add-node-summary` | yes | LLM 生成节点摘要 |
| `--if-add-doc-description` | yes | LLM 生成文档级描述 |
| `--md_path` | — | Markdown 模式（按 `#` 级别推树） |

核心模块（`pageindex/`）：
- `page_index.py`（主算法 + 多个 LLM check）
- `page_index_md.py`（Markdown 专用）
- `retrieve.py`（3 个 tool function）
- `client.py`（LLM 抽象）
- `utils.py`（PDF / JSON 工具）
- `config.yaml`（默认配置）

关键 LLM 步骤（来自源码 `page_index.py`）：
1. **TOC 检测** `toc_detector_single_page(content, model)` — 单页判 "是否含目录"
2. **标题出现校验** `check_title_appearance(item, page_list)` — 检查 TOC 提取的 title 是否真在指定页出现（fuzzy matching）
3. **标题起始校验** `check_title_appearance_in_start(title, page_text)` — 进一步判 section 是否就在该页开头（避免错位）
4. **节点摘要生成** — 为每节点调 LLM 生成 `summary` 字段
5. **并发执行** — `asyncio.gather` + `ThreadPoolExecutor` 并行多 LLM 调用

输出节点 JSON schema：

```jsonc
{
  "title": "Financial Stability",
  "node_id": "0006",
  "start_index": 21,        // PDF: physical page; MD: line number
  "end_index": 22,
  "summary": "The Federal Reserve ...",
  "nodes": [
    { "title": "Monitoring Financial Vulnerabilities",
      "node_id": "0007", "start_index": 22, "end_index": 28,
      "summary": "..." }
  ]
}
```

#### 步骤 ②：LLM tree search 检索（online，per-query）

**关键设计**：检索本身**不是算法**，而是 3 个 tool function 暴露给外部 LLM agent（OpenAI Agents SDK / MCP），让 agent 自己 reasoning 选哪些页：

源码 `pageindex/retrieve.py`（仅 137 行）暴露：
1. `get_document(doc_id)` — 返回文档 metadata（doc_name / doc_description / page_count）
2. `get_document_structure(doc_id)` — 返回 tree JSON（**剥掉 text 字段省 token**）
3. `get_page_content(doc_id, pages)` — 按页号字符串（如 `"5-7"` / `"3,8"` / `"12"`）拉原文

调用模式（`examples/agentic_vectorless_rag_demo.py`）：
```
Agent loop:
  step 1: get_document_structure(doc_id) → 看树
  step 2: LLM 推理 "我要看哪些 section"
  step 3: get_page_content(doc_id, pages="22-28")
  step 4: LLM 基于内容回答；不够再回 step 2
```

### 1.4 Markdown 模式 vs PDF 模式

| 维度 | PDF | Markdown |
|---|---|---|
| 主算法 | `page_index.py` | `page_index_md.py` |
| 解析 | `PyPDF2` 标准抽取 | 按 `#` 级别推树（`##` = level 2…） |
| `start_index` | physical page (1-indexed) | line number |
| 检索单元 | page | line range |
| 推荐输入 | 原 PDF | 必须 hierarchy 完整的 MD（不推荐用 PDF→MD 转换工具，因为大多丢层级，需用其家 OCR 才行） |

### 1.5 Agentic Vectorless RAG demo

`examples/agentic_vectorless_rag_demo.py` 用 **OpenAI Agents SDK** 把上述 3 tools 注册成 function tool，agent 自己选 doc → 看树 → 选页 → 回答。这是他们最新的 hero demo。

### 1.6 PageIndex File System（最近更新）

把 tree 从单文档扩到全 corpus：增加 *文件级* tree 层，agent 先选文件再进入文档。详见 `pageindex.ai/blog/pageindex-filesystem`。

### 1.7 三种部署模式

| 模式 | 解析质量 | 维护成本 |
|---|---|---|
| Self-host（开源版） | 标准 PyPDF2，TOC 弱信号 PDF 易错 | 完全自主 |
| Cloud / API / MCP | 自家 OCR + tree builder + retrieval pipeline | 按调用付费，外部 LLM |
| Enterprise（私有部署） | 同 Cloud | 商务谈判 |

**商业模式警示**：开源版核心是引流，真正壁垒在 Cloud OCR + tree builder。MimirQ 的 deepdoc / parsing 栈反而是优势，**不需要买 PageIndex API**。

---

## 2 MimirQ 4 个落点接入路径

PageIndex 不是模块化产品，要借鉴必须**拆解算法重新落地到 MimirQ 现有架构**。设计 4 个落点：

### 2.1 落点 A — 新切块策略 `app/rag/chunking/strategies/toc_tree.py`

**目标**：在生成普通 chunks 之外，额外产出 *per-document tree manifest*。

**关键设计**：
- 实现 `BaseChunker` 契约（`app/rag/chunking/base.py`），向后兼容现有 70+ 切块策略调用方式
- 输出双产物：
  - **chunks**（默认）：仍按 chunk 切，保证现有 vector / BM25 / ColBERT 索引不中断
  - **tree manifest**（新）：独立 JSON，schema 对齐 PageIndex 节点结构（`title / node_id / start_index / end_index / summary / nodes[]`）
- tree manifest 存储路径：建议复用现有 chunk metadata schema 加 `tree_manifest_id` 引用，manifest JSON 落 MinIO（参照 `rag-kg-snapshot-deep-dive-2026-q2.md` 的 blake3 + MinIO blob 思路）

**复用资产**（避免重写）：

| 已有 utility | 文件路径 | 复用点 |
|---|---|---|
| Markdown heading 解析 | `app/rag/chunking/utils/heading_parsing.py` (`parse_markdown_hash_heading`) | TOC 树构建 step 1 直接复用，**不需要 LLM** 即可处理 MD（PageIndex MD 模式同此） |
| 中文标题前缀解析 | `app/rag/chunking/utils/heading_parsing.py` (`parse_cn_prefixed_heading`) | "第 1 章 / 一、 / （一）" 等中文格式，PageIndex 上游不支持 |
| 层级切块工具 | `app/rag/chunking/utils/hierarchical.py` (`hierarchical_chunk_markdown`) | 现有的"online 树"基建可作为 tree manifest 的底层数据来源 |
| BaseChunker 契约 | `app/rag/chunking/base.py` | 实现 `split_documents` 不动 |
| 已有 11 个 hierarchy 切块 | `markdown_hierarchy.py` (194)、`markdown_outline.py` (198)、`outline.py` (323)、`book_structured.py` (299)、`text_hierarchy.py` (140) 等 | 这些已经能产出 hierarchy metadata，`toc_tree.py` 是这些的 *manifest 版本*（不是替代） |
| Deepdoc heading detection | `app/parsing/parsers/` 下 deepdoc 系列 | PDF 模式下复用 deepdoc 的 heading 识别，**优于 PageIndex 上游的 PyPDF2** |

**新增内容**：
- LLM-based TOC 检测（仅当 deepdoc heading 信号弱时启用）—— 移植 `toc_detector_single_page` 思路
- 节点摘要生成（可选，受 `--if-add-node-summary` 风格的 config 控制）
- 注册到 `app/rag/chunking/factory.py`（已有 70+ 策略注册模式，加一行）

**衔接现有调用链**：
- 切块入口仍走 `chunker_factory.get_chunker("toc_tree", **kwargs)`
- chunks 流入现有 vector / BM25 / ColBERT 索引（不变）
- tree manifest JSON 异步落 MinIO，URL 写回 chunk metadata

### 2.2 落点 B — 新 workflow `app/rag/workflows/tree_search.py`

**目标**：实现"LLM 在 tree manifest 上 reasoning-based 导航"作为 workflow，与 `crag_streaming` / `flare` / `self_rag` / `self_route` 同级。

**关键洞察**：PageIndex `retrieve.py` 只是 3 个 tool function 暴露给外部 agent —— 真正的 *推理* 在外部 LLM agent。所以 tree_search workflow 的本质是：
> **"提供 3 个 tool 给 LLM，让 LLM 自循环调用直至找到 section"**

**3 个 tool function 映射**（从 PageIndex `retrieve.py` 137 行平移）：
1. `get_document(doc_id)` → MimirQ：从 dataset 元数据查询
2. `get_document_structure(doc_id)` → MimirQ：从 MinIO 读 tree manifest，剥掉 `text`/`summary` 详情字段省 token（PageIndex 上游 `remove_fields` 同样思路）
3. `get_page_content(doc_id, pages)` → MimirQ：按 chunk metadata 的 `start_index` / `end_index` 反查 chunks

**复用资产**：

| 已有资产 | 文件路径 | 复用点 |
|---|---|---|
| Workflow 契约 | `app/rag/workflows/base.py:BaseWorkflow` | 实现 `run` / `astream` 不动 |
| 节点序列化思路 | `app/rag/kg/search/path_verbalizer.py` | KG 路径序列化的格式化思路可借鉴到 tree node verbalize |
| Critic 模式参考 | `app/rag/workflows/self_rag.py` | Self-RAG 的 "retrieve → critique → re-retrieve" 循环可作为 tree_search 自循环模板 |
| 现有 routing | `app/rag/workflows/routing.py` | 学习现有 routing workflow 的工厂注册风格 |

**新增内容**：
- LLM agent 自循环逻辑（模仿 PageIndex `agentic_vectorless_rag_demo.py`）
- 限制最大循环步数（防 token 爆炸），默认 5
- 终止条件：LLM 返回 "answer found" 或步数耗尽
- 流式输出（与 `crag_streaming` 对齐）
- 注册到 `app/rag/workflows/factory.py`

**衔接现有调用链**：
- 与现有 12 个 workflow 同级注册
- Adaptive-RAG router（落点 D）可路由到此 workflow

### 2.3 落点 C — 扩 `app/rag/retrieval/orchestrator.py`

**目标**：retrieval orchestrator 增加 *vectorless* 分支，按 dataset / query 配置选 hybrid retrieval 还是 tree search。

**关键设计**：
- 不动现有 `HybridRetriever` 主路径（5940 行），仅新增分支
- 新增 retrieval mode：`vectorless` / `tree_search`（与现有 `auto` / `hybrid` / `vector` / `keyword` / `mmr` 同级）
- 当 mode = `tree_search` 时：调用落点 B 的 workflow，返回 section-level 结果（可能数百~数千 token）

**复用资产**：

| 已有资产 | 文件路径 | 复用点 |
|---|---|---|
| Orchestrator 主类 | `app/rag/retrieval/orchestrator.py` (5188 行) | 新增 mode 分支，不动主路径 |
| Retrieval 契约 | `app/rag/retrieval/contract.py` | 复用统一返回结构（chunks / scores / metadata），section 作为"超大 chunk"返回 |
| Hierarchy 扩展工具 | `app/rag/retrieval/hierarchy_expand.py` (365)、`neighbor_expand.py`、`sibling_expand.py`、`context_expansion.py`、`contextual_followup.py` | 可作为 tree_search 的 *补充扩展*（先 tree search 定位 section，再用 hierarchy_expand 扩邻近 chunks） |

**新增内容**：
- mode 路由分支（约 50 行）
- section → chunk 的统一返回适配（让上层 chat / RAG 调用方无感知）

### 2.4 落点 D — 扩 `app/rag/workflows/system_router.py` / `self_route.py`

**目标**：Adaptive-RAG router 学会按文档结构信号选择是否走 tree search。

**关键设计**：
- 新增路由信号：
  - **Heading 密度**：每千 token 内 heading 数量 ≥ 阈值
  - **TOC 检测置信度**：deepdoc heading detection 在前 20 页的命中率
  - **文档长度**：单文档 ≥ N 页时倾向 tree search（短文档没必要）
  - **Query 类型**：跨章节 / 全局类型 query 倾向 tree search（"该报告的核心结论是什么"）；点查询倾向 vector hybrid
- Router 不替代 `system_router` / `self_route`，而是**增加一个候选分支**

**复用资产**：

| 已有资产 | 文件路径 | 复用点 |
|---|---|---|
| System Router | `app/rag/workflows/system_router.py` | 加 vectorless / tree_search 候选分支 |
| Self Route | `app/rag/workflows/self_route.py` | 同上 |
| Router 工厂 | `app/rag/workflows/routing.py` | 注册风格参考 |

**新增内容**：
- Router 决策树新增 1 个分支（约 30 行）
- 每路由判断的特征提取函数（heading 密度等，约 80 行）

### 2.5 落点综合工作量预估

| 落点 | 新增代码行数 | 修改既有文件行数 | 测试 | 工期 |
|---|---|---|---|---|
| A：toc_tree.py | ~400 | factory.py +1 | unit + integration | 1 周 |
| B：tree_search.py | ~350 | workflows/factory.py +1 | unit + integration | 1 周 |
| C：orchestrator 分支 | ~80 | orchestrator.py +50 | integration | 0.5 周 |
| D：router 分支 | ~110 | system_router.py +30 / self_route.py +30 | unit + e2e | 0.5 周 |
| **合计 P0** | **~940** | **~110** | — | **3 周** |

---

## 3 与 6 份既有 plan 划清边界（核心章节）

PageIndex 的概念在 MimirQ 已有多份 plan 的"擦边球"区间，必须**逐一对照避免双造**。

### 3.1 边界对照总表

| 既有 plan | 同源点 | 差异 / 边界 | 是否替代 | 共存方式 |
|---|---|---|---|---|
| `rag-kg-deep-research-2026-q2.md`（KG 树搜索） | "在结构上做 LLM 推理导航" | KG = 实体-关系图（节点= entity）；PageIndex = 单文档 TOC 树（节点= section） | **不替代** | router 两条分支 |
| `rag-context-expansion-rerank-2026-q2.md`（chunk 扩展） | "找到锚点→扩展上下文" | chunk 邻近/父子扩展（小颗粒）vs 自顶向下导航到 section（大颗粒） | **不替代** | 正交可叠加 |
| `rag-ibm-champion-blueprint-2026-q2.md`（小块大块） | "返回比检索单元更大的内容" | IBM 仍以 chunk 为索引单元，回页合并是后处理；tree search 从一开始就以 section 为索引和检索单元 | **不替代** | 不同索引哲学 |
| 现有 `markdown_hierarchy.py` / `outline.py` / `book_structured.py` | 都基于 heading 结构 | 现有 = chunks + metadata overlay（"online 树"）；PageIndex = 独立 tree manifest（"offline 树"） | **不替代** | 数据模型补充 |
| `rag-agentic-reasoning-deep-dive-2026-q2.md`（Self-RAG / CRAG / FLARE） | LLM 做检索决策 | 这些 workflow 决策"是否检索 / 何时检索"；tree search 决策"在树上选哪个节点" | **不替代** | 正交可组合 |
| `rag-eval-dataset-deep-dive-2026-q2.md`（router 架构） | router 决策走哪条路 | 该 plan 的 router 在向量检索内分流；tree search = 多一个 router 选项 | **不替代** | 增加 router 分支 |

### 3.2 与 KG agentic search 的详细对照（最易混淆）

`app/rag/kg/search/agentic_beam_search.py` + `plan_on_graph.py` + `drift_search.py` 已实现 KG 上的"agentic 树搜索"。容易让人觉得"已有了 PageIndex 风格"——**但并不是**：

| 维度 | KG agentic search（MimirQ 已有） | PageIndex tree search（拟新增） |
|---|---|---|
| 节点本质 | entity（KG 中的实体节点） | section（文档目录节点） |
| 边本质 | 关系（KG 中的 entity-entity 链接） | 父子结构（目录嵌套） |
| 索引来源 | KG extraction 管线（`app/rag/kg/extraction/`） | 单文档 TOC 提取 |
| 适用场景 | 跨文档实体关联 / 多跳推理 / 因果链 | 单文档定位特定 section / 长文档导航 |
| 输出粒度 | entity + 关系路径 | section 全文 |
| 失败模式 | KG 抽取质量差时全盘失败 | TOC 信号弱（散文）时全盘失败 |
| LLM 调用 | beam search 每步 LLM 评估 | tool 循环每步 LLM 决策 |
| 现有实现 | ✅ 已有（`agentic_beam_search.py` 等） | ❌ 缺失 |

**结论**：两者**不能互替**，应作为 router 的两条独立分支：
- 实体关联型 query（"A 和 B 的关系是什么"）→ KG agentic
- 文档定位型 query（"该报告中 X 章节怎么写的"）→ tree search
- Router 通过 query intent classifier 决策

### 3.3 与 IBM 蓝图 "小块检索大块喂食" 的详细对照

`rag-ibm-champion-blueprint-2026-q2.md` 第 ③ 项 "小块检索大块喂食（300/50 + 回页合并）"——容易让人觉得"已经在做 section-level"。**仍不是**：

| 维度 | IBM 小块大块 | PageIndex tree search |
|---|---|---|
| 索引单元 | 300 token chunk | section（数百~数千 token） |
| 检索方式 | vector + 回页合并 | LLM tool 循环 |
| 大块来源 | chunk → 找到所在页 → 回页 | 直接 section |
| 适用边界 | 通用（向量检索普适） | 强 TOC 文档 |

**结论**：IBM 蓝图是"vector 检索 + 后处理扩展"；PageIndex 是"vectorless + LLM 导航"。两者可叠加：先 tree search 定位 section → section 内再做 IBM 风格的小块匹配（精确定位答案位置）。

### 3.4 共存架构图（router 三分支）

```
                    ┌─ vector hybrid retrieval（现有主路径）
                    │   - HybridRetriever (Vector+BM25+SPLADE+ColBERT)
                    │   - Reranker
                    │   - Hierarchy expand
                    │
   Query → Router ──┼─ KG agentic search（rag-kg-deep-research P0）
                    │   - agentic_beam_search
                    │   - plan_on_graph
                    │   - drift_search
                    │
                    └─ TOC tree search（本 plan 拟新增）
                        - tree_search workflow
                        - get_document_structure / get_page_content tools
                        - per-document TOC manifest
```

Router 决策依据（落点 D 实现）：
- 文档结构信号 → 选 vector / tree
- Query 实体密度 → 选 KG / 其他
- Query 全局性 → 选 tree / vector
- 失败回退 → 默认 vector hybrid

---

## 4 FinanceBench 评测对标

### 4.1 FinanceBench 简介

- **论文**：arxiv 2311.11944 (Patronus AI, 2023-11)
- **数据**：150 条 SEC filings (10-K / 10-Q / 8-K) 跨财年
- **问题**：~10,000 条人工标注 QA，含数值/比较/趋势/解释 4 大类
- **评测**：开源 benchmark + 标注答案
- **领头者**：Mafin 2.5（PageIndex 驱动）98.7%，超过传统 vector RAG 一档

### 4.2 Mafin 2.5 复现协议

参照 `VectifyAI/Mafin2.5-FinanceBench`：
- 评测脚本 + LLM-Judge prompt
- 答案匹配规则（数值 ± tolerance / 字符串 fuzzy match）
- 错误分类（错召回 / 错抽取 / 错推理 / 错格式化）

### 4.3 MimirQ 复现路径

#### 步骤 1：评测集落地

新建目录 `evaluation/poc_runner/pageindex_bench/`：
- 复用 `rag-poc-attribution-framework-2026-q2.md` 的 5 字段埋点（`original_query / llm_response / final_context_filenames / feedback_score / latency_total_ms`）
- 复用 `rag-eval-dataset-deep-dive-2026-q2.md` Stage 1 评测集建设方法论
- 数据来源：FinanceBench 原始数据集 + 中文金融文档补充集（5 篇 A 股年报 + 50 问，对照中文场景）

#### 步骤 2：横向对照三组（同评测集）

| 组别 | 检索方式 | 解析方式 |
|---|---|---|
| **A 现状基线** | MimirQ hybrid retrieval（vector + BM25 + ColBERT + reranker + hierarchy_expand） | MimirQ deepdoc |
| **B PageIndex 原版** | PageIndex tree search（self-host 开源版） | PyPDF2 标准 |
| **C 混合最优** | PageIndex tree search + MimirQ deepdoc | MimirQ deepdoc |

可选第 4 组：
| **D 三路 router** | Adaptive router 在 ABC 间动态选择（落点 D 实现后） | MimirQ deepdoc |

#### 步骤 3：评测 metric

| Metric | 含义 | 工具 |
|---|---|---|
| Accuracy | 答案正确率（参照 Mafin 2.5 协议） | LLM-Judge（`rag-evaluation-deep-dive-2026-q2.md` 的 `llm_judge.py` Stage 1） |
| Per-query LLM cost | 单查询总 token × 单价（$/1M） | 已有 cost tracker |
| Latency p95 | 端到端响应时间（含解析+检索+生成） | OTel span（`rag-visualization-deep-dive-2026-q2.md` 已规划） |
| Explainability score | 人工标注 1-5（trace 是否可追溯到具体 page/section） | 人工标注 |
| 失败模式分布 | 错召回 / 错抽取 / 错推理 4 分类 | 人工标注 + LLM 辅助 |

#### 步骤 4：失败模式预测

PageIndex 大概率失分场景：
- **散文体文档**（无 heading）：TOC 检测失败 → 全盘失败
- **表格密集型**（金融附表）：tree search 找到 section 但表格数据需要单独抽取
- **多 PDF 对比**（A vs B）：tree search 局限在单文档，跨文档需要 router 协调
- **数值计算题**（"A 比 B 增长多少%"）：定位 section 后仍需 LLM 计算
- **小文档**（< 20 页）：tree search 没必要，vector 更快更便宜

### 4.4 决策门槛

| 评测结果 | 决策 |
|---|---|
| 组 C 比组 A accuracy 提升 < 5pt 但 cost 提升 > 3× | **不引入**，记录为已评估 |
| 组 C 比组 A accuracy 提升 > 10pt | **落 P0**，按本 plan 实施 4 落点 |
| 组 C 比组 A accuracy 提升 5~10pt | **作为 router 可选项**（仅 P0 落 toc_tree.py + tree_search.py，跳过 router 智能化） |
| 组 D（router）显著优于 A/B/C | **落 P0 + P2**，全栈实施 |

---

## 5 风险 / 里程碑 / 落地清单

### 5.1 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLM 调用成本爆炸 | 每查询 1-3 次 LLM × tree search 5 步循环 = 5-15 次 LLM | 用 `claude-haiku-4-5` / `gpt-4o-mini` 控本；单查询 token cap |
| 流式响应延迟 | 串行 LLM 调用对 chat 流式不友好 | 作为"深度模式"而非默认；首次出 thinking step 后透出 |
| TOC 信号弱场景兜底 | 散文 / 论坛 / 表格密集型崩盘 | router 检测后自动回退 hybrid（落点 D） |
| 与 KG 路径双造 | 概念上同源，实现易重叠 | 第 3.2 节强约束；router 决策严格分流 |
| 商业模式陷阱 | 误以为开源版 = 完整 PageIndex | 第 1.7 节明确：开源版仅引流，OCR 在 Cloud；MimirQ deepdoc 是优势 |
| 上游协议风险 | MIT 协议但商业公司可能改协议 | 仅借鉴算法，不依赖 PageIndex 包；自实现规避 |
| 评测集 bias | FinanceBench 偏 SEC，中文场景未覆盖 | 补建中文金融评测集（5 篇 + 50 问） |

### 5.2 里程碑

| 阶段 | 时间 | 内容 |
|---|---|---|
| **Pre-P0** | 1 周 | 第 4 章评测集 + 跑 PageIndex 开源版 baseline；用 *评测结果* 决定是否启动 P0 |
| **P0** | 2-3 周 | 落点 A toc_tree.py + 落点 B tree_search.py MVP + tree manifest schema |
| **P1** | 3-4 周 | 落点 C orchestrator vectorless 分支 + 内部 FinanceBench 评测集 + 与 baseline 对照 |
| **P2** | 4-6 周 | 落点 D router 学会路由 + 与 KG agentic 路径横向对比 + UI 透出 thinking trace |
| **P3** | 按需 | PageIndex 官方 MCP 作为兜底 retriever（仅当客户接受外部 LLM） |

### 5.3 落地清单（开工时直接执行）

#### Pre-P0 评测对标（决策门槛）
- [ ] 拉 `VectifyAI/Mafin2.5-FinanceBench` 仓库，跑通官方评测脚本
- [ ] 在 MimirQ 现状跑 FinanceBench 完整 150 文档，得 baseline accuracy / cost / latency
- [ ] PageIndex 开源版 self-host，跑同一评测集，得 PageIndex baseline
- [ ] 输出 4 组对照表（含失败模式分布）→ 触发决策门槛 → 决定 P0 启动与否

#### P0 实施（决策通过后）
- [ ] 实现 `app/rag/chunking/strategies/toc_tree.py`（约 400 行）
- [ ] 注册到 `app/rag/chunking/factory.py`（+1 行）
- [ ] tree manifest schema 定义（JSON Schema + Pydantic model）
- [ ] tree manifest 持久化到 MinIO（参照 KG snapshot 的 blake3 + blob 思路）
- [ ] 实现 `app/rag/workflows/tree_search.py`（约 350 行）
- [ ] 注册到 `app/rag/workflows/factory.py`（+1 行）
- [ ] 单元测试 + integration test
- [ ] 跑 P0 自评：FinanceBench 上 toc_tree + tree_search 单链路效果

#### P1 实施
- [ ] 扩 `app/rag/retrieval/orchestrator.py`（+50 行 + 80 行新分支）
- [ ] section → chunk 的统一返回适配
- [ ] 评测集 `evaluation/poc_runner/pageindex_bench/` 全量化
- [ ] LLM-Judge 评测 + cost / latency 对照
- [ ] UI 接入：在 chat 中显示 "正在浏览目录树..." thinking step

#### P2 实施
- [ ] 扩 `app/rag/workflows/system_router.py` / `self_route.py`（各 +30 行 + 80 行特征提取）
- [ ] router 决策可视化（接入 `rag-visualization-deep-dive-2026-q2.md` 的 trace 时间线）
- [ ] 与 KG agentic 路径横向对比评测

### 5.4 范围之外（明确不做）

- 不写商业 / POC 客户场景画像章节
- 不预先 fork PageIndex 上游
- 不引入 PageIndex 自身依赖（仅借鉴算法，自实现）
- 不评估官方 SaaS / MCP 接入合规问题（留客户合规团队）
- 不在本 plan 内做 Markdown vs PDF 模式的 A/B（合并为一个统一实现）
- 不实现 PageIndex File System（跨文档 file 树）—— P3 评估后决定

---

## 6 附录

### 6.1 PageIndex 上游源码读取清单（实施时参考）

| 文件 | 行数 | 重点 |
|---|---|---|
| `pageindex/page_index.py` | ~600 | TOC 检测 / 标题校验 / 节点摘要 / 并发执行 |
| `pageindex/page_index_md.py` | ~200 | Markdown `#` 级别推树 |
| `pageindex/retrieve.py` | 137 | 3 个 tool function（最小化） |
| `pageindex/client.py` | ~100 | LiteLLM 抽象 |
| `pageindex/utils.py` | ~200 | PDF / JSON 工具 |
| `pageindex/config.yaml` | — | 默认配置 |
| `examples/agentic_vectorless_rag_demo.py` | — | OpenAI Agents SDK 接入 |
| `cookbook/pageindex_RAG_simple.ipynb` | — | 最小 vectorless RAG 例子 |
| `cookbook/vision_RAG_pageindex.ipynb` | — | OCR-free vision RAG |

### 6.2 与 25 份既有 plan 的全量索引（避免双造）

仅本 plan 在 `plans/` 下新增，不修改任何既有 plan。已在第 3 章详细对照 6 份高相关 plan。其余 19 份相关性低，简表：

| 既有 plan | 相关性 | 备注 |
|---|---|---|
| `rag-parsing-chunking-deep-dive-2026-q2.md` | 中 | 切块章节可补 toc_tree 一节，但本 plan 自含足够细节 |
| `rag-evaluation-deep-dive-2026-q2.md` | 中 | LLM-Judge 框架被本 plan 第 4 章复用 |
| `rag-eval-dataset-deep-dive-2026-q2.md` | 中 | Stage 1 评测集建设方法论被复用 |
| `rag-poc-attribution-framework-2026-q2.md` | 中 | 5 字段埋点被复用 |
| `rag-visualization-deep-dive-2026-q2.md` | 低 | UI trace 时间线在 P1/P2 接入 |
| 其余 14 份 | 无 | 无概念重叠 |

### 6.3 关键洞察精选（5 条）

1. **PageIndex 的"算法"其实只有两步且 retrieve.py 仅 137 行** —— 真正壁垒在 TOC 提取的 LLM 提示词工程 + Cloud OCR；自实现完全可行
2. **MimirQ 的 deepdoc 比 PageIndex 上游 PyPDF2 强** —— 在 PDF heading detection 上 MimirQ 占优，只需嫁接 PageIndex 的 tree manifest 数据模型
3. **tree search 不替代任何已有方案** —— 是第三条独立路径（vector / KG / TOC），通过 router 共存
4. **先建评测集再决定是否实现** —— 在 FinanceBench 上量化收益门槛，避免拍脑袋上 P0
5. **商业模式陷阱**：开源版只是引流，PageIndex 真正的产品是 Cloud OCR + Tree Builder API；MimirQ 不需要买，但要警惕"对方升级会拉开开源版与 Cloud 版差距"

---

## 7 最终决策建议（2026-05-07 复盘后追加）

第 1-6 章给出了 *理论上* 的接入路径与评测对标。本节给出 *推荐结论*，覆盖前述章节的部分激进结论。

### 7.1 一句话立场

> **PageIndex 是营销做得很好、技术含量不高的开源项目。算法层面 MimirQ 已经覆盖；接口设计层面有 1 个值得抄；商业故事层面提醒"该建 benchmark 量化能力了"。不建议 P0 全栈，建议 P3 / 评估后落 ≤200 行轻量集成。**

### 7.2 真借鉴 vs 假借鉴

| 维度 | 是否借鉴 | 理由 |
|---|---|---|
| TOC 树作为独立 manifest 数据模型（落点 A） | ❌ 不抄 | MimirQ 的 "chunks + metadata overlay" 同一文档可被多策略切，更灵活；独立 tree 反而是约束 |
| LLM tree search workflow（落点 B） | ⚠️ 概念抄、实现轻量 | KG `agentic_beam_search` 已是同源能力；新加一个 *tree_search-style tool agent* 用现有 hierarchy 数据，约 200 行 |
| Orchestrator vectorless 分支（落点 C） | ❌ 不抄 | "vectorless" 是营销概念；本质是 LLM-augmented retrieval，不需要单独分支 |
| Router 学路由（落点 D） | ⚠️ 部分抄 | 现有 `system_router` / `self_route` 加 1 条 "tool agent 分支" 即可；不需要 4 维特征工程 |
| **3 tool function 接口范式** | ✅ 抄 | retrieve.py 的极简 MCP-style 接口（`get_document` / `get_document_structure` / `get_page_content`）值得在 workflow 层学习 |
| **"先建 benchmark 再堆功能" 纪律性** | ✅ 抄 | Mafin 2.5 的 98.7% 是商业故事核武器；MimirQ 反复指出"最大短板是没量化"，这次去做 |
| FinanceBench 横向对比 | ⚠️ 子集做 | 全量 150 篇 / 10000 题成本高；做 30 篇 / 200 题子集足够内部决策 |
| Cloud OCR / Tree Builder API | ❌ 不买 | MimirQ deepdoc 优于其开源 PyPDF2；他家壁垒在 Cloud OCR，不需要买单 |

### 7.3 致命的边界问题

PageIndex 适用 = **强结构长文档**（SEC filings / 招股书 / 法规 / 教科书）。MimirQ 客户画像（参考 `rag-poc-to-mvp-delivery-2026-q2.md` / `rag-poc-attribution-framework-2026-q2.md`）以 *B 端企业杂文档* 为主：

| 文档类型 | PageIndex 表现 | MimirQ 现有 hybrid |
|---|---|---|
| 财报 / 招股书 / 法规 | ✅ 优 | 中 |
| 技术手册 / 产品手册 | ✅ 优 | ✅ 优 |
| 会议纪要 / 邮件 / 工单 | ❌ 崩盘（无 TOC） | ✅ 优 |
| Excel / 表格密集 | ❌ 崩盘 | ✅ 优 |
| 产品需求 / 散文体 | ❌ 崩盘 | ✅ 优 |
| 工控售后 KB（参照 PoC-to-MVP 案例） | ❌ 崩盘 | ✅ 优 |

**结论**：抄全栈在 20% 文档类型上有用，但要付出全栈改造（940 行）成本，**ROI 失衡**。

### 7.4 修订后的实施路径（替代第 5.2 节里程碑）

| 阶段 | 时间 | 内容 | 触发条件 |
|---|---|---|---|
| **Stage 0**（先做） | **1 周** | **附录 6.4 的内部 benchmark**（不依赖 PageIndex，量化 MimirQ 现状） | 立即启动 |
| Stage 1（按需） | 1 周 | 200 行轻量 tree-search-style tool agent workflow（不重建数据模型，复用 hierarchy_expand） | 仅当 Stage 0 暴露"长结构文档场景"短板 |
| Stage 2（按需） | 0.5 周 | router 加 1 条 tool agent 分支 | Stage 1 完成后 |
| ~~Stage P0 全栈~~ | ~~3 周~~ | ~~原 4 落点~~ | **取消**，ROI 不足 |
| Stage P3（远期） | 按需 | PageIndex 官方 MCP 作为兜底 retriever | 客户明确要求且接受外部 LLM |

### 7.5 真正应该做的事（按价值排序）

1. **建 benchmark**（Stage 0）—— 见附录 6.4，1 周可交付，给销售 / PM 一个能 quote 的硬数据
2. **抄接口设计**（Stage 1，仅在 Stage 0 暴露短板时启动）—— ≤200 行
3. **router 加分支**（Stage 2，可选）—— ≤50 行
4. **保留 P3 备选** —— 客户场景明确时再考虑

---

## 附录补充

### 6.4 1 周内部 benchmark 落地清单（Stage 0，独立于 PageIndex）

**目标**：用 1 周建立 MimirQ 现有 hybrid retrieval 在金融文档场景的硬数据 baseline，给销售 / PM 可 quote 的数字，不依赖 PageIndex 接入。

**前置条件**：
- 已有 `evaluation/poc_runner/` 框架（参照 `rag-poc-attribution-framework-2026-q2.md`）
- 已有 `llm_judge.py` 评测框架（参照 `rag-evaluation-deep-dive-2026-q2.md` Stage 1）
- 已有 5 字段埋点（`original_query / llm_response / final_context_filenames / feedback_score / latency_total_ms`）

#### Day 1-2：评测集建设

- [ ] 拉 FinanceBench 数据集（arxiv 2311.11944 公开 150 文档）
- [ ] 抽样 30 篇文档（覆盖 10-K / 10-Q / 8-K / earnings call / proxy statement 5 类）
- [ ] 抽样 200 道题（数值 / 比较 / 趋势 / 解释 4 类各 50 题，对齐 Mafin 2.5 协议）
- [ ] **新建中文金融评测集**：5 篇 A 股年报（公开 PDF）+ 50 题人工标注（覆盖中文场景）
- [ ] 数据落地：`evaluation/poc_runner/finance_bench_subset/`（FinanceBench 子集）+ `evaluation/poc_runner/cn_finance_bench/`（中文集）
- [ ] schema 对齐 `rag-eval-dataset-deep-dive-2026-q2.md` Stage 1 标准

#### Day 3：跑 baseline

- [ ] 在 MimirQ 现状跑评测集 A 组（hybrid retrieval：vector + BM25 + ColBERT + reranker + hierarchy_expand）
- [ ] 跑评测集 B 组（仅 vector，关 BM25/ColBERT/rerank/hierarchy_expand，作为消融对照）
- [ ] 记录每题：accuracy / cost(token × $) / latency p95 / 失败模式 4 分类

#### Day 4：跑 PageIndex 开源版基线（作为外部对照，不接入 MimirQ）

- [ ] PageIndex 开源版 self-host（`pip install` + 标准 PyPDF2）
- [ ] 在同一评测集跑（FinanceBench 30 篇 + 中文 5 篇）
- [ ] 记录同样指标
- [ ] **关键观察**：开源版（无 Cloud OCR）能否复现 Mafin 2.5 的 98.7%？预期答案：不能，会差 10-30pt，因为他家真正护城河在 Cloud OCR

#### Day 5：分析 + 报告

- [ ] 三组对照表（A 现状 / B 消融 / C PageIndex 开源）
- [ ] 失败模式归因：哪些题 MimirQ 失分？哪些 PageIndex 失分？
- [ ] **核心问题回答**：
  1. MimirQ 现状在 FinanceBench 是多少分？
  2. 与 Mafin 2.5 的 98.7%（其 Cloud 版）差距多少？
  3. 与 PageIndex 开源版差距多少？
  4. 是否触发 Stage 1 启动条件（PageIndex 在某子类显著优于 MimirQ ≥ 5pt）？
- [ ] 输出 HTML 单文件报告（参照 `rag-kg-snapshot-deep-dive-2026-q2.md` 三原则：FILE_A023 / 客观中立 / 单文件）
- [ ] 报告归档：`evaluation/poc_runner/finance_bench_subset/report_2026-05-XX.html`

#### 决策门槛（Day 5 报告输出后）

| 报告结果 | 决策 |
|---|---|
| MimirQ 现状 ≥ 80% accuracy（中文 ≥ 75%） | 已有方案够好，**关闭 PageIndex 借鉴主题**，不进 Stage 1 |
| MimirQ 现状 70-80%，PageIndex 开源版同等 | 都不够好，问题不在引入 tree search，而在**优化现有 hybrid**（参考 `rag-context-expansion-rerank-2026-q2.md`），关闭本主题 |
| MimirQ 60-70%，PageIndex 开源版 ≥ 85% | **触发 Stage 1**，落 200 行轻量 tree search workflow |
| MimirQ 与 PageIndex 在不同题型互有胜负 | **触发 Stage 2**，建 router 分支共存（双方都保留） |

#### 工作量预估

| 任务 | 工时 | 负责人 |
|---|---|---|
| 评测集准备 | 8h | 评测工程师 |
| 中文集人工标注 | 6h | 业务专家 + 标注外包 |
| Baseline 三组运行 | 8h（含等待） | RAG 工程师 |
| 报告分析 + HTML 生成 | 6h | RAG 工程师 + PM |
| **合计** | **~28h / 1 周** | — |

#### 长期价值（即使不接 PageIndex 也值得做）

1. 建立 MimirQ 在金融文档场景的硬数据 baseline，**给销售用**
2. 评测集进 `evaluation/poc_runner/` 长期维护，未来任何 RAG 改动都跑此集做回归
3. 暴露 hybrid retrieval 在 SEC 类文档上的真实短板，指导 P1+ 优化方向（不一定要 tree search）
4. 输出的 HTML 报告对齐 PoC 客户沟通方式（参照 `rag-poc-attribution-framework-2026-q2.md` 三原则），可直接用于客户演示

---
