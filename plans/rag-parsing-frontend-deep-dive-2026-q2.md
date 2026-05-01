# `/parsing` 解析工作台前端调研 — 现状评估 + 自研深化路线

## Context

**触发场景**:用户从 `/parsing` 出发,要求对**解析工作台前端**做全面调研,**约束:不引大包优先自研**。RAG 入库第一站,前端是用户调试解析效果的核心 UI。后端已有 `parsing-chunking-deep-dive` plan(648 行,覆盖 OmniDocBench 86.2 / MinerU 2.5 / Docling 97.9% 表格 / Vectara 反直觉 / Context Cliff @2500 等),**但前端层未对标**。

**问题**:`/parsing` 已具规模(`web/components/parsing/` ~5800 行,15+ 组件 + PDF viewer 1264 行 + active-file-pane 1224 行 + workbench-shell 577 行 + bbox-overlay),覆盖文件浏览/解析队列/extract panel/elements panel/PDF + bbox 渲染/移动端适配/parse 比对对话框,**但缺**:① 解析策略可视化对比(MinIO 2.5 vs Docling vs DeepDoc)② 解析质量量化打分 ③ chunking 策略联动预览(对接 `/chunk-preview`)④ 解析失败归因可视化(parse-risk 三档判定 scan/text/low_density)⑤ 大文档解析进度细粒度 ⑥ OCR/表格/数学公式专项编辑器 ⑦ 多模态 chunk 预览(图表 thumbnail + bbox)。本调研对标业界(Llamacloud Parse Viewer / Docling Viewer / Unstructured.io UI / Mathpix / Adobe PDF Extract),**全部自研补齐**。

---

## 1. 现状盘点

### 1.1 文件清单(~5800 行)

| 文件 | 行数 | 角色 |
|---|---|---|
| `pdf-viewer.tsx` | 1264 | PDF.js 自研 viewer |
| `parsing-active-file-pane.tsx` | 1224 | 当前文件主面板 |
| `parsing-workbench-shell.tsx` | 577 | 工作台外壳 |
| `parsing-extract-panel.tsx` | 431 | 抽取面板 |
| `parsing-sidebar-pane.tsx` | 338 | 侧栏 |
| `parse-compare-dialog.tsx` | 281 | 解析比对对话框 |
| `parsing-library-browser.tsx` | 257 | 文件库浏览器 |
| `parsing-page.tsx` | 255 | 页面壳 |
| `parsing-mobile-inspector-content.tsx` | 238 | 移动端 |
| `parsing-elements-panel.tsx` | 228 | 元素面板 |
| `parsing-library-preview-pane.tsx` | 212 | 库预览 |
| `parsing-mobile-queue-content.tsx` | 162 | 移动队列 |
| `parsing-right-panel.tsx` | 124 | 右栏 |
| `parsing-left-panel.tsx` / `parsing-main-panel.tsx` | 52 / 17 | 容器 |
| `bbox-overlay.tsx` | - | bbox 覆盖层(已自研) |

### 1.2 已具备能力

- ✅ PDF.js 自研 viewer 1264 行
- ✅ bbox 覆盖层(parser 输出坐标可视化)
- ✅ 解析比对对话框(parse-compare-dialog)
- ✅ 抽取/元素/库浏览三视图
- ✅ 移动端响应
- ✅ 与后端 25+ parser & 70+ chunking 联动

### 1.3 8 大缺口

1. ❌ **解析策略并排对比**(MinIO 2.5 vs Docling vs DeepDoc 同文档输出对照)
2. ❌ **解析质量打分**(对齐 OmniDocBench 86.2 / Docling 97.9% 表格的 5-6 维量化评分)
3. ❌ **chunking 联动预览**(parsing → chunk-preview 链路打通)
4. ❌ **parse-risk 三档判定**(scan_pdf / text_pdf / low_density 70% 阈值,Pre-POC plan 已规划)
5. ❌ **大文档进度细粒度**(>100 页时 per-page 状态)
6. ❌ **OCR / 表格 / 公式专项编辑器**(让用户修订错误的解析输出)
7. ❌ **多模态 chunk thumbnail**(图表/表格 bbox 缩略图)
8. ❌ **解析失败归因**(.doc 需 textutil/LibreOffice 回退,Pre-POC plan 踩坑点)

---

## 2. 业界对标(参考 / 排除)

| 工具 | 借鉴点 | 排除原因 |
|---|---|---|
| **Llamacloud Parse Viewer** | 一流体验 | 商业 SaaS |
| **Unstructured.io UI** | element bbox 对照 | 全套引入太重 |
| **Docling Viewer** | 解析对照 | 与 docling 强绑 |
| **Mathpix** | 公式编辑 | 商业 |
| **Adobe PDF Extract** | OCR 标杆 | 商业 |
| **PDF.js**(已用) | 自研 viewer 基建 | ✅ 保留 |
| **react-pdf-highlighter** | 高亮组件思路 | 100KB,可参考不引 |

**结论**:全部自研在 `web/components/parsing/` 与 `web/lib/parse-*`。

---

## 3. P0 落地任务(2-3 周)

### 3.1 解析策略并排对比(~500 行)

**新建** `web/components/parsing/parser-comparison-grid.tsx`:
- 4 列 grid:`MinerU 2.5` / `Docling` / `DeepDoc(已有)` / `Mathpix(可选)`
- 同一文档同步滚动 + 同步 bbox 高亮
- 差异色编码:绿=只在 A、红=只在 B、灰=共有
- **后端**:`POST /api/v1/parsing/compare`,接收 doc_id + 多 parser,返回各自 element 列表

### 3.2 解析质量量化打分(~400 行)

**新建** `web/components/parsing/quality-score-panel.tsx`:
- 6 维评分(对齐 OmniDocBench):
  - 文本完整度 / 表格识别 / 公式渲染 / 阅读顺序 / 标题层级 / 图片提取
- 雷达图(echarts 已有)+ 6 个 metric tile
- 后端调 `app/rag/evaluation/parsing_quality_score.py`(新建)

### 3.3 parse-risk 三档判定 UI(~300 行)

**新建** `web/components/parsing/parse-risk-banner.tsx`:
- 文件上传后顶栏显示判定结果:
  - 🟢 `Clean Markdown`(text_pdf,>70% 文本)
  - 🟡 `Low Density`(混合)
  - 🔴 `Scan PDF`(<70% 文本,需 OCR)
- 5 档文档标签(对齐 Pre-POC plan):Clean_Markdown / Scan_PDF / Table_Heavy / Image_Heavy / Parse_Failed
- 点击 → 显示标签依据 + 推荐 parser

### 3.4 chunking 联动预览(~250 行)

**修改** `parsing-active-file-pane.tsx`:
- 新增"切块预览"按钮 → 跳 `/chunk-preview?doc_id=xxx&strategy=auto`
- 解析完成后自动联动 chunk 预览(对齐 IBM blueprint chunking_grid 300/50)
- 在 parsing 端就能看到 chunk 边界 overlay

### 3.5 解析失败归因(~250 行)

**新建** `web/components/parsing/parse-failure-attribution.tsx`:
- 失败时显示:错误类型 / 已尝试 fallback / 推荐手动修复
- .doc → 提示 "需 LibreOffice 转换"(对齐 Pre-POC 踩坑)
- 损坏 PDF → 提示 "尝试重新下载"
- OCR 超时 → 切换 lighter parser

### 3.6 大文档 per-page 进度(~200 行)

**修改** `parsing-page.tsx` + 新建 `web/components/parsing/per-page-progress.tsx`:
- WebSocket / SSE 接收 per-page 状态
- 100 页文档显示 100 个小方块,实时变绿
- 后端:`GET /api/v1/parsing/{doc_id}/progress/stream` 已存在?或新增

---

## 4. P1 任务(1 月)

### 4.1 OCR / 表格 / 公式专项编辑器
- 用户可手动修订 parser 输出
- 公式走 KaTeX(已有?)/ MathML 编辑
- 表格用 spreadsheet-like 编辑器(自研 200 行 grid)
- 修订入库自动触发 reparse

### 4.2 多模态 chunk thumbnail
- 图表 / 表格 bbox 缩略图(canvas 截图)
- gallery 视图 + 检索

### 4.3 解析时序对比
- 同文档不同时间解析结果对比(对齐 snapshot plan content-addressed)
- 检测 parser 升级回归

### 4.4 与 OTel 联动
- parsing 各阶段 span 入 OTel(viz plan P0)
- 时间线显示 OCR / 表格识别 / 阅读顺序各阶段耗时

---

## 5. 关键文件

**修改**:
- `web/components/parsing/parsing-active-file-pane.tsx`(加 quality / chunking 联动)
- `web/components/parsing/parsing-page.tsx`
- `web/components/parsing/parse-compare-dialog.tsx`(扩展为 grid)

**新建**:
- `web/components/parsing/parser-comparison-grid.tsx`(P0)
- `web/components/parsing/quality-score-panel.tsx`(P0)
- `web/components/parsing/parse-risk-banner.tsx`(P0)
- `web/components/parsing/parse-failure-attribution.tsx`(P0)
- `web/components/parsing/per-page-progress.tsx`(P0)
- `web/components/parsing/manual-element-editor.tsx`(P1)
- `web/components/parsing/chunk-thumbnail-gallery.tsx`(P1)
- `app/rag/evaluation/parsing_quality_score.py`(P0,后端 6 维评分)

**复用**(零修改):
- PDF.js / bbox-overlay / 已有 25+ parser & 70+ chunking
- Pre-POC scanner plan 的 5 档文档标签
- OmniDocBench / Docling 86.2/97.9 评测对标

---

## 6. 验证

1. parser comparison 烟测:同一 PDF 4 parser 并排,bbox 同步
2. parse-risk 烟测:扫描版 PDF → 🔴 Scan_PDF;Markdown → 🟢 Clean
3. chunking 联动:点"切块预览"→ chunk-preview 加载 doc 数据
4. quality score:OmniDocBench 样例打出 86.x 分,与 paper 一致
5. `pnpm verify` + 现有 source.test.ts 全过

---

## 7. 与已有调研协同

- **`rag-parsing-chunking-deep-dive`**:本计划是其前端落地;6 维 quality 对齐 OmniDocBench
- **`rag-pre-poc-scanner`**:5 档文档标签 + parse-risk 三档判定共享
- **`rag-ibm-champion-blueprint`**:Docling JsonReportProcessor + chunking 300/50 联动
- **`rag-visualization-deep-dive`**:OTel 埋点 + chunk PDF bbox 高亮 P0 协同
- **`rag-poc-to-mvp-delivery`**:双重输出(Clean Markdown 入库 + Clean DOCX 跳转)前端形态

---

## 8. 关键洞察

1. **5800 行已是业界一线**,缺的是"对比+量化+联动",不是"做更花的 viewer"
2. **不引大包**:Llamacloud / Unstructured 商业全套不要,自研补 6 个核心组件 ~1900 行即可
3. **parse-risk 是产品差异化**:让客户在解析前就知道"会不会糟糕",对齐 Pre-POC 价值
4. **质量评分必须量化**:OmniDocBench 86.2 不是论文数字,是产品 KPI
5. **chunking 联动是真护城河**:parsing 与 chunking 不联动 = 调试盲飞

---

## 9. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口。

已落地:
- 解析页保留 main 分支核心解析逻辑,同时补齐 PDF/bbox 证据、quality gate、parse compare、elements panel、structured extract panel 和知识库数据集桥接。
- 解析结果已能把 elements、visual_kind、bbox、pdf_quality、quality_gate 贯穿到 run state、库恢复、移动 inspector 和对比弹窗。
- 当前闭环是“解析/恢复源文件 → 查看结构化元素与证据 → 对比解析结果 → 必要时进入切块/入库”,符合产品使用路径。

明确不做:
- 暂不做独立 4-parser 并排大屏、公式/表格专用编辑器、逐页 SSE 进度矩阵或商业 Parse Viewer 复刻。
- 解析高级能力继续以证据面板和对比弹窗呈现,不再把所有 parser 内部参数暴露给普通操作人员。

Directive: 后续解析页修改必须优先保持 main 分支解析链路稳定,UI 只围绕证据可解释和少量人工兜底扩展。
