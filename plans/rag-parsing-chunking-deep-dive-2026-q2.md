# 文档解析 × 切块 深度调研报告（2026 Q2）

> **编写日期**：2026-04-18
> **定位**：前 5 份 plan 的 **解析层 + 切块层专项深化**。综合报告各给 1–2 章；本文纵向深挖，核心输出是"**内部 OmniDocBench 基线 + Vectara 25×48 切块网格**两项建设计划"。
> **核心问题**：解析与切块是 RAG 第一步的质量天花板。我方有 25 parser（~5500 行）+ 70+ 切块策略（~17700 行）+ 自研 DeepDoc（~8300 行）—— **功能覆盖在业界第一梯队**，但是否**真比 MinerU 2.5 / Docling 准**、是否**真比 fixed-size 512 好**，全未量化。本文给出如何证明。
> **交叉引用**：`rag-capability-gap-2026-q2.md` §2-3；`rag-deep-research-2026-q2.md` §4-5；`rag-eval-dataset-deep-dive-2026-q2.md` §2.8；`rag-agentic-reasoning-deep-dive-2026-q2.md`（agent 消费 chunk 的粒度）。

---

## 1. 全貌：我方栈规模与业界对标

### 1.1 我方栈规模（2026-04-18 核对）

| 模块 | 行数 | 子模块数 | 备注 |
|---|---|---|---|
| `app/parsing/parsers/` | **5531 行** | 25 个 parser | DeepDoc / MinerU / Marker / Magic-PDF / Docling / TextIn / olmOCR / DeepSeek-OCR / PaddleVL / Qianfan / GLM / TCADP / markitdown / pandoc / ETL4LLM + 基础类型 |
| `app/parsing/enrich/` | ~1200 行 | 10 个 | formula_ocr / image_caption / vlm_image_caption / table_markdown / seal_recognition / ocr_redaction |
| `app/parsing/processors/` | ~600 行 | 4 个 | cross_page_merge / vlm_correction / parse_cache / parser_service |
| `app/parsing/quality/` | ~800 行 | 6 个 | document_quality / text_quality / ocr_validator / reading_order / benchmark / competition |
| `app/parsing/preprocess/` | ~700 行 | 7 个 | deskew / handwriting_cleanup / orientation / paddle_doc_preprocess / watermark |
| `app/deepdoc/vision/` | **3660 行** | 8 文件 | layout_recognizer / table_structure_recognizer / ocr / operators / postprocess / recognizer |
| `app/deepdoc/parser/` | **4633 行** | 13 文件 | **pdf_parser.py 1620 行** / mineru_parser 655 / docling_parser 388 / tcadp_parser 454 |
| `app/rag/chunking/strategies/` | **17722 行** | **70+ 策略** | 通用 + 垂类（docker_compose / ansible / jira / github_actions / latex_sections / postmortem / sop_steps / prd_spec / meeting_minutes / 等） |
| `app/rag/chunking/` 核心 | 1257 行 | factory 590 / contextual_enrichment 199 / quality_scorer 186 / roles 209 / base 29 | — |
| `app/rag/preprocessing/` | ~3500 行 | 27 文件 | boilerplate / cleaning / html_canonical / language / near_dedup / normalization / pii_anonymizer / quality_filters / secrets / simhash / stopwords / tables / tokenization / urls |

**合计：解析 + 切块 ≈ 33000+ 行**，堆量在开源头部项目级别。

### 1.2 量级对比（业界开源）

| 项目 | 解析部分规模 | 覆盖格式 |
|---|---|---|
| **我方** | ~14000 行（parsing+deepdoc） | 25+ |
| **Unstructured.io** | ~15000 行 | 30+ |
| **Docling** | ~10000 行（Python 部分） | 10+ |
| **MinerU** | ~8000 行 | PDF / 图像为主 |
| **Marker** | ~3000 行 | PDF |
| **LlamaParse** | 闭源 API | — |

**结论**：**代码量上我们已接近第一梯队**，真正的 gap 不是"缺实现"，是**缺 benchmark 量化证明**。

---

## 2. OmniDocBench 详解（权威 PDF 解析基准）

**论文**：OmniDocBench（CVPR 2025，arXiv:2412.07626）—— 当前 PDF 解析**最权威的综合基准**。

### 2.1 基准覆盖

- **文档类型**：论文 / 教材 / 试卷 / 财报 / 法律 / 杂志 / 幻灯片 / 手写 / 笔记 9 类（中英混合）
- **子任务**：
  1. Layout detection（版面元素分类）
  2. OCR（文字识别）
  3. TSR（表格结构识别）
  4. Reading order（阅读顺序）
  5. Formula recognition（公式）
- **评测指标**：Edit distance、GriTS（表格）、mAP（布局）、CER/WER（OCR）、Hit@k（阅读顺序）

### 2.2 2026 核心分数

| 系统 | OmniDocBench v1.5 | GPU 速度 | 许可证 |
|---|---|---|---|
| **MinerU 2.5**（pipeline mode） | **86.2** | 0.21s/页 (L4) | Apache 2.0 + 无 AGPL 污染 |
| MinerU 2.0-2505-0.9B (VLM) | ~84 | 略慢 | — |
| **Docling**（TableFormer + DocLayNet） | — | 0.49s/页 (L4) / 1.27s/页 (M3 Max) | **MIT** |
| GPT-4o（通用 VLM） | 落后专用 | 慢 | 商业 API |
| **Mathpix**（中文 SOTA） | 中文第一 | 慢 | 商业 API |

**关键结论**：
- **MinerU 2.5 是最强开源**，可商用（已移除 AGPLv3 / CC-BY-NC-SA 4.0 模型）
- **Docling 表格最强**（97.9% 复杂表格准确）
- **中文建议 Mathpix**（即使 GPT-4o VLM 也落后于专用管线）

### 2.3 我方现状对标

- `app/parsing/parsers/mineru_parser.py`（123 行）+ `app/deepdoc/parser/mineru_parser.py`（655 行）—— **有但可能老版**
- `app/parsing/parsers/docling_parser.py`（314 行）+ `app/deepdoc/parser/docling_parser.py`（388 行）
- 自研 `app/deepdoc/vision/layout_recognizer.py`（254 行）+ `table_structure_recognizer.py`（597 行）+ `ocr.py`（717 行）
- `app/parsing/quality/benchmark.py` + `competition.py` **存在但未跑 OmniDocBench 报分**

### 2.4 Gap + 建议（关键建设）

- **P0** `plans/scripts/omnidocbench_runner.py`：
  - 下载 OmniDocBench 公开集
  - 跑我方 DeepDoc / MinerU 2.5 / Docling 三家
  - 出 accuracy × latency × cost 表
  - **若 DeepDoc 分数低于 MinerU 2.5，下一步是切到 MinerU 2.5 为默认**
- **P0** MinerU parser 升级到 2.5：已可商用 + 支持 PPTX/XLSX + thread-safe 多 GPU 并发；如果我方仍在老版，直接升级是免费质量提升
- **P1** 新增 `parsers/mathpix_parser.py`：中文长尾 / 公式密集文档专用通道
- **P1** `routing.py` 增加 quality fallback：分数 < 阈值 → 自动尝试第二后端 → 择优

---

## 3. 25 parser 与 9 家业界方案头对头

### 3.1 业界分类

| 类别 | 代表 | 我方有否 |
|---|---|---|
| **Pipeline 专用**（强） | MinerU 2.5 / Docling / Mathpix | ✅ MinerU + Docling |
| **VLM 原生** | GPT-4o / Gemini 2.5 / LlamaParse / GLM-OCR | ✅ GLM / olmOCR / DeepSeek-OCR / PaddleVL / Qianfan |
| **专门 OCR** | PaddleOCR / TextIn / TCADP | ✅ TextIn / TCADP |
| **学术 PDF** | Nougat / Marker / Magic-PDF | ✅ Marker / Magic-PDF |
| **通用转换** | markitdown / pandoc | ✅ 全有 |
| **端到端 ML** | ETL4LLM / NVIDIA Nemotron | ✅ ETL4LLM，缺 Nemotron |
| **Rust 级速度** | Ferrules | ❌ 缺 |
| **视觉直接** | ColPali / ColQwen | ❌ 缺（见 §5） |

### 3.2 选型决策矩阵（给工程师）

| 文档特征 | 首选 parser | 备选 |
|---|---|---|
| 英文学术 PDF（含公式） | Marker / MinerU 2.5 | Magic-PDF |
| 中文财报 / 法律 / 长文 | **Mathpix** | TextIn / TCADP |
| 扫描件 | DeepSeek-OCR / PaddleVL | MinerU 2.5 |
| 手写 | 自研 handwriting_cleanup + DeepSeek-OCR | — |
| 高表格密度 | **Docling** | MinerU 2.5 |
| 幻灯片 | pptx_parser 直出 + VLM | MinerU 2.5（仅 2.5+） |
| 极快需求（Rust 级） | 暂无 | 未来 Ferrules |
| 视觉 patch 检索 | ColPali（见 §5） | — |

### 3.3 我方 `app/parsing/routing.py` 现状

- 有路由骨架 ✅
- **建议增加"质量分数 < threshold → fallback"的仲裁**（P1）
- 当前缺**决策追踪**（哪个文档走了哪个 parser，为什么），`processors/parser_service.py` 可加
- 建议接 Prometheus metric：`parser_selection_total{parser="mineru"} / {fallback="true"}`

---

## 4. 表格深度理解

### 4.1 业界前沿（2025–2026）

| 系统 | 年份 | 核心 | 关键数字 |
|---|---|---|---|
| **Table Transformer (TATR)** | Microsoft | 检测 + TSR | PubTables-1M 基线 |
| **TableFormer (IBM)** | — | 视觉 TSR（HTML + BBox 双 decoder） | SOTA TSR 多个数据集 |
| **TableFormer (Google TAPAS)** | — | 表格推理 | SQA +6%（抗扰动） |
| **DePlot** | 282M | 图表 → 表格（one-shot） | CoT/SC/PoT prompting 配合 |
| **TAPEX / TAPAS / TUTA** | 经典 | 表格 QA | 长表落后 |
| **UniTable / DocFormer / LayoutLM** | 多模态 | 版面 + 表格 | 仍 lag 长财报 |
| **PubTables-v2**（arXiv:2512.10888, Dec 2025） | 135,578 表 | **首个多页 TSR 大规模基准** | 基于 PubMed 2023–2025 |
| **POTATR**（PubTables-v2 同期） | — | image-to-graph 扩 TATR | 多页 TSR |
| **TASER**（arXiv:2508.13404, 2026） | — | 长财报表格 + schema | Table Representation Learning 长文落后警告 |
| **XLLM 2025** | 2025-02 | MLLMs vs 专用 OCR | GriTS F1 评测 |

### 4.2 核心发现

- **MLLMs（GPT-4o / Gemini / Granite Vision）在简单表格上接近专用管线，但在长、复杂、跨页表格上仍落后 TableFormer / TATR**
- **多页 TSR 是当前短板**（PubTables-v2 推出正是为此）
- **Chart-to-Table 是相对独立的子问题**（DePlot 范式成熟但 282M 参数非零开销）

### 4.3 我方现状对标

- `app/deepdoc/vision/table_structure_recognizer.py`（597 行）—— 自研 TSR，**未跑 GriTS / PubTables-v2**
- `app/parsing/enrich/table_markdown.py` —— table → markdown
- **无 Chart-to-Table / DePlot 等价物**
- **无 NL2SQL 闭环**（虽有 `db_catalog` 但未连）

### 4.4 建议

- **P1** 内部 PubTables-v2 / GriTS 报分：证明自研 TSR 是否可留
- **P1** `parsing/enrich/chart_to_data.py`：DePlot 或 UniChart 集成，图表 → 结构化数据点，产物作独立 chunk type `chart_data`
- **P2** `tools/nl2sql.py`：连 `db_catalog`，text-to-SQL（DAIL-SQL / C3-SQL 风格）+ schema linking，结果摘要回 LLM
- **P2** 多页表格合并：`cross_page_merge.py` 增加表格专用合并逻辑（行延续 / 表头复用）

---

## 5. ColPali / ColQwen：跳过 OCR 的视觉检索

### 5.1 ColPali 范式（ICLR 2025，arXiv:2407.01449）

- **不做 OCR 和版面分析**
- 直接对**文档页面图像**用 VLM（如 PaliGemma / Qwen2-VL）产 **patch 级 late interaction 向量**
- 检索时 query text embedding × page patch embeddings → MaxSim 聚合

### 5.2 工程代价

- **向量膨胀 100×**：10M chunks 对应 1B 向量；Milvus 可承载但参数需调
- LLM 消费问题：ColPali 返回**图像**，需 VLM 下游（不能用纯文本 LLM）
- **PLAID 压缩**可以减 75% 存储，但引入复杂度

### 5.3 与我方现有管线的融合

- 独立子集合：`colpali_page_embeddings`
- 检索时与文本通道**RRF 融合**
- 只有 VLM 模型作 generator 时才能发挥价值

### 5.4 2025 工程实践

- HuggingFace Cookbook 有 Milvus + ColPali + Qwen2-VL 完整示例
- Voice-Vision RAG（AI Engineer World's Fair 2025）：voice + ColPali 端到端

### 5.5 我方现状对标

- `app/rag/embedding/clip_embedder.py` —— CLIP 基础
- `app/rag/core/vision_reader.py` —— 视觉读取
- **无 ColPali / ColQwen 接入**

### 5.6 建议

- **P1** `parsers/colpali_parser.py`（~300 行）：ColPali / ColQwen-v0.2 接入；输出到独立 Milvus 子集合
- **P1** `retriever.py` 新增 `colpali_retriever`：late interaction 召回 + 与文本 RRF 融合
- **P2** PLAID 压缩（若存储成本成为瓶颈）
- **前置条件**：上游 LLM 具备多模态能力（GPT-4o / Claude Sonnet 4.6 / Qwen2.5-VL）

---

## 6. 公式 / 印章 / 手写 / 水印：Enrichment 完整链路

### 6.1 业界对标

- **公式**：LaTeX-OCR、Mathpix、Marker 的 Nougat 模块
- **印章**：专用 seal-detection 模型（业务场景高价值）
- **手写**：HTR（Handwritten Text Recognition）模型（PaddleOCR 有）
- **水印**：图像去水印（对法律文档敏感）

### 6.2 我方现状

- `app/parsing/enrich/formula_ocr.py` —— 公式 OCR ✅
- `app/parsing/enrich/seal_recognition.py` —— 印章识别 ✅
- `app/parsing/preprocess/handwriting_cleanup.py` —— 手写清理 ✅
- `app/parsing/preprocess/watermark.py` —— 水印处理 ✅
- `app/parsing/enrich/ocr_redaction.py` —— OCR 脱敏
- `app/parsing/enrich/image_ocr.py` / `image_caption.py` / `vlm_image_caption.py` —— 图像理解

**结论**：**enrichment 链路齐全**，是我方领先业界开源的部分。

### 6.3 Gap

- 公式 / 表格 / 代码 / 图表 / 印章**是否进入独立子索引 reachable**？若都混在 body chunk，检索时无法按类型加权
- **建议**：引入 `chunk_type ∈ {text, formula, table, code, figure, chart_data, seal}` 作为 metadata 一级字段；retriever 可按 query type 加权

### 6.4 建议

- **P1** `chunking/roles.py`（已有 209 行）扩展：chunk_type 枚举 + metadata 标准化
- **P1** `retriever.py` 增加"按 chunk_type 加权"参数；orchestrator 按 query type 调整

---

## 7. 切块策略实证：Vectara NAACL 2025 反直觉结论

### 7.1 Vectara 论文（arXiv:2410.13070，NAACL 2025）

**实验规模**：**25 种切块配置 × 48 种 embedding 模型 = 1200 组合**；覆盖 retrieval / evidence retrieval / answer generation 三层任务。

**核心反直觉结论**：
1. **切块配置的影响 ≥ embedding 选择**（甚至更大）
2. **真实文档集合上，fixed-size 切块稳定优于 semantic chunking**（三层任务全赢）
3. 语义切块的计算开销**不被结果合理化**

### 7.2 Chroma "Context Rot" 研究（2025 Jul）

- 测 18 个主流 LLM（GPT-4.1 / Claude 4 / Gemini 2.5）
- 结论：**context 长度增加，检索性能下降**（即使 needle-in-haystack 容易）
- **"Context Cliff" ≈ 2500 tokens**（质量陡降点，2026-01 跟进研究）
- sentence chunking 在 ~5000 tokens 以内接近 semantic chunking，但成本远低

### 7.3 Fragment Size 陷阱（FloTorch 2025）

- Chroma 测试语义切块 **91.9% Recall@k**
- FloTorch 测试同样语义切块端到端 **仅 54% accuracy**（比 recursive 低 15 pp）
- 原因：FloTorch 语义切块平均 **43 tokens**，LLM 上下文不足
- **必须设最小 chunk size floor（256 tokens）**

### 7.4 Microsoft Azure 默认推荐

**512 tokens + 128 overlap（25%）** 是经典起点（BERT tokens，不是字符）。

### 7.5 我方现状对标

- **70+ 种垂类切块策略**（`app/rag/chunking/strategies/`）—— 功能覆盖远超业界
- `chunking/strategies/semantic.py` —— 语义切块
- `chunking/strategies/token.py`（98 行） / `recursive.py` / `sentence_window.py` —— 基础
- `chunking/contextual_enrichment.py`（199 行）—— Anthropic 风格 ✅
- `chunking/quality_scorer.py`（186 行） + `app/services/chunk_quality_gate.py` —— 质量门

**Gap**：
- **70+ 策略**但**没有在内部 Vectara 风格网格上证明哪些真有效**
- 语义切块是否强制 **minimum chunk size floor** 未确认
- Context Cliff @2500 是否触发告警未确认

### 7.6 建议（关键建设）

- **P0** `plans/scripts/chunking_grid_runner.py`：
  - 选 3 个语料（中英企业 / 技术手册 / 法律）
  - 跑网格：{fixed 256/512/1024} × {overlap 0/10%/25%} × {semantic / recursive / sentence_window / parent_child / contextual}
  - 报 retrieval recall / answer EM / cost 三表
  - **目标：证伪或证实 Vectara 的反直觉结论，决定我方默认策略**
- **P0** `strategies/semantic.py` 加 **minimum chunk size floor（默认 256 tokens）**
- **P0** `core/context_compression.py` / orchestrator 加 Context Cliff 监测：总 context tokens > 2500 时 metrics 报警
- **P1** 精简 70+ 策略：基于 grid runner 结果剔除未证明有效的垂类（降维护成本）

---

## 8. Anthropic Contextual Retrieval 惰性增量方案

### 8.1 原版（2024-09）

- 为每个 chunk 生成 **50–100 token 的文档上下文前缀**
- 召回率 **+35%**
- 缺点：**每个 chunk 都要 LLM 调用，成本高**（~1/3 文档入库成本）

### 8.2 惰性增量方案（本文提案）

- **首次入库不做 contextual enrichment**
- 监听 `evidence_gap` 报警：某 chunk 在召回后被判为"上下文缺失"
- 仅对这些 chunk 反向生成 contextual prefix → 重建该 chunk 索引
- **成本降 ~70–90%**（因为只处理真正失败的 chunk）

### 8.3 我方现状对标

- `app/rag/chunking/contextual_enrichment.py`（199 行）—— Anthropic 风格已实现
- 运行模式：全量入库即调 —— 成本模式
- `app/rag/retrieval/evidence_gap.py` —— 已有信号源

### 8.4 建议

- **P0** `contextual_enrichment.py` 增加 `lazy_mode`：默认关闭；启用后仅在 `evidence_gap` 判定失败时反向调用
- **预计收益**：contextual enrichment 成本降至 10–30%，召回质量持平

---

## 9. RAPTOR：递归摘要层级索引

### 9.1 原版（ICLR 2024，arXiv:2401.18059）

- **递归**：chunks → 聚类 → LLM 摘要 → 重嵌入 → 再聚类 → ... → 根节点
- **检索两种策略**：
  - **Tree traversal**：逐层向下剪枝（精）
  - **Collapsed tree**：拍平所有层作同级检索（快）—— 更常用
- **收益**：QuALITY +20%（带 GPT-4）

### 9.2 2025 改进（Frontiers, Dec 2025）

- Fixed-token chunking 是 RAPTOR 的 **bottleneck**（语义边界被切断）
- **改进 1**：semantic chunking（similarity 阈值 0.7 切分）
- **改进 2**：GMM 聚类 → **Leiden 图聚类**（k-NN 图 + 社区检测）
- **改进 3**：layer-aware 自适应参数（k 增大、resolution 减小）

### 9.3 生产工程

- **RAGFlow v0.6.0 已集成** RAPTOR（ragflow.io/docs/enable_raptor），threshold 默认 0.1，cluster 默认 64
- 官方实现 `parthsarthi03/raptor`
- VectorHub 教程（LanceDB + GMM）

### 9.4 我方现状对标

- `app/rag/chunking/utils/hierarchical.py` + `strategies/parent_child.py` —— 层级有，但**不是 RAPTOR**（没有聚类 + LLM 摘要）
- `integrated_pipeline/` 有集成骨架
- **无 RAPTOR 完整实现**

### 9.5 建议

- **P0**（与 KG 专项的 `pprank` 并列最值得做）：`strategies/raptor.py`（~400 行）：
  - 递归聚类（可选 Leiden 或 GMM）
  - LLM 摘要产父节点
  - 父节点重嵌入 + metadata 记 `raptor_layer`
  - 检索时默认 collapsed tree
- **P1** 2025 Frontiers 改进：semantic 预切块 + Leiden 聚类（更高质量，成本略增）
- **预计收益**：多跳 QA (HotpotQA / MuSiQue 级) 显著提升；QuALITY +20%（按论文）

---

## 10. Late Chunking（Jina 2024）

### 10.1 核心机制

- 原 RAG：**先切后嵌** → 每 chunk 独立嵌入，边界信息丢失
- Late Chunking：**先嵌后切** → 整文档一次 pass 产 token embeddings → 按 chunk 边界做 mean pooling
- 优势：每 chunk embedding 保留全文档上下文信号

### 10.2 前置条件

- 需要 **long-context embedding 模型**（Jina v3 8K / BGE-M3 8K）
- 整文档 embedding 成本 ≈ 按 chunk 单独嵌入，但**需要能一次吃下整文档的模型**

### 10.3 我方现状对标

- 默认 BGE-M3（长文支持 8K）✅ **具备前置条件**
- **未实现 late chunking**

### 10.4 建议

- **P1** `strategies/late_chunking.py`（~200 行）：
  - 整文档 embedding（BGE-M3 或 Jina v3）
  - 按已有切块边界做 mean pool
  - 产 chunk embedding + 原始 chunk 原文
- **配合 A/B**：与普通切块在召回 recall/precision 上对比

---

## 11. Proposition Indexing / Small-to-Big / Parent-Doc / Sentence-Window

### 11.1 四种多粒度策略

| 策略 | 检索粒度 | 返回给 LLM 粒度 | 适用 |
|---|---|---|---|
| **Proposition indexing**（Dense X, 2023） | 原子命题（1 句 1 事实） | 可变 | 精准事实 |
| **Small-to-Big / Parent-Doc** | 小 chunk | 父 chunk（或整文档） | 通用 |
| **Sentence-Window** | 单句 | 句子 + 前后 N 句 | 精准 + 上下文平衡 |
| **RAPTOR collapsed tree**（§9） | 多层 | 多层混合 | 多跳 + 全局 |

### 11.2 我方现状对标

- `strategies/proposition.py` —— ✅
- `strategies/parent_child.py` —— ✅（small-to-big）
- `strategies/sentence_window.py` —— ✅
- **最完整**

### 11.3 建议

- **P0**（与 §7 grid runner 联动）：实证这 4 种在我方语料上的相对表现，**不要盲目保留**
- **P1** parent_child 引入层级缓存（父 chunk 可预计算）

---

## 12. Agentic Chunking / Semantic Double Merging

### 12.1 业界前沿

- **Agentic Chunking**：LLM 作 judge 决定边界（高成本但语义最准）
- **Semantic Double Merging**：两轮相似度 + LLM 仲裁
- **LLM-as-chunker**：一次 pass 输出切块决策序列（成本最高）

### 12.2 生产价值

- 高价值 / 低频语料（法律合同、技术规范、医疗指南）**值得做**
- 通用 / 高频语料（网页、客服）**不值得**（成本远超收益）

### 12.3 我方现状对标

- `strategies/semantic.py` —— 基础语义切块
- 无 LLM-as-judge agentic chunker

### 12.4 建议

- **P2** `strategies/agentic_chunker.py`：批处理模式（离线），仅对 tenant/dataset 级配置开启
- **运营上**：配合 chunk_quality_gate，失败样例进 agentic chunker 重切

---

## 13. 我方 25 parser + 70+ 策略 × 业界基准：建设蓝图

### 13.1 内部 benchmark 建设（最关键的 P0）

**两个并行建设**：

#### (a) 内部 OmniDocBench 基线（解析层）

**路径**：`app/rag/evaluation/parse_bench/`

```
parse_bench/
├── datasets/
│   ├── omnidocbench_subset/       # OmniDocBench 公开集采样
│   ├── internal_real_docs/        # 我方真实企业文档 500 份（标注 gold JSON）
│   └── chinese_long_tail/         # 中文长尾子集（法律/医疗/政务）
├── metrics/
│   ├── edit_distance.py
│   ├── grits.py                   # 表格 GriTS
│   ├── reading_order_hit.py
│   └── formula_accuracy.py
├── runners/
│   ├── deepdoc_runner.py
│   ├── mineru25_runner.py
│   ├── docling_runner.py
│   └── mathpix_runner.py
└── reports/
    └── comparison_matrix.py
```

**目标**：
1. 证明/证伪自研 DeepDoc 比 MinerU 2.5 好（若差，切默认 MinerU 2.5）
2. 证明中文长尾文档是否需要 Mathpix 特殊通道
3. 监督解析质量 regression

#### (b) 切块网格 runner（切块层）

**路径**：`app/rag/evaluation/chunking_grid/`

```
chunking_grid/
├── configs/
│   ├── fixed_256_0overlap.yaml
│   ├── fixed_512_128overlap.yaml
│   ├── fixed_1024_0overlap.yaml
│   ├── semantic_min256.yaml
│   ├── recursive.yaml
│   ├── sentence_window_3.yaml
│   ├── parent_child.yaml
│   ├── contextual.yaml
│   └── raptor.yaml
├── datasets/                       # 复用评测集专项 Stage 2 合成数据
├── metrics/
│   ├── retrieval_recall.py
│   ├── answer_em.py
│   └── cost.py
└── reports/
    └── 9x3_matrix.py               # 9 配置 × 3 数据集
```

**目标**：
1. 证伪或证实 Vectara 反直觉结论（fixed-size 优于 semantic）
2. 决定我方默认切块策略
3. 精简 70+ 策略中未证明有效的垂类

### 13.2 Gap 总表

| 能力 | 业界 SOTA | 我方状态 | 建议 |
|---|---|---|---|
| 内部 OmniDocBench 跑基线 | 未跑 | — | **P0 建** |
| 切块网格 runner | 未跑 | — | **P0 建** |
| MinerU 2.5 升级 | 不确定版本 | — | **P0** 升级 |
| Mathpix 中文 parser | 无 | — | P1 |
| RAPTOR | 无 | — | P0 |
| Late Chunking | 无 | — | P1 |
| Contextual Retrieval 惰性 | 全量模式 | — | P0 |
| ColPali parser | 无 | — | P1 |
| Chart-to-Table (DePlot) | 无 | — | P1 |
| NL2SQL | 无 | catalog 在 | P2 |
| Min chunk size floor | 未确认 | — | P0 |
| Context Cliff 监测 | 未确认 | — | P0 |
| 质量 fallback 闭环 | 未闭合 | — | P1 |
| chunk_type 独立索引 | 未确认 | roles.py 基础 | P1 |
| Ferrules 速度 | 无 | — | P3 |

---

## 14. 建议优化（按优先级）

### 🥇 P0（1–4 周，建基线 + 快速修复）

| # | 建议 | 预计收益 |
|---|---|---|
| 1 | 内部 `parse_bench/`（OmniDocBench + 500 真实文档） | 量化证明 + regression 基线 |
| 2 | 内部 `chunking_grid/`（9 配置 × 3 数据集） | 证伪 Vectara 反直觉 + 剪枝 70+ 策略 |
| 3 | `strategies/raptor.py` | 多跳 QA +20%（QuALITY） |
| 4 | MinerU parser 升级至 2.5（商用友好） | OmniDocBench 86.2，免费质量升 |
| 5 | Min chunk size floor 默认 256 | 避免 FloTorch 54% 端到端陷阱 |
| 6 | Context Cliff 监测（>2500 警报） | 成本治理 + 质量预警 |
| 7 | Contextual Retrieval 惰性增量模式 | 成本降 70% 召回质量持平 |

### 🥈 P1（1–2 月）

| # | 建议 | 理由 |
|---|---|---|
| 8 | `parsers/mathpix_parser.py`（中文长尾） | OmniDocBench 中文第一 |
| 9 | `parsers/colpali_parser.py` + 独立子集合 | 视觉密集文档质量 |
| 10 | `enrich/chart_to_data.py`（DePlot） | 图表 → 结构化数据 |
| 11 | `strategies/late_chunking.py`（Jina 风格） | 边界信息保留 |
| 12 | 质量 fallback 闭环（routing 分数仲裁） | 低质文档自愈 |
| 13 | PubTables-v2 / GriTS 内部表格跑分 | 证明 TSR 留用 |
| 14 | `chunk_type` metadata 一级字段 + 按类型加权 | 公式 / 表格 / 代码子通道 |

### 🥉 P2（2–6 月）

| # | 建议 |
|---|---|
| 15 | `strategies/agentic_chunker.py`（LLM-as-judge，离线） |
| 16 | `tools/nl2sql.py`（DAIL-SQL 连 catalog） |
| 17 | PLAID ColPali 向量压缩 |
| 18 | Ferrules（Rust 速度）集成 |
| 19 | Late-interaction 存储优化 |

### 观望

- Nemotron / GOT-OCR 2.0 跟进
- Agentic chunker 通用化
- 多页表格合并专用模型（PubTables-v2 的 POTATR）

---

## 15. 参考资料（未节号，作为附录）

### 解析基准
- [OmniDocBench (CVPR 2025, arXiv:2412.07626)](https://arxiv.org/html/2412.07626v1)
- [MinerU GitHub](https://github.com/opendatalab/MinerU)
- [PDF-Extract-Kit](https://github.com/opendatalab/PDF-Extract-Kit)
- [Docling (arXiv:2501.17887)](https://arxiv.org/html/2501.17887v1)
- [2025 Parse Benchmark](https://procycons.com/en/blogs/pdf-data-extraction-benchmark/)
- [2026 Parser Wrestling](https://medium.com/@ravi.retheesh/why-i-spent-2026-wrestling-with-these-10-document-parsers-unstructured-io-1e389ecf40db)

### 表格
- [Table Transformer (TATR) Microsoft](https://github.com/microsoft/table-transformer)
- [TableFormer IBM](https://openreview.net/pdf?id=kjZN7kBCit)
- [TableFormer Google TAPAS](https://github.com/google-research/tapas/blob/master/TABLEFORMER.md)
- [PubTables-v2 (arXiv:2512.10888)](https://arxiv.org/html/2512.10888v1)
- [TASER (arXiv:2508.13404)](https://arxiv.org/html/2508.13404)
- [Awesome-TSR](https://github.com/MathamPollard/awesome-table-structure-recognition)
- [XLLM 2025 Table Bench](https://aclanthology.org/2025.xllm-1.2.pdf)
- [DePlot (ACL 2023)](https://aclanthology.org/2023.findings-acl.660.pdf)

### ColPali 系
- [ColPali (arXiv:2407.01449)](https://arxiv.org/abs/2407.01449)
- [Multimodal RAG with ColPali (HF Cookbook)](https://huggingface.co/learn/cookbook/en/multimodal_rag_using_document_retrieval_and_vlms)
- [ColPali + Milvus](https://huggingface.co/blog/saumitras/colpali-milvus-multimodal-rag)

### 切块
- [Vectara NAACL 2025 (arXiv:2410.13070)](https://arxiv.org/abs/2410.13070)
- [Chroma Context Rot](https://research.trychroma.com/context-rot)
- [Anthropic Contextual Retrieval Blog](https://www.anthropic.com/news/contextual-retrieval)
- [Jina Late Chunking Blog](https://jina.ai/news/late-chunking-in-long-context-embedding-models/)
- [RAPTOR (arXiv:2401.18059)](https://arxiv.org/abs/2401.18059)
- [RAPTOR GitHub](https://github.com/parthsarthi03/raptor)
- [RAPTOR Enhanced (Frontiers 2025 Dec)](https://www.frontiersin.org/journals/computer-science/articles/10.3389/fcomp.2025.1710121/full)
- [RAGFlow RAPTOR](https://ragflow.io/docs/enable_raptor)
- [VectorHub RAPTOR Tutorial](https://superlinked.com/vectorhub/articles/improve-rag-with-raptor)
- [PremAI Chunking Benchmark Guide 2026](https://blog.premai.io/rag-chunking-strategies-the-2026-benchmark-guide/)
- [Firecrawl Chunking Strategies 2026](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)

### Proposition & Small-to-Big
- Dense X Retrieval (Chen et al., 2023)
- LlamaIndex Small-to-Big / Parent-Document Retriever 文档

### 本项目相关 plan（交叉引用）
- `plans/rag-capability-gap-2026-q2.md` §2-3
- `plans/rag-deep-research-2026-q2.md` §4-5
- `plans/rag-eval-dataset-deep-dive-2026-q2.md`（benchmark 方法论对齐）
- `plans/rag-kg-deep-research-2026-q2.md`（结构化检索的补充视角）
- `plans/rag-agentic-reasoning-deep-dive-2026-q2.md`（agent 消费 chunk 的粒度）

---

## 结论

1. **我方解析 + 切块栈规模在业界第一梯队**（~33000 行，25 parser，70+ 策略），**不缺实现**。
2. **最大问题是"未量化"**：没有内部 OmniDocBench + 切块网格作基线，无法证明自研比 MinerU 2.5 / Docling / fixed-size 512 好多少。
3. **P0 七项**全部围绕"**建基线 + 快速修复**"，4 周可落地；其中 `parse_bench` + `chunking_grid` 两个内部 benchmark 是**最重要的战略抓手**。
4. **P1 七项**围绕"补齐国际第一梯队未覆盖的能力"（Mathpix 中文 / ColPali / Late Chunking / Chart-to-Table / 质量 fallback / PubTables-v2 / chunk_type 索引）。
5. **核心洞察**：**解析切块的投资方向不是"再写 10 个 parser"，而是"建立能证明价值的 benchmark 体系"**。这呼应评测集专项 "选架构前先建评测集"的核心论断。

---

> **下一份专项**：③ 安全 / 合规 / Guard（Output Guard 扩容 + Llama Guard 3 + Presidio + 红队）

> **可独立拆的子 plan**：
> - `plans/parse-bench-builder.md`（内部 OmniDocBench 基线）
> - `plans/chunking-grid-runner.md`（切块网格）
> - `plans/mineru-25-upgrade.md`
> - `plans/strategies-raptor.md`
> - `plans/mathpix-parser.md`
> - `plans/colpali-parser.md`
> - `plans/chart-to-data.md`
> - `plans/late-chunking.md`
> - `plans/contextual-enrichment-lazy.md`
> - `plans/parser-quality-fallback.md`
