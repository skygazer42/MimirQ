# DeepDoc Pipeline 二次开发深化路线（2026 Q2-Q3）

> **核心思想**：MimirQ 已经 fork 了 RAGFlow DeepDoc 全栈（vision 3770 行 + parser 4555 行）+ 外层 33 个 backend + 1600 行 quality 评估栈——**模型层已经够了**。真正的二开杠杆在 **pipeline 编排 / 规则化后处理 / 几何算法 / 闭环流程**，而不是再塞一堆 HuggingFace 重模型。本 plan 严格遵循"**先 pipeline，后模型；先规则，后训练**"的次序。
>
> 创建日期：2026-05-18
> 来源：用户 12 项 DeepDoc 二开方向 + 用户明确指引"结合 pipeline 优化而不是集成很重的模型"
> 替代：之前 `deepdoc-secondary-development-2026-q2-q3.md`（偏模型集成方向）废弃
> 关联：
> - `plans/deepdoc-api-productization-2026-q3.md`（P1-2，对外 SaaS API 化）
> - `plans/rag-parsing-frontend-deep-dive-2026-q2.md`（前端 `/parsing` 工作台）
> - `plans/rag-parsing-chunking-deep-dive-2026-q2.md`（OmniDocBench / GriTS / 切块基线）
>
> **一句话**：DeepDoc 现状的 80% 问题是 **解析后没人编排、规则化后处理缺失、人工修正无闭环**——不是模型不够准。P0 全部是 pipeline + 规则化（零新模型），仅在 P2 才允许引入唯一一个 20M 极小公式模型。

---

## 0 阅读路径

| 章节 | 用途 |
|---|---|
| 第 1 章 | "Pipeline 二开" vs "模型集成" 的判定原则 |
| 第 2 章 | MimirQ DeepDoc 现状盘点（已 fork 的 vision / parser / quality 全栈） |
| 第 3 章 | 用户 12 项 × 现状对照 × **重新标注 pipeline 还是模型** |
| 第 4 章 | P0：5 件纯 pipeline 优化（零模型） |
| 第 5 章 | P1：3 件 pipeline 闭环 + 规则化后处理（零模型） |
| 第 6 章 | P2：3 件可选（其中仅"公式 LaTeX"用 20M 极小模型） |
| 第 7 章 | 落地里程碑（4-7 周 daily，全 pipeline） |
| 第 8 章 | 决策门槛与陷阱清单 |
| 第 9 章 | 范围之外 + 与其他 plan 的边界 |
| 附录 | 算法伪代码（reading order / 跨页表 / caption linker） |

---

## 1 "Pipeline 二开" vs "模型集成" 的判定原则

### 1.1 三条铁律

| 铁律 | 含义 |
|---|---|
| **铁律 1：能用规则就不用模型** | reading order / 跨页表 / caption 绑定 / 页眉页脚 / section tree / 中文后处理 全部纯几何 + heuristics |
| **铁律 2：能用现有 vision 输出就不调 HF 模型** | `vision/layout_recognizer.py` 已出 10 类 layout 标签 + bbox，`TSR.py` 已出 row/col/header/spanning——后处理拿这些数据就够 |
| **铁律 3：模型只在"无规则可言"时才引入** | 仅公式识别（OCR → LaTeX，纯文本结构推断无规则），且选 20M 的 Texo 而非 250M 的 nougat-latex |

### 1.2 为什么 pipeline 才是真正的护城河

| 维度 | 集成 HF 重模型 | Pipeline 优化 |
|---|---|---|
| **可移植** | 同行复制成本低（pip install 就行） | 同行需要逆向算法 + heuristic 阈值 + 流程编排 |
| **客户感知** | "你们用了 XX 模型" → 客户也能买到 | "你们解析后的表格能跨页合并 / reading order 自动修复 / 业务专家能改" → 不可替代 |
| **维护成本** | 模型升级、显存爆炸、推理慢、依赖更新 | 纯 Python 算法，零依赖、零 GPU |
| **可解释** | 黑盒，错了不知道怎么调 | 规则 + heuristic 可逐步调阈值 |
| **可调试** | 模型重训需要几天 | 改条件、改阈值、改顺序 → 立即生效 |

### 1.3 "什么时候不得不用模型"清单

| 任务 | 能用规则吗 | 结论 |
|---|---|---|
| Reading Order | ✅ bbox 几何 + 栏检测 + 字体大小 | **纯算法** |
| 跨页表合并 | ✅ 列数匹配 + bbox 列对齐 + 上一页 footer 文本 | **纯算法** |
| 页眉页脚去重 | ✅ 跨页文本重复检测 | **纯算法** |
| Caption 绑定 figure/table | ✅ 几何距离 + 关键词前缀 + 字体 | **纯算法** |
| Section tree | ✅ 字体大小聚类 + Title label + 层级推断 | **纯算法** |
| 表格 JSON Schema | ✅ 现有 TSR 输出后处理 | **纯算法** |
| 中文繁简 / 全半形 / 中英混排 | ✅ opencc / 字符映射表 / jieba | **纯规则** |
| 行业术语 / 同义词 | ✅ 词典查表 + industry_rules | **纯规则** |
| Quality Gate 触发 review | ✅ 阈值判断 | **纯规则** |
| Review UI 校正回写 | ✅ 工程实现 | **纯工程** |
| 文档预分类 / 增量 / 缓存 | ✅ 工程 | **纯工程** |
| OCR 错字修复 | ⚠️ 词典 + LLM correction | 词典 95% + LLM 兜底（已有 LLM） |
| 公式 → LaTeX | ❌ 无规则可言 | **极小模型必要**（Texo 20M） |
| 流程图 → graph | ❌ 复杂结构推断 | **VLM zero-shot 可选**，不自训 |

**P0 / P1 全部落在前 12 项**——零新模型。

---

## 2 MimirQ DeepDoc 现状盘点（重点：vision 已经够用）

### 2.1 vision 已经输出了什么

```
app/deepdoc/vision/                                  # 3770 行已就位
  layout_recognizer.py    254  ✅ 输出 10 类 layout 块 + bbox
                                  (Text/Title/Figure/FigureCaption/Table/TableCaption/
                                   Header/Footer/Reference/Equation)
  ocr.py / _ocr.py        717+255 ✅ OCR 文本 + 置信度
  operators.py            731  ✅ 图像预处理
  postprocess.py          371  ✅ 几何后处理
  recognizer.py           453  ✅ 区域识别
  table_structure_recognizer.py 597 ✅ row/col/header/projected_row_header/spanning_cell
  seeit.py / t_ocr.py / t_recognizer.py  辅助
```

**关键判断**：vision 已经把所有**结构信号**输出了——bbox、layout label、字体（部分）、OCR 文本、表格单元格关系。**剩下要做的是"用这些信号编排出业务可用的解析结果"**，不是再叠模型。

### 2.2 外层 pipeline 现状

```
app/parsing/
  parsers/              33 个 backend（deepdoc/docling/mineru/marker/markitdown/
                        magic-pdf/etl4llm/deepseek-ocr/glm-ocr/mathpix/olmocr/
                        paddle-vl/qianfan-ocr/textin/colpali/ 等）
  routing.py            ✅ choose_pdf_backend(quality, requested)
  factory.py            ✅ 统一工厂
  diagnostics.py        ✅ 解析诊断
  enrich/               ⚠️ 子目录已存在但内容稀薄 → **本 plan 重点扩充这里**
  processors/           ⚠️ 后处理流水线骨架已有
  quality/              1606 行（grits/reading_order/scorer/benchmark/ocr_validator）
  subprocess_runner.py + subprocess_worker.py  页级并行已有
```

**关键判断**：pipeline 骨架已就位，但 `enrich/` 和 `processors/` 是最薄的一层——**这就是本 plan 主战场**。

### 2.3 一句话总结

> **MimirQ DeepDoc 的"模型层"已超第一梯队**（vision 3770 行 + 33 个 backend）；**"pipeline 编排层 + 后处理层"是真正的瓶颈**（`enrich/` 与 `processors/` 几乎空白）。

---

## 3 用户 12 项 × 现状 × 重新标注（Pipeline / 模型 / 工程）

| # | 用户方向 | 现状 | 本质类型 | gap | 优先级 |
|---|---|---|---|---|---|
| 1 | Parser Router | 80% 已做 | **Pipeline** | 失败降级链 + 触发原因记录 | P0 |
| 2 | 表格 JSON Schema + 跨页合并 + Markdown/HTML | 35% | **Pipeline + 规则**（TSR 输出后处理） | 全部 | **P0** |
| 3 | Reading Order 修复 | 40%（只评估） | **算法 + 几何**（无模型） | 多栏排序 + 页眉页脚 + caption / section tree | **P0** |
| 4 | 流程图 / 架构图 graph | 0% | **VLM zero-shot 可选**（不自训） | 等客户拉力 | P2 |
| 5 | 公式 → LaTeX | 20% | **极小模型必要**（Texo 20M） | 等客户拉力 | P2 |
| 6 | Layout-aware chunking | 70% | **规则 + Pipeline** | 6 类策略补完 | P1 |
| 7 | 质量自检 | 75% | **规则**（阈值） | 接 review queue 闭环 | **P0** |
| 8 | Review UI 人工校正 | 5% | **工程 + Pipeline 闭环** | 全部 | **P0** |
| 9 | 多语言 / 繁中 | 45% | **纯规则**（opencc / 字符映射 / 词典） | 全部 | P1 |
| 10 | 大规模性能 | 50% | **工程**（缓存 / 增量 / 预热 / 队列） | 全部 | P1 |
| 11 | 对外 API / SDK | 65% | **工程** | 已在另 plan | 见 P1-2 plan |
| 12 | Benchmark | 70% | **规则 + 数据** | 中文 benchmark | 见 cn-benchmark plan |

**关键发现**：12 项里 **10 项是 pipeline / 算法 / 工程 / 规则**，只有 2 项（流程图 + 公式）真正需要模型——且都可放到 P2 视客户拉力再启动。

---

## 4 P0：5 件纯 pipeline 优化（零模型）

### 4.1 P0-A：Parser 失败降级链 + 触发原因记录（用户 #1 补完）

**现状**：`routing.py:choose_pdf_backend()` 已能基于 quality 选 backend；但**单次失败后没有自动降级链**，也**没有把"为什么选了这个 backend"和"降级路径"记录给前端可视化**。

**Pipeline 编排**：

```python
# app/parsing/processors/parser_fallback_pipeline.py（新）
class ParserFallbackPipeline:
    """
    1. 预检（pre_poc_scanner 输出 + 文档 hash 缓存）
    2. 主 backend 选择（routing.choose_pdf_backend）
    3. 执行 → 质量评分（quality/scorer.py 已有）
    4. 若 quality.grade == 'fail' 或 score < threshold:
       a. 记录失败原因（OCR 失败 / 表格失败 / reading order 异常 / 超时）
       b. 按 fallback_chain 选下一 backend
       c. 重试（max_retries=2）
    5. 全链失败:
       a. 兜底 Naive parser（纯文本）
       b. 标记为 REVIEW
    6. 全程 OTel span + 决策日志 → 前端展示
    """
```

**新增 / 改造**：

| 文件 | 行数 | 作用 |
|---|---|---|
| `app/parsing/processors/parser_fallback_pipeline.py`（新） | ~350 | 主编排器 |
| `app/parsing/processors/fallback_chain_config.py`（新） | ~80 | YAML/dict 配置降级链（scan→mineru→deepdoc→naive） |
| `app/parsing/processors/parse_decision_log.py`（新） | ~150 | 决策日志（哪个 backend 因为什么原因失败） |
| `app/parsing/routing.py`（改） | +50 | 暴露"为什么选这个" |
| 前端 `/parsing` 工作台（改） | +100 | 展示 decision log 时间线 |

**收益**：客户能看到"这份 PDF 主路径 MinerU 失败（表格识别异常）→ 降级 DeepDoc → 成功"，而不是黑盒。

---

### 4.2 P0-B：表格 Pipeline——JSON Schema + 跨页合并 + 多表示输出（用户 #2，零模型）

**目标**：把 `vision/table_structure_recognizer.py` 已有的 row/col/header/spanning 输出**重新编排**为可机读 JSON + Markdown/HTML/CSV 三表示 + 跨页合并 + cell-level confidence。**不引 TATR，不引 SLANet——纯后处理。**

**Schema**：

```python
# app/parsing/output/table_schema.py（新，~150 行）
class TableCell(BaseModel):
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    text: str
    is_header: bool = False
    is_projected_row_header: bool = False
    bbox: tuple[float, float, float, float]
    page: int
    confidence: float  # ← 来自 OCR 置信度（已有）+ TSR 一致性检验（新增规则）

class TableExtraction(BaseModel):
    table_id: str
    page_start: int
    page_end: int  # 跨页 > page_start
    rows: int
    cols: int
    cells: list[TableCell]
    caption: str | None
    representations: dict[Literal["markdown", "html", "csv"], str]
    quality: TableQuality  # row_consistency / col_consistency / cell_completeness / overall
    parser: str  # deepdoc / mineru / docling
    merged_from: list[str] | None  # 若是跨页合并，原 table_ids
```

**跨页合并算法（纯几何 + heuristic，零模型）**：

```python
# app/parsing/enrich/cross_page_table_merger.py（新，~300 行）
def merge_cross_page_tables(tables: list[TableExtraction]) -> list[TableExtraction]:
    """
    判定两个相邻页表是否同一表：
    1. cols 数完全相等
    2. 每列的 x 中心位置 |diff| < 5% 页宽
    3. 上一页 table 的 bbox.y_max 距页底 < 10% 页高
    4. 下一页 table 的 bbox.y_min 距页顶 < 10% 页高
    5. 下一页第一行内容不含 header 关键词（"序号"/"项目"/"金额" 等已在 industry_rules）
       或 上一页 footer 文本含"续表 / continued"
    6. （可选）字体大小一致

    满足 4 条以上 → 合并；标记 merged_from
    """
```

**Cell confidence 推断（无模型，组合现有信号）**：

```python
def compute_cell_confidence(cell, ocr_conf, tsr_consistency) -> float:
    """
    confidence = 0.6 * ocr_conf
              + 0.2 * tsr_row_consistency   # 同行 y 中心 std
              + 0.2 * tsr_col_consistency   # 同列 x 中心 std
    """
```

**Markdown/HTML/CSV 输出（纯模板）**：

```python
# app/parsing/enrich/table_to_markdown.py（新，~200 行）
def to_markdown(table: TableExtraction) -> str: ...  # GFM table
def to_html(table: TableExtraction) -> str: ...      # 含 rowspan/colspan
def to_csv(table: TableExtraction) -> str: ...
```

**新增 / 改造**：

| 文件 | 行数 | 作用 |
|---|---|---|
| `app/parsing/output/table_schema.py` | ~150 | Pydantic schema |
| `app/parsing/enrich/table_to_markdown.py` | ~200 | 三表示输出 |
| `app/parsing/enrich/cross_page_table_merger.py` | ~300 | 跨页合并算法 |
| `app/parsing/enrich/table_confidence.py` | ~120 | cell-level 置信度 |
| `app/deepdoc/vision/table_structure_recognizer.py`（**不改主流程**，只在外层包装时取信号） | 0 | 不动 |

**验证**：用现有 `quality/grits.py` 对自建 50 张中文财报表评测，跨页合并准确率 ≥ 90%；GriTS 较 vision/TSR 原输出 +5-10pt（来自 schema 化 + confidence 过滤低质 cell）。

---

### 4.3 P0-C：Reading Order 修复——纯几何算法（用户 #3，零模型）

**现状**：`quality/reading_order.py` 444 行只**评估**对错；本节新增**修复**算法，全部纯几何 + heuristic，**不引 LayoutReader**。

**核心算法**：

```python
# app/parsing/enrich/reading_order_fixer.py（新，~450 行）
def fix_reading_order(blocks: list[LayoutBlock]) -> list[LayoutBlock]:
    """
    Step 1: 按 page 分组
    Step 2: 每页内：
        a. 栏数检测（k-means clustering on bbox.x_center, k in [1,2,3]）
           - silhouette score 选最优 k
           - 单栏（k=1）：按 y 升序
           - 多栏（k>=2）：每栏内按 y 升序 → 栏间按 x 升序拼接
        b. Header/Footer 识别（在 Step 4 已剔除）
    Step 3: 跨页连续段落合并
        - 上页 last block.bbox.y_max 距页底 < 5% 页高
        - 下页 first block.bbox.y_min 距页顶 < 5% 页高
        - 字体大小相同（容差 ±1pt）
        - 上页 last block 末尾无句号（中英文）
        → 合并为单一逻辑段
    Step 4: 头尾去除
        - 跨页文本相似度 ≥ 90%（Jaccard / Levenshtein）+ 同位置（bbox.y 相对页高 < 10% 或 > 90%）
        - 同时出现在 ≥ 3 页 → 标记 header/footer，剔除
    Step 5: Caption 绑定（独立模块 caption_linker.py）
    Step 6: Section tree（独立模块 section_tree_builder.py）
    """
```

**配套独立模块**：

| 文件 | 行数 | 算法 |
|---|---|---|
| `app/parsing/enrich/header_footer_remover.py`（新） | ~150 | 跨页文本重复检测（hash + 相似度） |
| `app/parsing/enrich/caption_linker.py`（新） | ~200 | Figure/Table caption ↔ figure/table 绑定（几何距离 ≤ 50px + caption 关键词正则 `^(图|表|Fig|Tab)\s*\d+` + 字体小于正文 1-2pt） |
| `app/parsing/enrich/section_tree_builder.py`（新） | ~250 | 字体大小 k-means（k=3-5）+ Title label 优先 + 缩进推断 H1/H2/H3 |
| `app/parsing/quality/reading_order.py`（改） | +80 | 新增 "before fix" / "after fix" 双重指标，前端展示对比 |

**验证**：自建 50 篇多栏论文 + 30 份招股书，reading order 准确率从 baseline ~62% → target ≥ 88%（不需要 LayoutReader）。

---

### 4.4 P0-D：Quality Gate Pipeline——低信心 → Review Queue 闭环（用户 #7 + #8 联动）

**目标**：把已有的 quality 评分（1600 行栈）连到已有的 `/knowledge/quarantine` 隔离队列（2114 行），形成自动闭环——**纯 pipeline 编排，零新算法**。

```python
# app/parsing/processors/quality_gate.py（新，~250 行）
class QualityGate:
    """
    解析完成后强制经过此 Gate；决定 PASS / REVIEW / FAIL。

    判定规则（全部纯阈值，可配置）：
    - OCR avg confidence < 0.70 → REVIEW(reason="ocr_low_confidence")
    - 任一 table cell confidence < 0.60 → REVIEW(reason="table_low_confidence")
    - Reading order "before vs after fix" 差异 > 30% → REVIEW(reason="reading_order_unstable")
    - Section tree 异常（无 H1 / 单层）+ 总块数 > 50 → REVIEW(reason="section_tree_anomaly")
    - 解析失败但触发降级链最终成功 → REVIEW(reason="fallback_used")
    - parse_score < min_parse_score → REVIEW(reason="parse_score_low")
    """
```

**接入位置**：

| 位置 | 变更 |
|---|---|
| `app/api/v1/document_upload.py` | 解析完调 `QualityGate.evaluate(result)` → REVIEW 时进 `quarantine_queue` 表 |
| `app/api/v1/quarantine.py` | 新增 `parse_quality` 来源类别（与 output_guard / parse_risk / presidio_pii / acl_unclear / user_flag 并列第 6 类，对齐 `rag-quarantine-frontend-deep-dive` plan） |
| `web/app/knowledge/quarantine/page.tsx` | UI 增加 parse_quality 归因 + 一键跳转 Review UI |

**新增/改造**：

| 文件 | 行数 | 作用 |
|---|---|---|
| `app/parsing/processors/quality_gate.py` | ~250 | 主 gate |
| `app/parsing/processors/gate_config.py` | ~60 | 阈值配置 |
| `app/api/v1/quarantine.py`（改） | +40 | 新增 parse_quality 类别 |
| 前端 `quarantine/page.tsx`（改） | +80 | 第 6 类 UI |

---

### 4.5 P0-E：Review UI——人工校正闭环（用户 #8，工程 + Pipeline）

**最有产品价值的一项**——用户清单原文："企业场景里**可校正**往往比**一次解析完美**更重要"。

**前端**：在 `/parsing` 工作台增加 Review 子路由 `/parsing/review/[doc_id]`。

| UI 组件 | 用途 | 实现成本 |
|---|---|---|
| 左 PDF / 右 chunk 对照 | 主对照视图 | 已有 PDF.js viewer，复用 |
| bbox 高亮联动 | 点 chunk → PDF 高亮原区域 | 已有 bbox 数据，~150 行 |
| 表格 HTML 编辑器 | 修 row/col/header/merged cell | 自建 contenteditable，~300 行 |
| Reading order 拖拉排序 | 多栏错序手修 | `@dnd-kit/core` 已用，~150 行 |
| Caption ↔ figure 绑定 | 手动连接 | 选择 + 连线 SVG，~200 行 |
| 低信心项过滤 | 只看风险区 | `quality.confidence < 0.7` filter，~50 行 |
| 校正回写 | 修正后入库（重新发布到 dataset） | API + state，~150 行 |
| 校正样本导出 | 沉淀为训练样本（未来 fine-tune） | JSON 导出，~100 行 |

**后端 API**：

```python
# app/api/v1/parsing_review.py（新，~400 行）
@router.get("/parsing/{doc_id}/review")
async def get_review_payload(doc_id: str):
    """返回 PDF URL + blocks + tables + figures + bbox + confidence + decision_log"""

@router.put("/parsing/{doc_id}/corrections")
async def save_corrections(doc_id: str, corrections: CorrectionPayload):
    """保存表格 cell 修正 / reading order 重排 / caption 重绑"""

@router.post("/parsing/{doc_id}/republish")
async def republish_after_review(doc_id: str):
    """校正后重新生成 chunk + embedding 入 dataset"""

@router.get("/parsing/corrections/export")
async def export_correction_samples(start_date: str, end_date: str):
    """导出校正样本为训练数据（每条含原始 + 修正 + bbox）"""
```

**新增**：

| 文件 | 行数 | 作用 |
|---|---|---|
| `app/api/v1/parsing_review.py` | ~400 | 后端 API |
| `app/services/parsing_review_service.py` | ~300 | 校正回写 + republish 逻辑 |
| `app/models/parsing_correction.py` | ~80 | 校正记录表 |
| `web/app/parsing/review/[doc_id]/page.tsx` | ~600 | 主路由 |
| `web/components/parsing/review/*` | ~800 | 组件（PDFOverlay / TableEditor / ReorderList / CaptionLinker） |

**总计** ~2200 行（后端 ~800 + 前端 ~1400），1.5-2 周。

---

## 5 P1：3 件 pipeline 闭环 + 规则化后处理（零模型）

### 5.1 P1-A：Layout-aware chunking 覆盖度补完（用户 #6）

MimirQ 现有 70+ 切块策略，但用户清单 #6 明确的 6 类 layout-aware chunk **是否全覆盖待核**。

| 用户要求 | MimirQ 覆盖 | 补救 |
|---|---|---|
| Title + paragraphs → 章节 chunk | ⚠️ 部分 | 用 P0-C section_tree → `section_chunk_strategy.py` |
| Table caption + table → 表格 chunk | ⚠️ 部分 | 用 P0-B TableExtraction → `table_chunk_strategy.py` |
| Figure caption + figure OCR → 图片 chunk | ❓ 需核 | 用 P0-C caption_linker → `figure_chunk_strategy.py` |
| Equation + explanation → 公式 chunk | ❌ | P2 引入公式 LaTeX 后再做 |
| 跨页连续段落合并 | ⚠️ | P0-C reading_order_fixer 已 cover |
| Parent-child chunk + bbox tracking | ⚠️ | 与 `rag-context-expansion-rerank` plan 联动 |

**预估**：4 个新策略文件 + 测试 ~600 行，1 周。**全部基于 P0 输出**，零新算法。

---

### 5.2 P1-B：中文 / 繁中专项（用户 #9，纯规则）

**重点 5 项**，全部纯规则 / 词典：

| 功能 | 实现方式 | 行数 | 依赖 |
|---|---|---|---|
| 繁简正规化（可选） | `opencc-python` 包装 | ~50 | opencc |
| 中英混排 token 边界 | jieba（已用）+ 英文 regex 边界 | ~150 | 无新依赖 |
| 全形 / 半形统一 | Unicode 字符映射表（~150 个映射） | ~80 | 无 |
| 中文 OCR 错字修复 | 词典 + LLM correction（fallback） | ~250 | 已有 LLM |
| 专有名词词典 | 接入 `industry_rules` 术语映射 | ~100 | 已有 |

**新增**：`app/parsing/enrich/zh_postprocess.py` ~600 行。**与 `industry-rules-productization` plan 共享词典 schema**。

---

### 5.3 P1-C：性能 Pipeline 工程化（用户 #10）

**已有**：subprocess_runner + 页级并行。

**待补**（**全部工程，零算法**）：

| 优化 | 实现 | 行数 |
|---|---|---|
| 文档预分类（pre_poc_scanner 接入） | 已存在 → 接入 routing | ~100 |
| 模型预热（vision OCR/TSR） | 服务启动时加载 + 触发一次 inference | ~80 |
| 结果缓存（文件 hash） | Redis / Disk LRU | ~150 |
| 增量解析（小改重跑） | 比对 bbox / 文本 hash → 只重跑变化页 | ~300 |
| 超大 PDF 分段（>500 页） | 每 50 页 1 个 job + 队列 | ~200 |
| 解析超时降级 | 已有 P0-A fallback chain 覆盖 | 0 |
| 成本统计 | OTel span + per-doc/page/GPU 时间 | ~150 |

**总计** ~1000 行，2-3 周。**纯工程，零模型，零算法**。

---

## 6 P2：3 件可选（仅 1 件必引入唯一一个极小模型）

### 6.1 P2-A：公式 → LaTeX（用户 #5，**仅此一项必须用模型**）

**前提**：客户明确询问需要公式 QA 时再启动。

**模型选择策略**：

| 候选 | 参数量 | 优缺点 | 选用条件 |
|---|---|---|---|
| **Texo (2026)** | **20M** | 极小，CPU/边缘可跑，token accuracy 接近 UniMERNet-T | **默认**（边缘 / 私有化部署） |
| pix2text-mfr | ~80M | TrOCR 架构，中文友好 | 中文公式场景 |
| pix2tex（lukas-blecher） | ~50M | 经典基线，im2latex BLEU 88% | 备选 |
| ~~nougat-latex-base 250M~~ | 250M | 准确率高但太重 | **不用**（违反"轻量"原则） |

**实现（仅做包装，不引重模型）**：

```python
# app/parsing/enrich/formula_to_latex.py（P2 才新增，~250 行）
class FormulaToLatexPipeline:
    def __init__(self, engine: Literal["texo", "pix2text-mfr", "pix2tex"] = "texo"):
        self.model = self._load_lazy(engine)  # 懒加载

    async def extract(self, equation_patches: list[ImagePatch]) -> list[FormulaResult]:
        latex_list = await self.model.batch_predict(equation_patches)
        return [validate_latex(x) for x in latex_list]  # latex_validator 兜底
```

**新增**：`app/parsing/enrich/formula_to_latex.py` + `latex_validator.py` ~350 行，启动条件**严格**：客户场景 + 至少 1 个付费 PoC。

---

### 6.2 P2-B：流程图 / 架构图 graph extraction（用户 #4，**VLM zero-shot，不自训**）

**不自训**——直接用已有 LLM 路径调 VLM（Qwen2-VL / GPT-4o-mini / Claude 3.5 Sonnet Vision），prompt 输出严格 JSON：

```python
# app/parsing/enrich/diagram_to_graph.py（P2，~400 行）
async def extract_diagram_graph(img: bytes, type_hint: str = "auto") -> DiagramGraph:
    """
    Prompt: '识别这张图的类型（流程图/架构图/组织图/时序图/SOP）+ 提取节点和边，
            输出严格 JSON {"type":..., "nodes":[...], "edges":[...]}'
    """
```

**触发条件**：layout_recognizer 检出 Figure + caption 含关键词（"流程"/"架构"/"组织"/"时序"/"SOP"）→ 进入 enrich 队列。

**启动条件**：客户场景明确 + VLM 已接入（多数已有）。**不预先全栈布局**。

---

### 6.3 P2-C：Domain Post-Processor（用户 #5 高级部分）

针对 4 类 domain 做规则化 post-processor：

```
app/parsing/enrich/domain/
  legal_processor.py        条款编号正则 + 定义抽取 + 义务/责任/期限关键词
  financial_processor.py    报表 / 注释 / 口径 / 期间对齐（与 cn-finance benchmark 联动）
  patent_processor.py       claim tree 编号规则 + 附图说明 + 实施例
  medical_processor.py      指标 / 剂量 / 禁忌 / 证据等级词典
```

**全部纯规则 + 词典**，与 `industry-rules-productization` plan 共享。

**启动条件**：对应行业客户付费 PoC 启动。

---

## 7 落地里程碑（4-7 周，全 pipeline）

### Phase 1：P0 核心（Week 1-4）

| Week | 任务 | 产出 | 模型 |
|---|---|---|---|
| W1 | P0-A Parser Fallback Pipeline + decision log | `processors/parser_fallback_pipeline.py` + 前端可视化 | 无 |
| W1-2 | P0-B 表格 Pipeline（Schema + Markdown/HTML + 跨页合并 + confidence） | 4 个 enrich 模块 | 无 |
| W2-3 | P0-C Reading Order Fix（多栏 + 页眉页脚 + caption + section tree） | 4 个 enrich 模块 | 无 |
| W3 | P0-D Quality Gate → 隔离队列闭环 | `processors/quality_gate.py` + 队列接入 | 无 |
| W4 | P0-E Review UI 后端 API + 前端 MVP（表格编辑 + 拖拉重排 + bbox 高亮） | `api/v1/parsing_review.py` + `web/app/parsing/review/[doc_id]/` | 无 |

### Phase 2：P1（Week 5-7）

| Week | 任务 | 产出 | 模型 |
|---|---|---|---|
| W5 | P1-A Layout-aware chunking 4 类策略补完 | 4 个 strategy 文件 | 无 |
| W5-6 | P1-B 中文 / 繁中专项（5 项纯规则） | `zh_postprocess.py` | 无 |
| W6-7 | P1-C 性能 Pipeline（预热 + 缓存 + 增量 + 大 PDF 分段 + 成本统计） | 5 个工程模块 | 无 |

### Phase 3：P2（视客户拉力，按需进入）

- **不预先全栈布局**——只在客户场景明确 + 付费意向时启动
- Texo 公式 / VLM 流程图 / Domain processor 各自独立启动

**全程总览**：P0 + P1 = **零新模型，全部 pipeline / 规则 / 工程**；总代码 ~5500 行，6-7 周。

---

## 8 决策门槛与陷阱清单

### 8.1 决策门槛

| 决策点 | 通过标准 | 否则 |
|---|---|---|
| P0 启动 | 至少 1 个客户场景被表格 / reading order 阻塞 | 推迟 |
| P0-A fallback chain | 单 backend 跑通率 ≥ 80% + 降级链生效率 ≥ 90% | 调阈值 |
| P0-B 跨页表合并 | 自建 50 表测试集合并准确率 ≥ 90% | 收紧匹配规则 |
| P0-C reading order | 50 篇多栏论文 + 30 招股书准确率 ≥ 88%（vs baseline ~62%） | 加 layoutreader 模型 fallback（仅此情况） |
| P0-E Review UI | 至少 1 个 PoC 客户业务专家能演示自助修正 | 推迟 |
| P2 公式启动 | 至少 1 个付费 PoC 客户要求 | 推迟 |
| P2 流程图启动 | 客户场景明确 + 现有 VLM 可用 | 推迟 |

### 8.2 陷阱清单（**特别强调"避免又被模型诱惑"**）

| # | 陷阱 | 后果 | 规避 |
|---|---|---|---|
| 1 | **看到 HF 上某个模型很厉害就集成** | 维护成本爆炸、不可移植、可解释丢失 | **必须先问"能不能用规则替代"**；3 条铁律必须背 |
| 2 | 跨页表合并算法太激进 | 把不相干表合一起 | 严格匹配 4-5 条 heuristic，宁可漏不可错 |
| 3 | Reading Order 修复破坏原有正确顺序 | 准确率倒退 | **强制 "before fix" vs "after fix" 双指标**，倒退立刻回滚 |
| 4 | Review UI 做成大而全 | 永远做不完 | 严格 MVP：只支持表格修 + reading order 拖拉 + caption 绑定 3 件套 |
| 5 | Quality Gate 阈值过严 | review queue 爆满，客户骂 | 默认宽松阈值 + 客户可调 |
| 6 | 中文 OCR 错字修复全用 LLM | 成本爆 | 词典优先 95% + LLM 兜底 5% |
| 7 | 增量解析判定不准 | 重跑全文档 | 必须 bbox-level hash 比对 |
| 8 | 性能优化和 P0 并行 | 互相干扰 | P0 完成后再启动 P1-C |
| 9 | 把 P0-A 的 fallback chain 写死成串行 | 每次都跑遍所有 backend = 巨慢 | 用 quality 信号触发，单 backend 跑通 90% 文档 |
| 10 | **看到客户问表格 QA 就上 nougat** | 250M 模型上线后 GPU 显存爆 | P0-B 纯规则方案 + cell confidence 过滤已能解决 80% |
| 11 | Review UI 校正不沉淀 | 错失训练样本机会 | `parsing_correction` 表必须有，未来可导出 |
| 12 | section tree 全靠字体大小 | 表格 caption / 图注被误识别为标题 | 字体 + Title label + 缩进 + 关键词四信号融合 |

---

## 9 范围之外 + 与其他 plan 的边界

### 9.1 不在本 plan 范围

- **DeepDoc 模型层 fine-tune** — 数据不足；等 Review UI 沉淀 ≥ 5000 校正样本后再单独立项
- **整套 RAGFlow 升级合并** — fork 后已分叉，不做上游同步
- **第三方 SaaS API 整合**（Reducto / Mistral OCR / Mathpix）— 已在 `app/parsing/parsers/` 列入，不重复
- **多模态 ColPali / video** — 与 `rag-deep-research` P2 重合
- **对外 SaaS API + 计费 + SDK** — 在 `deepdoc-api-productization-2026-q3.md`
- **大幅引入 HF 重模型** — 违反本 plan 三条铁律

### 9.2 与其他 plan 的边界

| Plan | 边界 |
|---|---|
| `deepdoc-api-productization-2026-q3.md` | **本 plan 给能力 → 那 plan 给商品**：本 plan 让 deepdoc 输出从"原始"变"可用"；那 plan 把它包成对外 SaaS endpoint + SDK + 计费 |
| `rag-parsing-chunking-deep-dive-2026-q2.md` | **那 plan 给评测标尺**：用 OmniDocBench / parse_bench 验证本 plan P0 |
| `rag-parsing-frontend-deep-dive-2026-q2.md` | **那 plan 给前端基础**：解析对比 grid / 质量评分面板；本 plan P0-E Review UI 在其上扩展 |
| `rag-quarantine-frontend-deep-dive-2026-q2.md` | **那 plan 给隔离队列前端**：本 plan P0-D Quality Gate 触发后进那个队列 |
| `industry-rules-productization-2026-q2.md` | **那 plan 给术语词典**：本 plan P1-B 中文专项 + P2-C domain processor 共享 |
| `rag-compliance-automation-2026-q3.md` | **那 plan 给法规层 KG**：本 plan P2-C legal processor 给那 plan 输出条款级 parser |

---

## 附录 A：核心算法伪代码（全部纯几何/规则，零模型）

### A.1 多栏检测 + 排序

```python
def detect_columns_and_sort(page_blocks: list[Block]) -> list[Block]:
    if len(page_blocks) <= 3:
        return sorted(page_blocks, key=lambda b: b.bbox.y_min)

    x_centers = [(b.bbox.x_min + b.bbox.x_max) / 2 for b in page_blocks]
    # k-means k in [1,2,3]，取 silhouette 最高者
    best_k, labels = best_kmeans(x_centers, k_range=range(1, 4))

    if best_k == 1:
        return sorted(page_blocks, key=lambda b: b.bbox.y_min)

    columns = defaultdict(list)
    for block, label in zip(page_blocks, labels):
        columns[label].append(block)

    # 按列的 x 中心排序，每列内按 y 排序
    sorted_cols = sorted(columns.items(), key=lambda kv: mean(b.bbox.x_min for b in kv[1]))
    out = []
    for _, col_blocks in sorted_cols:
        out.extend(sorted(col_blocks, key=lambda b: b.bbox.y_min))
    return out
```

### A.2 跨页表合并判定

```python
def is_same_table_cross_page(t1: TableExtraction, t2: TableExtraction, page_h: float, page_w: float) -> bool:
    if t1.cols != t2.cols:
        return False

    # 列对齐：每列 x 中心差 < 5% 页宽
    cols1 = [c.bbox.x_center for c in t1.cells if c.row == 0]
    cols2 = [c.bbox.x_center for c in t2.cells if c.row == 0]
    if max(abs(a - b) for a, b in zip(cols1, cols2)) > 0.05 * page_w:
        return False

    # 上页表贴页底 + 下页表贴页顶
    if (page_h - t1.cells[-1].bbox.y_max) > 0.10 * page_h: return False
    if t2.cells[0].bbox.y_min > 0.10 * page_h: return False

    # 续表关键词 OR 下页第一行非 header
    if "续表" in (t1.caption or "") or "continued" in (t1.caption or "").lower():
        return True
    if not any(h in (t2.cells[0].text or "") for h in HEADER_KEYWORDS):
        return True
    return False
```

### A.3 Caption 绑定

```python
def link_captions(figures: list[Figure], tables: list[Table], captions: list[CaptionBlock]) -> list[Link]:
    links = []
    for cap in captions:
        # 关键词识别（图/表）
        kind = detect_caption_kind(cap.text)  # 'figure' / 'table' / None
        if not kind: continue

        candidates = figures if kind == 'figure' else tables
        # 距离 + 同页 + 字体相近
        nearest = min(
            candidates,
            key=lambda f: bbox_distance(cap.bbox, f.bbox) if f.page == cap.page else float('inf')
        )
        if bbox_distance(cap.bbox, nearest.bbox) < 50:  # px
            links.append(Link(caption=cap.id, target=nearest.id, kind=kind))
    return links
```

### A.4 Section Tree 构建

```python
def build_section_tree(blocks: list[Block]) -> SectionNode:
    title_blocks = [b for b in blocks if b.label == 'Title']
    if not title_blocks:
        return SectionNode(level=0, blocks=blocks)

    # 按字体大小聚类（k=3-5）
    sizes = [b.font_size for b in title_blocks]
    levels = kmeans_levels(sizes, k=min(5, len(set(sizes))))

    # 构建嵌套
    root = SectionNode(level=0)
    stack = [root]
    for b, lv in zip(title_blocks, levels):
        node = SectionNode(level=lv, title=b.text, blocks=[])
        while stack and stack[-1].level >= lv:
            stack.pop()
        stack[-1].children.append(node)
        stack.append(node)
    return root
```

---

## 附录 B：现状 vs P0+P1 完成后对比

| 维度 | 现状 | P0+P1 完成后 |
|---|---|---|
| 表格 | TSR 输出文字化句子 | JSON Schema + Markdown/HTML/CSV + 跨页合并 + cell confidence |
| Reading Order | 仅评估对错 | 多栏修复 + 页眉页脚清除 + caption 绑定 + section tree（**纯几何**） |
| 公式 | 仅识别为 Equation 区域 | （P2 可选）极小模型 Texo |
| Parser 失败 | 静默或 routing 一次性选 | 失败降级链 + 决策日志 + 前端可视化 |
| Quality 评分 | 1600 行栈未连闭环 | Quality Gate → 隔离队列 → Review UI 闭环 |
| 人工修正 | 无 | bbox 高亮 / 表格编辑 / 拖拉排序 / 校正回写 |
| 中文支持 | OCR 中英；其他通用 | 繁简 / 全半形 / 中英混排 / 错字修复 / 行业词典（**纯规则**） |
| 性能 | 页级并行 | + 预热 / 缓存 / 增量 / 大 PDF 分段 / 成本统计 |
| **模型负担** | vision 3770 行已就位 | **不变**（P0 + P1 零新模型） |

---

## 附录 C：交付物清单（验收用）

### P0 交付（Week 1-4 完成）

- [ ] `app/parsing/processors/parser_fallback_pipeline.py` + decision log
- [ ] `app/parsing/output/table_schema.py` Pydantic schema
- [ ] `app/parsing/enrich/` 下 8 个新模块：
  - table_to_markdown / cross_page_table_merger / table_confidence
  - reading_order_fixer / header_footer_remover / caption_linker / section_tree_builder
- [ ] `app/parsing/processors/quality_gate.py` + 隔离队列接入
- [ ] `app/api/v1/parsing_review.py` + 校正回写
- [ ] `web/app/parsing/review/[doc_id]/page.tsx` + 4 个组件
- [ ] 跨页表合并准确率报告（≥ 90%）
- [ ] Reading order 修复准确率报告（≥ 88% vs baseline 62%）
- [ ] Quality Gate 触发率 + review 通过率统计

### P1 交付（Week 5-7 完成）

- [ ] 4 个 layout-aware chunking 策略文件
- [ ] `app/parsing/enrich/zh_postprocess.py`（5 项中文规则）
- [ ] 性能优化 5 个工程模块（预热 / 缓存 / 增量 / 分段 / 成本统计）
- [ ] OTel span 覆盖率（解析 → enrich → chunking → Gate 全程）

### P2 启动条件（按需）

- [ ] 公式：客户付费 PoC + 加 Texo 20M 模型
- [ ] 流程图：客户场景明确 + VLM 已接入
- [ ] Domain：行业客户付费 PoC

---

## 参考资料

- [RAGFlow DeepDoc README](https://github.com/infiniflow/ragflow/blob/main/deepdoc/README.md)
- [RAGFlow Select PDF Parser](https://ragflow.io/docs/select_pdf_parser)
- [RAGFlow Accelerate Indexing](https://ragflow.io/docs/accelerate_doc_indexing)
- [DeepDoc 表格/流程图限制 Discussion](https://github.com/orgs/infiniflow/discussions/11473)
- [DeepDoc garbled output issue](https://github.com/infiniflow/ragflow/issues/13366)
- 仅 P2 引用 → [Texo (arXiv 2026, 20M)](https://arxiv.org/html/2602.17189v1)

> **唯一被本 plan 认可的 HF 模型只有 Texo（20M）**，且在 P2 才启动。其他所有 HF 模型集成方案（TATR / LayoutLMv3 / nougat-latex / SLANet 等）**全部排除**——违反"先 pipeline 后模型"铁律。
