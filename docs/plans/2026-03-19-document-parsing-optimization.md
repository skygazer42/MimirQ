# 文档解析优化计划

> 基于 2026-03-19 代码审计 + 行业对标（OmniDocBench, SCORE-Bench, ECLAIR, GLM-OCR, PaddleOCR-VL 1.5, Nemotron-Parse 等）。
> 聚焦解析管线：质量评估、结构还原、格式覆盖、性能优化。

---

## 现状审计摘要

- **15+ PDF 解析器**：basic(PyMuPDF) / Docling / DeepDoc / Marker / MinerU / PaddleVL / olmOCR / DeepSeek OCR / Qianfan OCR / ETL4LLM / MagicPDF / MarkItDown 等
- **质量评分路由**：`score_pdf_quality` 三维评分 → `choose_pdf_backend` 自动选择
- **解析竞赛**：`select_best_parse_attempt` 多解析器竞争取最优
- **治理管线**：30+ governance 选项
- **表格/图片抽取**：DeepDoc TableStructureRecognizer + pdfplumber + 多路图片抽取
- **诊断/兜底**：解析失败诊断 + 推荐备选 + 多级 fallback

---

## 优化点

### Opt 1: 解析产出自动化 Benchmark（TEDS / NID / SCORE） -- P0

维护 golden-set 文档，对每个解析器计算 text edit distance / TEDS(表格) / reading order NID / image extraction recall，纳入 CI nightly。涉及 `app/parsing/quality/`, `scripts/`。

### Opt 2: 跨页表格/列表续接 -- P0

新增 `app/parsing/processors/cross_page_merge.py`，检测相邻页截断表格（列数匹配 + 缺 header）→ 合并。同理处理跨页编号列表。

### Opt 3: 公式识别与 LaTeX 转写 -- P0

短期开启 MagicPDF `formula_enable`；中期新增 `formula_processor.py` 调用 PaddleOCR Formula Recognition / UniMERNet。

### Opt 4: VLM 解析校正管线（Parse-then-Correct） -- P1

新增 `vlm_correction.py`，对低分页面（table_quality < 0.6）将 Markdown + 页面图像送入 VLM 校正。

### Opt 5: 图片/图表语义描述增强 -- P1

在 `InlineAssetStage` 中统一对所有解析路径的图片 asset 做 VLM 描述（图表结构化描述 / 照片 caption）。

### Opt 6: 阅读顺序校验 -- P1

新增 `reading_order.py`，XY-Cut 算法生成预期顺序 → NID 对比 → 纳入质量评分第四维度。

### Opt 7: 新增 EPUB / RTF / EML / 独立图片 -- P1

EPUB/RTF/ODT 注册到 Pandoc；EML/MSG 新增 `email_parser.py`；独立图片新增 `image_parser.py`。

### Opt 8: 解析竞赛增强 — 多维度评分矩阵 -- P2

扩展为 `0.40*text + 0.30*table + 0.15*image + 0.15*reading_order`，用户可按文档类型调权重。

### Opt 9: 跨文档近似去重 -- P2

新增 `document_dedup.py`，MinHash + LSH 跨文档近似去重（Jaccard > 0.85）。

### Opt 10: GLM-OCR / PaddleOCR-VL 1.5 集成 -- P1

新增 `glm_ocr_parser.py`（0.9B, Apache-2.0, OmniDocBench 94.5%），更新 PaddleVL 支持 1.5。

### Opt 11: 解析缓存与增量重解析 -- P2

新增 `parse_cache.py`，key = `sha256(content) + backend + config_hash`，MinIO 存储 + TTL。

### Opt 12: 解析质量报告仪表盘 -- P2

前端：各解析器使用占比、平均质量分、fallback 率、低质量文档列表 + 一键重试。

---

## 建议实施顺序

**Phase 1 (1-2 周)**: Opt 1 (Benchmark), Opt 3 (公式), Opt 7 (新格式), Opt 10 (GLM-OCR)

**Phase 2 (2-3 周)**: Opt 2 (跨页表格), Opt 4 (VLM 校正), Opt 6 (阅读顺序)

**Phase 3 (2-3 周)**: Opt 5 (图表描述), Opt 8 (竞赛矩阵), Opt 9 (近似去重)

**Phase 4 (1-2 周)**: Opt 11 (解析缓存), Opt 12 (质量仪表盘)
