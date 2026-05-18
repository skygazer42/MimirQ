# DeepDoc Pipeline 二次开发 — 具体实施计划（2026 Q2）

> 上一份 `deepdoc-secondary-development-2026-q2-q3.md` 定方向；本份是**文件级 / 函数级 / Day 级**的可执行实施手册。**严格遵循"先 pipeline 后模型 / 先规则后训练"铁律**。
>
> 创建日期：2026-05-18
> 来源：`deepdoc-secondary-development-2026-q2-q3.md` 第 4-7 章 P0/P1
> 关键发现（**核查后更新**）：`processors/cross_page_merge.py` 530 行 + `enrich/formula_ocr.py` 403 行 + `enrich/table_markdown.py` 71 行 + `processor.py` 5569 行 8-Stage 流水线 **已存在**——本实施计划主要是"**在现有 9000+ 行基础上做精准增量**"，不是从零写。
>
> 关联：
> - `plans/deepdoc-secondary-development-2026-q2-q3.md`（方向 plan）
> - `plans/rag-parsing-frontend-deep-dive-2026-q2.md`（前端工作台扩展）
> - `plans/rag-quarantine-frontend-deep-dive-2026-q2.md`（隔离队列接入）

---

## 0 现状基线（实施前必读）

### 0.1 已有 Stage 流水线（`processor.py` 5569 行）

```python
DocumentProcessorService 主流程：
  ParsingStage (668)         # backend 选 + 解析
    → InlineAssetStage (993)  # figure/table/equation 后置 enrich（已挂 vlm/ocr/seal/chart/formula）
    → GovernanceStage (1203)  # output guard / 敏感信息
    → NormalizeStage (1217)   # 文本归一
    → ChunkingStage (1252)    # 70+ 策略
    → ChunkDedupStage (1378)  # 切片去重
    → ChunkAssetStage (1421)  # 切片资产关联
    → IndexStage (1734)       # 入向量库
```

**关键点**：本实施计划**不重写主流程**，只**在 Stage 之间插入新算子**（reading_order_fixer / header_footer_remover / section_tree / quality_gate）+ 扩充薄模块（table_markdown 71 → ~270 行）。

### 0.2 已有 enrich 模块（11 个，~3300 行）

| 模块 | 行数 | 用途 | 本计划如何动 |
|---|---|---|---|
| `cross_page_merge.py` (processors/) | 530 | 表格 + 列表跨页合并 | **不动**（已覆盖 P0-B 主要场景） |
| `formula_ocr.py` | 403 | 公式 OCR（含 audit + HTTP backend） | **P2 才扩**（默认禁用） |
| `table_markdown.py` | 71 | OCR 文本 → markdown | **扩到 ~270 行**（接 TSR cells） |
| `chart_to_data.py` | 363 | 图表 → 数据 | 不动 |
| `formula_ocr.py` audit | 含在 403 内 | 公式审计 | 不动 |
| `image_understanding.py` | 506 | VLM 图像理解 | 不动 |
| `vlm_image_caption.py` | 416 | VLM caption | 不动 |
| `image_caption.py` | 189 | caption | 不动 |
| `image_ocr.py` | 161 | 图像 OCR | 不动 |
| `image_code.py` | 274 | 代码图片 | 不动 |
| `seal_recognition.py` | 431 | 印章 | 不动 |
| `ocr_redaction.py` | 51 | OCR 脱敏 | 不动 |

### 0.3 已有 quality 模块（8 个，~1606 行）

| 模块 | 行数 | 用途 | 本计划如何动 |
|---|---|---|---|
| `scorer.py` | 349 | 综合评分 | **+50 行**接入新维度 |
| `reading_order.py` | 444 | 评估 | **+80 行**双指标（before/after） |
| `grits.py` | 117 | GriTS 表格评分 | 不动 |
| `benchmark.py` | 230 | benchmark runner | 不动 |
| `ocr_validator.py` | 124 | OCR 置信度 | 不动 |
| `competition.py` | 149 | backend 横评 | 不动 |
| `document_quality.py` | 126 | 文档质量 | 不动 |
| `text_quality.py` | 67 | 文本质量 | 不动 |

### 0.4 已有 routing/factory（~700 行）

| 模块 | 行数 | 用途 | 本计划如何动 |
|---|---|---|---|
| `routing.py` | (~150) | 选 backend | **+100 行**加 decision log |
| `factory.py` | (~600) | 工厂 | 不动 |
| `subprocess_runner.py` / `subprocess_worker.py` | — | 页级并行 | 不动 |
| `diagnostics.py` | — | 解析诊断 | **+50 行**接 decision log |

### 0.5 真正"全新"的模块（要从零写）

| 模块 | 估算行数 | 优先级 |
|---|---|---|
| `enrich/reading_order_fixer.py` | ~450 | P0 |
| `enrich/header_footer_remover.py` | ~150 | P0 |
| `enrich/caption_linker.py` | ~200 | P0 |
| `enrich/section_tree_builder.py` | ~250 | P0 |
| `output/table_schema.py` (Pydantic) | ~180 | P0 |
| `processors/quality_gate.py` | ~250 | P0 |
| `processors/parser_fallback_orchestrator.py` | ~350 | P0 |
| `processors/parse_decision_log.py` | ~150 | P0 |
| `api/v1/parsing_review.py` | ~400 | P0 |
| `services/parsing_review_service.py` | ~300 | P0 |
| `models/parsing_correction.py` | ~80 | P0 |
| `enrich/zh_postprocess.py` | ~600 | P1 |
| `processors/parse_warmup.py` | ~80 | P1 |
| `processors/incremental_parse.py` | ~300 | P1 |

**新增代码总量约 3740 行**；改造现有代码约 350 行。**P0 + P1 总计 ~4100 行**，6-7 周可完成。

---

## 1 任务分解：18 个具体 Task

### Task 0：搭建基线测试集（Day 1，必须先做）

**目的**：所有 P0 验收都要量化对照基线，必须先固定测试集。

**子任务**：

| 子任务 | 产出 | 工期 |
|---|---|---|
| 收集 50 篇中文学术论文（多栏） | `tests/parse_bench/zh-papers/*.pdf` | 0.5d |
| 收集 30 份招股书 / 年报（跨页表多） | `tests/parse_bench/cn-finance/*.pdf` | 0.5d |
| 标注 reading order GT（人工，每篇 10-20 块顺序） | `tests/parse_bench/zh-papers/_gt.jsonl` | 1d（可外包） |
| 标注跨页表 GT（每份 5-10 张表的合并状态） | `tests/parse_bench/cn-finance/_gt.jsonl` | 1d |
| 跑 baseline benchmark 出基线分 | `tests/parse_bench/_baseline_2026_05_18.json` | 0.5d |

**预期 baseline**：
- Reading order accuracy：~62%（仅评估，没修复）
- 跨页表合并准确率：现有 `cross_page_merge.py` ~75%
- Section tree 深度合理性：未测

**验收**：基线 JSON + 测试集 README 写明每张文档的 GT 关键点。

---

### Task 1：Reading Order Fixer（P0-C 主体，Day 2-5）

**新建文件**：`app/parsing/enrich/reading_order_fixer.py` ~450 行

**核心 API**：

```python
# app/parsing/enrich/reading_order_fixer.py

@dataclass
class LayoutBlock:
    bbox: tuple[float, float, float, float]   # x_min, y_min, x_max, y_max
    page: int
    page_size: tuple[float, float]            # page_w, page_h
    label: str                                 # Text/Title/Figure/Table/Header/Footer/...
    text: str
    font_size: float | None = None
    confidence: float = 1.0

def fix_reading_order(blocks: list[LayoutBlock]) -> tuple[list[LayoutBlock], dict]:
    """
    返回：(reordered_blocks, diagnosis)
    diagnosis = {
      "columns_per_page": {1: 2, 2: 1, ...},
      "header_footer_removed_count": 12,
      "merged_paragraphs": 8,
      "stability_score": 0.85,  # before vs after 相似度
    }
    """

def _detect_columns(page_blocks: list[LayoutBlock]) -> int:
    """k-means clustering on bbox.x_center, k in [1,2,3], silhouette 选最优"""

def _sort_in_columns(page_blocks: list[LayoutBlock], k: int) -> list[LayoutBlock]:
    """单栏按 y 升序；多栏每栏内 y 升序 → 栏间 x 升序拼接"""

def _merge_cross_page_paragraphs(blocks: list[LayoutBlock]) -> list[LayoutBlock]:
    """4 条 heuristic：
       - 上页 last.y_max 距页底 < 5% 页高
       - 下页 first.y_min 距页顶 < 5% 页高
       - 字体大小相同（±1pt）
       - 上页 last 末尾无句号
    """
```

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 2 上午 | `LayoutBlock` dataclass + `_detect_columns` (k-means + silhouette) |
| Day 2 下午 | `_sort_in_columns` + 单栏 / 双栏单测 |
| Day 3 上午 | `_merge_cross_page_paragraphs` 4 条 heuristic |
| Day 3 下午 | 接入 `processor.py` ParsingStage 后置 hook |
| Day 4 | 跑 50 篇论文，调阈值（栏间 gap / 跨页 y 阈值 / 字体容差） |
| Day 5 | 写单测 ≥ 20 个 + 接入 quality/reading_order.py 双指标 |

**依赖**：
- `sklearn.cluster.KMeans` + `silhouette_score`（项目已有 sklearn）
- 现有 `quality/reading_order.py` 评估函数（用于回归对照）

**验收**：reading order accuracy **62% → ≥ 88%**；before/after stability score 全部 > 0.7（无破坏性重排）。

---

### Task 2：Header/Footer Remover（P0-C 配套，Day 6）

**新建**：`app/parsing/enrich/header_footer_remover.py` ~150 行

**核心 API**：

```python
def detect_and_remove_header_footer(
    blocks: list[LayoutBlock],
    *,
    min_pages: int = 3,        # 至少在 3 页出现
    similarity_threshold: float = 0.9,
    position_band: float = 0.1, # 相对页高 < 10% 或 > 90%
) -> tuple[list[LayoutBlock], dict]:
    """
    Step 1: 按 (text_normalized, page_position_band) 分组
    Step 2: 同一文本在 ≥ min_pages 个不同 page 同一 band 出现 → 标记
    Step 3: 剔除并记录
    """
```

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 6 上午 | 文本归一 + position_band 计算 + 跨页分组 |
| Day 6 下午 | 阈值调试 + 在 50 篇论文上验证不误删正文 |

**验收**：误删正文率 < 1%（标 GT 100 块）；跨页重复 header/footer 召回率 ≥ 95%。

---

### Task 3：Caption Linker（P0-C 配套，Day 7-8）

**新建**：`app/parsing/enrich/caption_linker.py` ~200 行

**核心 API**：

```python
CAPTION_PATTERN = re.compile(r"^(图|表|图表|Fig\.?|Tab\.?|Table|Figure)\s*\d+", re.IGNORECASE)

def link_captions_to_targets(
    blocks: list[LayoutBlock],
    *,
    max_distance_px: float = 50.0,
    font_size_delta: float = 2.0,
) -> list[CaptionLink]:
    """
    Step 1: 用 CAPTION_PATTERN 识别 caption 候选 + 类型（figure/table）
    Step 2: 同页找最近的 Figure/Table（bbox 距离）
    Step 3: 字体小于正文 1-2pt 加分
    Step 4: 输出 link 列表 + confidence
    """

@dataclass
class CaptionLink:
    caption_block_id: str
    target_block_id: str
    kind: Literal["figure", "table"]
    distance_px: float
    confidence: float  # 综合距离 + 关键词 + 字体
```

**验收**：50 篇论文 + 30 份招股书，caption 绑定准确率 ≥ 90%。

---

### Task 4：Section Tree Builder（P0-C 配套，Day 9-10）

**新建**：`app/parsing/enrich/section_tree_builder.py` ~250 行

**核心 API**：

```python
@dataclass
class SectionNode:
    level: int  # 0 = root, 1 = H1, 2 = H2, ...
    title: str | None
    blocks: list[LayoutBlock]
    children: list["SectionNode"]
    span: tuple[int, int]  # 起止 block index

def build_section_tree(
    blocks: list[LayoutBlock],
    *,
    max_levels: int = 5,
) -> SectionNode:
    """
    Step 1: 找所有 label == 'Title' 的 block
    Step 2: 字体大小 k-means，k = min(5, unique_sizes)
    Step 3: 大字体 → 高级别（H1）
    Step 4: 配合：编号正则（"第一章" / "1." / "1.1") 修正层级
    Step 5: 构建嵌套
    """

def detect_chapter_number(text: str) -> int | None:
    """支持：第一章 / 第 1 章 / 1. / 1.1 / 1.1.1 / Chapter 1 / 一、 / （一）"""
```

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 9 上午 | `detect_chapter_number` + 单测（中英 8 种编号格式） |
| Day 9 下午 | 字体 k-means + 层级映射 |
| Day 10 | 构建嵌套 + 在 50 篇论文验证（深度合理性 + H1 数量与目录对照） |

**验收**：H1 数量与人工标注目录吻合 ≥ 85%；总深度 ≥ 2 的文档比例 ≥ 80%。

---

### Task 5：Table Schema + Markdown/HTML/CSV 输出（P0-B 主体，Day 11-13）

**改造**：`app/parsing/enrich/table_markdown.py` 71 → ~270 行
**新建**：`app/parsing/output/table_schema.py` ~180 行

**Schema**：

```python
# app/parsing/output/table_schema.py
from pydantic import BaseModel
from typing import Literal

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
    confidence: float

class TableQuality(BaseModel):
    row_consistency: float    # 同行 y 中心 std
    col_consistency: float    # 同列 x 中心 std
    cell_completeness: float  # 非空 cell 比例
    overall: float

class TableExtraction(BaseModel):
    table_id: str
    page_start: int
    page_end: int
    rows: int
    cols: int
    cells: list[TableCell]
    caption: str | None
    representations: dict[Literal["markdown", "html", "csv"], str]
    quality: TableQuality
    parser: str
    merged_from: list[str] | None
```

**改造 `table_markdown.py`**：

```python
# 保留现有 markdown_table_from_ocr_text（71 行不动）
# 新增以下函数（~200 行）：

def from_tsr_cells(cells: list[dict]) -> TableExtraction:
    """从 vision/TSR.py 的输出 dict 构造 TableExtraction"""

def to_markdown(table: TableExtraction) -> str:
    """GFM table，含 rowspan/colspan 兼容（用 HTML 内联 fallback）"""

def to_html(table: TableExtraction) -> str:
    """完整 HTML table，含 rowspan/colspan"""

def to_csv(table: TableExtraction) -> str:
    """CSV 输出，spanning cell 展平"""

def compute_quality(cells: list[TableCell]) -> TableQuality:
    """row/col consistency from bbox std + completeness"""

def compute_cell_confidence(cell_dict: dict, ocr_conf: float) -> float:
    """confidence = 0.6 * ocr_conf + 0.2 * row_consistency + 0.2 * col_consistency"""
```

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 11 | `table_schema.py` Pydantic + `from_tsr_cells` + `compute_quality` |
| Day 12 | `to_markdown` / `to_html` / `to_csv` + 单测 |
| Day 13 | `processor.py` InlineAssetStage 接入新输出 + 30 份招股书验证 |

**验收**：50 张中文财报表 GriTS（用现有 `quality/grits.py`）≥ 0.85；3 种 representations 全部可解析回 TableExtraction。

---

### Task 6：跨页表 Cell-Level 合并增强（P0-B 配套，Day 14）

**改造**：`app/parsing/processors/cross_page_merge.py` 530 → ~620 行（**只 +90 行**，因主流程已存在）

**当前能力**：基于 metadata 的列数 + truncated 标记合并 markdown 文本块。
**新增**：在 cell-level 上合并 TableExtraction 对象 + bbox 列对齐严格判定。

```python
# 在现有 cross_page_merge.py 末尾追加：

def merge_cross_page_table_extractions(
    tables: list[TableExtraction],
    *,
    page_size: tuple[float, float],
    col_alignment_tolerance: float = 0.05,  # 5% 页宽
    edge_distance_ratio: float = 0.10,       # 距页底/顶 10% 内
) -> list[TableExtraction]:
    """
    在 TableExtraction 层面合并：
    1. cols 完全相等
    2. 上一页表最后一行 cell.bbox.y_max 距页底 < 10%
    3. 下一页表第一行 cell.bbox.y_min 距页顶 < 10%
    4. 每列 x 中心差 < 5% 页宽
    5. 续表关键词 OR 下页第一行非 header
    """
```

**验收**：30 份招股书跨页表合并准确率 **75% → ≥ 90%**。

---

### Task 7：Parser Fallback Orchestrator + Decision Log（P0-A，Day 15-17）

**新建**：
- `app/parsing/processors/parser_fallback_orchestrator.py` ~350 行
- `app/parsing/processors/parse_decision_log.py` ~150 行
- `app/parsing/processors/fallback_chain_config.py` ~80 行

**核心 API**：

```python
# parser_fallback_orchestrator.py
class ParserFallbackOrchestrator:
    def __init__(self, chain_config: FallbackChainConfig):
        self.chain = chain_config
        self.log = ParseDecisionLog()

    async def parse_with_fallback(
        self,
        file_path: Path,
        quality_hint: dict | None = None,
        requested_backend: str | None = None,
    ) -> tuple[ParseResult, ParseDecisionLog]:
        """
        1. 预检（pre_poc_scanner 输出）→ 主 backend
        2. 调用主 backend
        3. 跑 quality/scorer → grade + score
        4. 若 grade == 'fail' or score < threshold:
           - log.record(backend, reason, score, attempt)
           - 选下一 backend（按 chain.fallback_for(failed_backend, reason)）
           - 重试（max=2）
        5. 全链失败 → naive parser 兜底 + quality_gate REVIEW
        """

# parse_decision_log.py
@dataclass
class ParseDecisionEntry:
    timestamp: datetime
    backend: str
    grade: str
    score: float
    reason: str          # ocr_low / table_fail / timeout / ...
    elapsed_ms: int
    attempt: int

class ParseDecisionLog:
    entries: list[ParseDecisionEntry]
    final_backend: str
    final_grade: str
    total_attempts: int
    total_elapsed_ms: int

    def to_otel_attributes(self) -> dict: ...
    def to_review_payload(self) -> dict: ...
```

**fallback_chain_config.py**：

```yaml
# fallback_chain.yaml 默认配置
default:
  primary_selector: routing.choose_pdf_backend
  fallbacks:
    deepdoc:
      on_failure: [mineru, docling, naive]
      on_low_table_quality: [docling]
      on_low_ocr: [mineru]
    mineru:
      on_failure: [deepdoc, docling, naive]
    docling:
      on_failure: [deepdoc, naive]
  max_attempts: 3
```

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 15 | `parse_decision_log.py` 完整实现 + 单测 |
| Day 16 | `fallback_chain_config.py` YAML loader + `parser_fallback_orchestrator.py` 主流程 |
| Day 17 | 接入 `processor.py` ParsingStage + OTel span 注入 + 前端可视化 hook |

**验收**：单 backend 跑通率 ≥ 80%；降级链生效率 ≥ 90%；decision log 完整记录每次决策。

---

### Task 8：Quality Gate（P0-D，Day 18-19）

**新建**：
- `app/parsing/processors/quality_gate.py` ~250 行
- `app/parsing/processors/gate_config.py` ~60 行

**核心 API**：

```python
# quality_gate.py
class GateAction(Enum):
    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"

@dataclass
class GateDecision:
    action: GateAction
    reasons: list[str]    # ocr_low_confidence / table_low_confidence / reading_order_unstable / ...
    severity: Literal["low", "medium", "high"]
    review_payload: dict | None

class QualityGate:
    def __init__(self, config: GateConfig):
        self.config = config

    def evaluate(self, parse_result: ParseResult) -> GateDecision:
        reasons = []

        if parse_result.ocr_avg_confidence < self.config.ocr_threshold:  # 0.70
            reasons.append("ocr_low_confidence")

        for table in parse_result.tables:
            if any(c.confidence < self.config.cell_threshold for c in table.cells):  # 0.60
                reasons.append("table_low_confidence")
                break

        if parse_result.reading_order_diagnosis.stability_score < 0.7:
            reasons.append("reading_order_unstable")

        if not parse_result.section_tree.has_h1() and parse_result.total_blocks > 50:
            reasons.append("section_tree_anomaly")

        if parse_result.decision_log.total_attempts > 1:
            reasons.append("fallback_used")

        if parse_result.quality_score < self.config.score_threshold:
            reasons.append("parse_score_low")

        return self._build_decision(reasons, parse_result)
```

**接入位置**：
- `processor.py` 在 InlineAssetStage 之后、GovernanceStage 之前插入 QualityGate
- REVIEW 时不阻塞流水线，但产出 `review_payload` 并写入 `quarantine_queue` 表

**新增 schema**：

```python
# app/api/schemas/quarantine.py 已存在，仅在枚举里新增：
class QuarantineSource(str, Enum):
    OUTPUT_GUARD = "output_guard"
    PARSE_RISK = "parse_risk"
    PRESIDIO_PII = "presidio_pii"
    ACL_UNCLEAR = "acl_unclear"
    USER_FLAG = "user_flag"
    PARSE_QUALITY = "parse_quality"   # ← 新增
```

**前端**：`web/app/knowledge/quarantine/page.tsx` 在归因 filter 中新增 `parse_quality` 类别（+80 行）。

**验收**：Quality Gate 触发率 ≤ 20%（不能太敏感）；触发后人工 review 通过率 ≥ 70%（验证阈值合理）。

---

### Task 9：Review UI 后端（P0-E 后端，Day 20-22）

**新建**：
- `app/api/v1/parsing_review.py` ~400 行
- `app/services/parsing_review_service.py` ~300 行
- `app/models/parsing_correction.py` ~80 行
- `alembic/versions/xxxx_add_parsing_correction.py` ~50 行（迁移）

**API**：

```python
# app/api/v1/parsing_review.py
router = APIRouter(prefix="/parsing", tags=["parsing-review"])

@router.get("/{doc_id}/review")
async def get_review_payload(doc_id: str, ...) -> ReviewPayload:
    """
    返回：
    - pdf_url
    - blocks: list[LayoutBlock]（含 bbox + label + text + confidence）
    - tables: list[TableExtraction]
    - figures: list[Figure]
    - captions: list[CaptionLink]
    - section_tree: SectionNode
    - decision_log: ParseDecisionLog
    - gate_decision: GateDecision
    """

@router.put("/{doc_id}/corrections")
async def save_corrections(doc_id: str, payload: CorrectionPayload):
    """
    支持三类修正：
    - table_cell: {table_id, row, col, new_text, new_rowspan, new_colspan}
    - reading_order: {new_block_order: list[block_id]}
    - caption_link: {caption_id, target_id} 或 {caption_id, unlink: true}
    """

@router.post("/{doc_id}/republish")
async def republish_after_review(doc_id: str):
    """触发：根据校正后状态重新生成 chunk + embedding → 入 dataset"""

@router.get("/corrections/export")
async def export_correction_samples(
    start_date: str,
    end_date: str,
    format: Literal["jsonl", "csv"] = "jsonl",
):
    """导出校正样本（未来 fine-tune 用）"""
```

**Model**：

```python
# app/models/parsing_correction.py
class ParsingCorrection(Base):
    __tablename__ = "parsing_corrections"

    id: Mapped[str]
    doc_id: Mapped[str]
    tenant_id: Mapped[str]
    correction_type: Mapped[str]      # table_cell / reading_order / caption_link
    original_payload: Mapped[dict]     # 原始解析结果
    corrected_payload: Mapped[dict]    # 修正后
    operator_id: Mapped[str]
    operator_role: Mapped[str]
    created_at: Mapped[datetime]
```

**Service**：

```python
# app/services/parsing_review_service.py
class ParsingReviewService:
    async def load_review_payload(doc_id: str) -> ReviewPayload: ...
    async def save_correction(doc_id: str, payload: CorrectionPayload) -> None: ...
    async def republish(doc_id: str) -> RepublishResult:
        """
        1. 拉取最新解析结果 + corrections
        2. apply corrections（table cells / order / caption links）
        3. 重跑 ChunkingStage → ChunkAssetStage → IndexStage
        4. 更新 quarantine 表（移除该 doc 的 parse_quality 标记）
        """
```

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 20 | Model + migration + 基础 API（GET review） |
| Day 21 | PUT corrections + service apply 逻辑 |
| Day 22 | POST republish + 接入 ChunkingStage 重跑 + export 导出 |

**验收**：3 类校正全部可保存 + republish + 在 dataset 中检索能命中修正后内容。

---

### Task 10：Review UI 前端（P0-E 前端，Day 23-27）

**新建路由**：`web/app/parsing/review/[doc_id]/page.tsx` ~600 行

**新建组件**（`web/components/parsing/review/`）：

| 组件 | 行数 | 功能 |
|---|---|---|
| `PDFOverlay.tsx` | ~200 | PDF + bbox 高亮联动（复用项目 PDF.js viewer） |
| `BlockListPane.tsx` | ~150 | 右侧 chunk/block 列表，点击高亮 PDF |
| `TableCellEditor.tsx` | ~300 | 表格 cell contenteditable + 行列调整 |
| `ReorderList.tsx` | ~150 | @dnd-kit 拖拉排序 |
| `CaptionLinker.tsx` | ~200 | SVG 连线 caption↔figure/table |
| `ConfidenceFilter.tsx` | ~50 | 低信心项过滤 toolbar |
| `CorrectionToolbar.tsx` | ~80 | 保存 / 取消 / republish 按钮 |
| `DecisionLogTimeline.tsx` | ~120 | 显示 fallback 决策时间线 |

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 23 | 路由骨架 + `PDFOverlay` + `BlockListPane`（基础联动） |
| Day 24 | `TableCellEditor`（含 rowspan/colspan 编辑） |
| Day 25 | `ReorderList` + `CaptionLinker` SVG 连线 |
| Day 26 | `ConfidenceFilter` + `CorrectionToolbar` + 保存到后端 |
| Day 27 | `DecisionLogTimeline` + 测试全流程 + i18n |

**验收**：在 5 份测试文档上完整跑通：打开 → 高亮 → 编辑表格 → 拖拉重排 → 重绑 caption → 保存 → republish → 在 dataset 检索验证。

---

### Task 11：Routing Decision Log 接入前端（Day 28）

**改造**：
- `app/parsing/routing.py` +100 行（暴露选择原因）
- `app/parsing/diagnostics.py` +50 行（合并 decision log）
- 前端 `web/app/parsing/page-client.tsx` +100 行（展示 timeline）

**验收**：前端能看到每份文档的"主 backend → 失败原因 → 降级 backend → 成功"完整决策时间线。

---

### Task 12：layout-aware chunking 4 类策略（P1-A，Day 29-31）

**新建**：

| 文件 | 行数 | 策略 |
|---|---|---|
| `app/rag/chunking/strategies/section_aware.py` | ~150 | 基于 section_tree 切分章节 |
| `app/rag/chunking/strategies/table_chunk.py` | ~200 | TableExtraction → 1 chunk + markdown + 元数据 |
| `app/rag/chunking/strategies/figure_chunk.py` | ~150 | Figure + caption + OCR 文本 → 1 chunk |
| `app/rag/chunking/strategies/cross_page_paragraph.py` | ~100 | 利用 reading_order_fixer 的合并结果 |

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 29 | `section_aware` + `table_chunk` |
| Day 30 | `figure_chunk` + `cross_page_paragraph` |
| Day 31 | 注册到 strategy registry + 50 篇论文回归测试 |

**验收**：在测试集上，table chunk 单独召回率比通用切片 +20pt；section chunk 召回深度更准。

---

### Task 13：中文 / 繁中 post-process（P1-B，Day 32-34）

**新建**：`app/parsing/enrich/zh_postprocess.py` ~600 行

**子模块**：

```python
# 5 个独立函数 + 一个流水线主函数
def normalize_traditional_to_simplified(text: str) -> str:
    """opencc 包装；可配置保留繁体"""

def fix_chinese_english_mix_tokens(text: str) -> str:
    """jieba + 英文 regex 边界识别"""

def normalize_fullwidth_to_halfwidth(text: str, *, keep_chinese_punct: bool = True) -> str:
    """全形→半形字符映射表"""

def correct_ocr_typos_by_dict(text: str, *, dictionary: Mapping[str, str]) -> str:
    """词典优先 95% 场景；命中即替换"""

async def correct_ocr_typos_by_llm(text: str, *, max_window: int = 200) -> str:
    """LLM correction 兜底 5% 场景；只对置信度低的窗口调用"""

def apply_industry_terms(text: str, *, terms: Mapping[str, str]) -> str:
    """接入 industry_rules 术语映射表"""

def zh_postprocess_pipeline(text: str, *, config: ZhConfig) -> str:
    """组合上述 5 步"""
```

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 32 | 繁简 / 全半形 / 中英混排（纯字符级） |
| Day 33 | OCR typo 词典版 + LLM 版（接已有 LLM Provider） |
| Day 34 | industry_rules 术语接入 + 单测 + 接入 NormalizeStage |

**验收**：在 30 份招股书 OCR 结果上，错字修复准确率 ≥ 90%（词典 + LLM 综合）。

---

### Task 14：性能 Pipeline 工程化（P1-C，Day 35-38）

**新建/扩**：

| 文件 | 行数 | 功能 |
|---|---|---|
| `app/parsing/processors/parse_warmup.py` (新) | ~80 | 服务启动时预热 OCR/TSR 模型 |
| `app/parsing/processors/parse_cache.py` (扩) | 78 → ~250 | LRU + Redis 双层 |
| `app/parsing/processors/incremental_parse.py` (新) | ~300 | bbox-level hash 比对，只重跑变化页 |
| `app/parsing/processors/large_pdf_partitioner.py` (新) | ~200 | >500 页 PDF 切段 + 队列 |
| `app/observability/parse_cost_tracker.py` (新) | ~150 | per-doc/page/GPU 时间统计 + 成本 |

**实施 Day 拆**：

| Day | 内容 |
|---|---|
| Day 35 | `parse_warmup.py` + 接入 FastAPI startup |
| Day 36 | `parse_cache.py` 扩容（Redis + LRU + 命中率统计） |
| Day 37 | `incremental_parse.py`（hash 比对 + 变化页定位） |
| Day 38 | `large_pdf_partitioner.py` + `parse_cost_tracker.py` |

**验收**：
- 模型首次冷启动延迟从 ~30s 降到 < 1s（warmup 生效）
- 同文档重复解析延迟 < 100ms（cache 命中）
- 小修改的文档增量解析时间 < 全量 30%
- 500+ 页 PDF 总解析时间 < 单页串行的 1.5×

---

## 2 完整 Daily 时间表（6 周）

### Week 1：基线 + Reading Order 主体

| Day | Task | 产出 |
|---|---|---|
| D1 | Task 0：基线测试集 + GT 标注启动 | `tests/parse_bench/` + baseline JSON |
| D2 | Task 1：`LayoutBlock` + `_detect_columns` | reading_order_fixer.py 部分 |
| D3 | Task 1：`_sort_in_columns` + `_merge_cross_page_paragraphs` | 完整算法 |
| D4 | Task 1：接入 + 调阈值 | 50 篇论文跑通 |
| D5 | Task 1：单测 ≥ 20 + 双指标接入 | accuracy ≥ 88% |

### Week 2：Reading Order 辅助 + Section Tree

| Day | Task | 产出 |
|---|---|---|
| D6 | Task 2：Header/Footer Remover | 误删 < 1% |
| D7-8 | Task 3：Caption Linker | 准确率 ≥ 90% |
| D9-10 | Task 4：Section Tree Builder | H1 吻合 ≥ 85% |

### Week 3：表格 + 跨页 + Parser 编排

| Day | Task | 产出 |
|---|---|---|
| D11-13 | Task 5：Table Schema + Markdown/HTML/CSV | GriTS ≥ 0.85 |
| D14 | Task 6：跨页表 Cell-Level 合并 | 合并准确率 ≥ 90% |
| D15-17 | Task 7：Parser Fallback Orchestrator + Decision Log | 降级链生效 ≥ 90% |

### Week 4：Quality Gate + Review UI 后端

| Day | Task | 产出 |
|---|---|---|
| D18-19 | Task 8：Quality Gate | 触发率 ≤ 20% / review 通过率 ≥ 70% |
| D20-22 | Task 9：Review UI 后端 + Model + Service | 3 类校正 + republish |

### Week 5：Review UI 前端

| Day | Task | 产出 |
|---|---|---|
| D23-27 | Task 10：Review UI 前端（8 个组件） | 完整跑通校正流程 |
| D28 | Task 11：Routing decision log 前端接入 | 时间线可视化 |

### Week 6：layout-aware chunking + 中文 post-process + 性能

| Day | Task | 产出 |
|---|---|---|
| D29-31 | Task 12：4 类 chunking 策略 | table chunk 召回 +20pt |
| D32-34 | Task 13：中文 / 繁中 post-process | 错字修复 ≥ 90% |
| D35-38 | Task 14：性能 Pipeline 工程化 | cache 命中 < 100ms / 冷启动 < 1s |

**总计 38 个工作日 = 6 周（不含测试集 GT 标注的人工时间）**。

---

## 3 测试用例规格

### 3.1 单元测试（必须每 Task 配套）

| Task | 单测文件 | 用例数 |
|---|---|---|
| Task 1 | `tests/parsing/enrich/test_reading_order_fixer.py` | ≥ 20 |
| Task 2 | `tests/parsing/enrich/test_header_footer_remover.py` | ≥ 10 |
| Task 3 | `tests/parsing/enrich/test_caption_linker.py` | ≥ 15 |
| Task 4 | `tests/parsing/enrich/test_section_tree_builder.py` | ≥ 15 |
| Task 5 | `tests/parsing/enrich/test_table_markdown.py` | ≥ 20 |
| Task 6 | `tests/parsing/processors/test_cross_page_merge.py` | ≥ 8（已有部分） |
| Task 7 | `tests/parsing/processors/test_parser_fallback.py` | ≥ 12 |
| Task 8 | `tests/parsing/processors/test_quality_gate.py` | ≥ 10 |
| Task 9 | `tests/api/v1/test_parsing_review.py` | ≥ 15 |
| Task 12 | `tests/rag/chunking/test_layout_aware_strategies.py` | ≥ 12 |
| Task 13 | `tests/parsing/enrich/test_zh_postprocess.py` | ≥ 15 |
| Task 14 | `tests/parsing/processors/test_incremental_parse.py` | ≥ 10 |

**总用例数 ≥ 162**。

### 3.2 集成测试

| 路径 | 用例 |
|---|---|
| `tests/integration/test_parse_full_pipeline_zh_paper.py` | 论文：parsing→fix→chunk→index→retrieve |
| `tests/integration/test_parse_full_pipeline_prospectus.py` | 招股书：含跨页表的完整流程 |
| `tests/integration/test_review_full_flow.py` | Review UI：解析→标记→校正→republish→检索 |
| `tests/integration/test_fallback_chain.py` | Backend 失败 → 降级 → 兜底 |
| `tests/integration/test_quality_gate_to_quarantine.py` | Gate 触发 → 队列 → 修正 → 解除 |

### 3.3 Benchmark Regression

每周 nightly 跑：
- `tests/parse_bench/run_baseline.py`：在 50 篇论文 + 30 招股书上跑全量
- 输出对比报告：本周 vs 上周 vs baseline
- 任何指标倒退 > 5% → 自动告警

---

## 4 验收指标汇总

| Task | 指标 | Baseline | Target | 测量方式 |
|---|---|---|---|---|
| 1 | Reading order accuracy | 62% | ≥ 88% | quality/reading_order.py 评分 |
| 1 | Stability score | — | ≥ 0.7 全部 | before/after 相似度 |
| 2 | Header/Footer 误删率 | — | < 1% | 100 块人工标注 |
| 2 | Header/Footer 召回 | — | ≥ 95% | 同上 |
| 3 | Caption 绑定准确率 | — | ≥ 90% | 50 篇 + 30 份人工标注 |
| 4 | Section H1 吻合 | — | ≥ 85% | 与目录对比 |
| 5 | 表格 GriTS | ~0.70 | ≥ 0.85 | quality/grits.py |
| 6 | 跨页表合并准确率 | 75% | ≥ 90% | 30 份招股书人工 |
| 7 | 单 backend 跑通率 | — | ≥ 80% | 全量统计 |
| 7 | 降级链生效率 | — | ≥ 90% | 失败案例统计 |
| 8 | Gate 触发率 | — | ≤ 20% | 全量统计 |
| 8 | Review 通过率 | — | ≥ 70% | 人工抽样 |
| 9 | 校正 republish 成功率 | — | ≥ 99% | API 统计 |
| 10 | Review UI 完整流程 | — | 5 份文档通过 | 人工验证 |
| 12 | Table chunk 召回 | — | +20pt vs 通用 | 评测集 hit rate |
| 13 | 中文错字修复 | — | ≥ 90% | 30 份招股书 |
| 14 | 冷启动延迟 | ~30s | < 1s | 性能测试 |
| 14 | Cache 命中延迟 | — | < 100ms | 性能测试 |
| 14 | 增量解析时间 | — | < 30% 全量 | 性能测试 |

---

## 5 风险缓解清单

| 风险 | 触发场景 | 缓解 |
|---|---|---|
| **Reading order 修复后准确率倒退** | 阈值设错 / 算法 bug | 双指标 (before/after)；任何文档倒退 > 5% 阻塞合并 |
| **跨页表误合不相干表** | heuristic 太宽松 | 严格 4-5 条匹配；先用 30 份招股书校准 |
| **Quality Gate 太敏感** | 阈值默认偏严 | 配置化 + 客户可调；首次部署默认宽松 |
| **Review UI 校正破坏 chunk** | republish 出错 | republish 前快照备份 + 失败回滚 |
| **Caption 绑定误绑** | 距离阈值不合理 | 严格组合（距离 + 关键词 + 字体）+ confidence < 0.7 时不绑 |
| **Section tree 把表注误识别为 H** | 字体大小近似 | 强制 label == 'Title' 优先 + 编号正则修正 |
| **incremental 误判** | bbox 浮点比较 | hash 用 round(2) + 容差 |
| **中文 OCR LLM 修复成本爆** | 错字过多全发 LLM | 词典优先 95% + LLM 仅 5% + 长度上限 |
| **38 天工期超期** | 单 Task 难度超估 | 每周末 review；Task 7/9/10 可弹性 +2d |

---

## 6 与现有系统的集成切面

### 6.1 ProcessorService 流水线插入点

```
ParsingStage
  ↓
  [新插入 1] reading_order_fixer (Task 1)
  ↓
  [新插入 2] header_footer_remover (Task 2)
  ↓
InlineAssetStage  ← [新插入 3] caption_linker 在此 stage 内调用
  ↓
  [新插入 4] section_tree_builder (Task 4)
  ↓
  [新插入 5] table_schema 化 (Task 5)（内部）
  ↓
  [新插入 6] cross_page_table_extraction 合并 (Task 6)
  ↓
  [新插入 7] quality_gate (Task 8)  ← 不阻塞但写 quarantine
  ↓
GovernanceStage（原有）
  ↓
NormalizeStage  ← [新插入 8] zh_postprocess (Task 13)
  ↓
ChunkingStage  ← [新增 4 个策略] (Task 12)
  ↓
... (其余 Stage 不动)
```

### 6.2 Routing 集成

```
documents/upload
  ↓
ParserFallbackOrchestrator (Task 7)
  ↓
  routing.choose_pdf_backend (现有，+ decision log)
  ↓
  执行 → quality 评分 (现有)
  ↓
  失败 → 降级链 (Task 7)
  ↓
  ParseResult + ParseDecisionLog
```

### 6.3 Quarantine 集成

```
QualityGate.evaluate() == REVIEW
  ↓
  写 quarantine_queue 表 (现有，新增 parse_quality 类别)
  ↓
前端 /knowledge/quarantine 看到
  ↓
  点击"前往修正" → /parsing/review/[doc_id] (Task 10)
  ↓
  修正完 republish (Task 9)
  ↓
  自动从 quarantine 移除
```

---

## 7 交付物总览

### 代码

- 新增文件 **14 个** ~3740 行
- 改造文件 **6 个** ~+350 行
- 单测 **12 个文件 ≥ 162 用例**
- 集成测试 **5 个文件 ≥ 25 用例**

### 文档

- `docs/parsing/reading-order-algorithm.md`（算法白皮书）
- `docs/parsing/table-schema-spec.md`（Schema 规范）
- `docs/parsing/review-ui-guide.md`（运营手册）
- `docs/parsing/fallback-chain-config.md`（配置指南）

### Benchmark 报告

- `reports/parse-bench-2026-week-N.md`（每周 nightly 自动出）
- `reports/p0-acceptance-2026-06.md`（P0 完成时验收报告）

---

## 8 何时算"完成"——验收清单

P0 完成判定（必须**全部勾选**才合并到 main）：

- [ ] Task 0：基线测试集 80 份文档 + GT 全部标注完成
- [ ] Task 1-4：Reading order accuracy 88% / Header-Footer 召回 95% / Caption 90% / Section 85%
- [ ] Task 5-6：表格 GriTS 0.85 / 跨页合并 90%
- [ ] Task 7：单 backend 跑通 80% / 降级链 90%
- [ ] Task 8：Gate 触发 ≤ 20% / Review 通过 ≥ 70%
- [ ] Task 9-10：Review UI 完整流程在 5 份文档跑通 + 校正后检索能命中
- [ ] Task 11：Routing decision log 在前端可视化
- [ ] 所有 P0 单测通过 + 集成测试通过
- [ ] Nightly benchmark 不倒退
- [ ] 至少 1 个 PoC 客户演示通过（业务专家能自助修正）

P1 完成判定：

- [ ] Task 12：4 类 layout-aware chunking 策略上线 + chunk 召回 +20pt
- [ ] Task 13：中文错字修复 90%
- [ ] Task 14：冷启动 < 1s / cache < 100ms / 增量 < 30%
- [ ] OTel span 覆盖率 100%（解析 → enrich → chunk → gate → review 全链路）

---

## 9 范围之外

**本实施计划不做**：
- 引入 HF 重模型（TATR / LayoutLMv3 / nougat-latex 等）—— 违反"先 pipeline 后模型"
- 公式 LaTeX（在 P2，且只用 Texo 20M）
- 流程图 graph extraction（在 P2，VLM zero-shot）
- 重写 `processor.py` 5569 行主流程
- 重写 `cross_page_merge.py` 现有 530 行（只在末尾 +90 行新增 cell-level 合并）
- 对外 SaaS API（在 `deepdoc-api-productization-2026-q3.md`）
- 中文 benchmark（在 `cn-benchmark-baseline-2026-q2.md`）

---

## 附录 A：每日 standup 模板

```markdown
## Day X / 38 — YYYY-MM-DD

### 昨日完成
- [ ] Task N：xxx（实际 X 行 / 预估 Y 行）
- [ ] 测试：N 个新单测通过

### 今日计划
- [ ] Task M：xxx
- [ ] 预期产出：xxx

### 风险/阻塞
- 无 / xxx

### Benchmark
- Reading order：本日 X% （+/- 与昨日）
- 跨页表合并：本日 X%
- Gate 触发率：本日 X%
```

## 附录 B：每周 review 模板

```markdown
## Week N Review — YYYY-MM-DD

### 完成 Task
- [ ] Task A / Task B / ...

### 验收指标进展
| Task | Target | Actual | 状态 |
|---|---|---|---|
| Reading order | ≥88% | XX% | ✅/⚠️/❌ |

### 工期偏差
- 计划 5d / 实际 Xd / 原因：...

### 下周计划
- Task X / Y / Z

### 风险升级
- 无 / xxx → 缓解：...
```
