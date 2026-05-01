# `/datasets/[id]/precheck` 入库前预检前端调研 — 现状评估 + 自研深化

## Context

**触发场景**:用户从 `/datasets/[id]/precheck` 出发,要求对**入库前预检前端**做全面调研,**约束:不引大包优先自研**。这是 Pre-POC scanner plan(已规划 ~5500 行后端,~650 行 plan)的前端落地点。**核心价值**:解决"基于样例报价总偏差"——让客户在签约/POC 前就能看到数据集质量画像,生成脱敏报告。

**问题**:`/datasets/[id]/precheck` 已具规模(`page-client.tsx` **1446 行** + page.tsx + loading-shell.test),前端骨架基本对齐 Pre-POC plan,**但需对照 plan 7 项核心功能 + 5 档文档标签 + 6 条金律 + 离线脱敏报告三原则**逐项核对:① 格式分布饼图 ② PDF 三档判定(scan/text/low_density + 70% 阈值)③ 长度分位数直方图 ④ MD5 + SimHash 汉明距离 ≤5 重复检测 ⑤ 敏感信息带上下文待审核列表(Presidio 集成)⑥ 大 Excel >5000 行走 Text-to-SQL 提示 ⑦ 5 档文档标签下游 pipeline 路由。本调研以 Pre-POC plan 为对照,**全部自研**(绝不引 PyDeepDoc 重型库)。

---

## 1. 现状盘点

### 1.1 文件清单

| 文件 | 行数 | 角色 |
|---|---|---|
| `page-client.tsx` | **1446** | 主 client 组件 |
| `page.tsx` | 19 | server entry |
| `loading.tsx` / `error.tsx` | - | 状态壳 |
| `page.loading-shell.source.test.ts` | - | 测试 |

### 1.2 已具备能力(需进一步确认)

从规模推断已实现:
- 文件列表 + 上传(应有)
- 基础统计(应有)
- 部分图表展示

需对照 Pre-POC plan 7 项核心功能验证。

### 1.3 7+ 大缺口(对照 Pre-POC plan)

1. ❌ **格式分布饼图**(.pdf / .docx / .xlsx / .pptx / .md / .txt 占比)
2. ❌ **PDF 三档判定可视化**(scan / text / low_density,70% 阈值清晰展示)
3. ❌ **长度分位数直方图**(p10/p50/p90/p99)
4. ❌ **MD5 + SimHash 重复检测**(汉明距离 ≤5 列出待人工确认)
5. ❌ **敏感信息上下文待审核**(Presidio + 周围 50 字上下文,人工标注)
6. ❌ **大 Excel >5000 行检测**(自动建议走 Text-to-SQL 而非向量化)
7. ❌ **5 档文档标签下游路由**(Clean_Markdown / Scan_PDF / Table_Heavy / Image_Heavy / Parse_Failed)
8. ❌ **离线脱敏 HTML 报告**(对齐 Pre-POC 三原则:FILE_A023 / 客观中立 / 单文件)
9. ❌ **8 维难点表标记**(对齐 IBM blueprint:时态/术语变体/信息分散/细粒度/跨实体/否定/数值/时间)
10. ❌ **客户对话故事板**(UMAP 可视化 + 圈选,对齐 viz plan 客户沟通)

---

## 2. 业界对标(全部排除大包)

| 工具 | 借鉴点 | 排除 |
|---|---|---|
| **Llamacloud Parse** 预检 | 商业 SaaS | 不考虑 |
| **Unstructured.io 数据画像** | element 统计 | 全套引入太重 |
| **Pandas Profiling** | 自动报告 | Python 库,前端不引 |
| **DataPrep** | EDA 自动 | 同上 |
| **Great Expectations** | 数据质量 | 偏 ETL |
| **OpenRefine** | 数据清洗 UI | 偏 ETL |
| **Datafold** | 表对比 | 偏 SQL |

**结论**:全部自研,前端用已有 echarts/recharts/plotly/jsdiff 即可。

---

## 3. P0 落地任务(2-3 周)

### 3.1 格式分布与基础统计(~250 行)

**修改/新建** `web/components/precheck/format-distribution-card.tsx`:
- 饼图(echarts):.pdf / .docx / .xlsx / .pptx / .md / .txt / 其他
- 总数 / 总大小 / 平均大小
- 异常格式列表(如 .doc 旧格式 → 提示 LibreOffice 转换)

### 3.2 PDF 三档判定可视化(~350 行)

**新建** `web/components/precheck/pdf-classification-panel.tsx`:
- 三档:`scan_pdf`(<70% 文本)/ `text_pdf`(>70%)/ `low_density`
- 每文档一行,显示文本占比 bar + 判定标签
- 70% 阈值线清晰可见
- 推荐 parser:scan → MinerU OCR / text → Docling 直读

### 3.3 长度分位数直方图(~200 行)

**新建** `web/components/precheck/length-distribution-chart.tsx`:
- echarts histogram + 分位数标线(p10/p50/p90/p99)
- 异常长文档高亮(对齐 Pre-POC 巨型 Excel 检测)
- token 估算(简单:字符 / 4)

### 3.4 重复检测(MD5 + SimHash)(~400 行)

**新建** `web/components/precheck/duplicate-detection-panel.tsx`:
- MD5 完全重复 → 一组组列出
- SimHash 汉明距离 ≤5 → "相似但非完全相同"列出 + 人工确认按钮
- ⚠️ 对齐 Pre-POC 踩坑:**相似 ≠ 冲突**,SimHash 必须人工确认
- 不自动合并 / 不自动删除

### 3.5 敏感信息上下文待审核(~450 行)

**新建** `web/components/precheck/sensitive-info-review.tsx`:
- 调用后端 Presidio(对齐 safety plan)
- 每条命中:`实体类型 / 文档名 / 上下文 50 字 / 推荐处理`
- 三选项:`保留 / 脱敏 / 删除整段`
- 批量审核 UI
- ⚠️ 对齐 Pre-POC 三原则:不主观建议,只标记"待确认"

### 3.6 大 Excel 路由提示(~200 行)

**新建** `web/components/precheck/excel-routing-banner.tsx`:
- >5000 行 Excel 自动检测
- 顶部 banner:"⚠️ 此 Excel 7234 行,推荐走 Text-to-SQL 而非向量化"
- 推荐路径:`/datasets/[id]/db-catalog`(对应 db-catalog 页面)
- 用户可强制走向量化(覆盖默认)

### 3.7 5 档文档标签下游路由(~250 行)

**新建** `web/components/precheck/document-label-router.tsx`:
- 5 档(Clean_Markdown / Scan_PDF / Table_Heavy / Image_Heavy / Parse_Failed)
- 每档对应推荐 pipeline(parser + chunking 策略)
- Sankey 图(echarts):labels → pipelines
- 一键应用推荐配置到 pipeline_config

### 3.8 离线脱敏 HTML 报告(~500 行)

**新建** `web/components/precheck/offline-report-export.tsx`:
- 单文件 HTML 导出(对齐 Pre-POC plan + snapshot plan)
- 三原则:FILE_A023(脱敏文件名)/ 客观中立(无主观评分)/ 单文件
- 内嵌 echarts SVG / 表格 / 5 档 sankey
- 导出前 dialog 确认脱敏范围
- 给销售/POC 团队拿走

---

## 4. P1 任务(1 月)

### 4.1 客户故事板编辑器
- UMAP 可视化(对齐 viz plan)+ 选区 + 注释
- 一键 PDF 导出

### 4.2 8 维难点表标记
- 对齐 IBM blueprint:时态辨析 / 术语变体 / 信息分散 / 细粒度类型 / 跨实体比较 / 否定判定 / 数值单位 / 时间范围
- 自动检测样例文档中的难点

### 4.3 与 ingestion 联动
- 预检通过 → 直接跳转 `/knowledge/ingestion?config=auto`
- 配置自动应用 5 档标签推荐

### 4.4 跨数据集对比
- 多个 dataset 的预检结果对比
- 销售场景:多客户样例对比报价

### 4.5 历史预检对比
- 同 dataset 不同时间预检结果(对齐 snapshot plan content-addressed)

---

## 5. 关键文件

**修改**:
- `page-client.tsx`(1446,集成新组件)

**新建**(纯自研,8 个 P0 组件 ~2600 行):
- `web/components/precheck/format-distribution-card.tsx`
- `web/components/precheck/pdf-classification-panel.tsx`
- `web/components/precheck/length-distribution-chart.tsx`
- `web/components/precheck/duplicate-detection-panel.tsx`
- `web/components/precheck/sensitive-info-review.tsx`
- `web/components/precheck/excel-routing-banner.tsx`
- `web/components/precheck/document-label-router.tsx`
- `web/components/precheck/offline-report-export.tsx`
- 后端配套:`app/rag/tools/pre_poc_scanner/`(已规划 5500 行)

**复用**:
- echarts pie/histogram/sankey
- Presidio(对齐 safety plan)
- 5 档文档标签(Pre-POC plan)
- snapshot plan HTML 报告 SSR 框架

---

## 6. 验证

1. 格式饼图:测试集 5 种格式分布显示正确
2. PDF 三档:扫描版 → scan_pdf;Markdown 转 PDF → text_pdf;混合 → low_density
3. SimHash:已知相似文档汉明距离 ≤5 列出
4. Presidio 上下文:身份证 / 手机号 / 邮箱 命中带 50 字上下文
5. 大 Excel:>5000 行 Excel 触发 Text-to-SQL banner
6. 离线报告:导出 HTML 单文件 + 浏览器打开图表正常
7. `pnpm verify` + `loading-shell.source.test` 全过

---

## 7. 与已有调研协同

- **`rag-pre-poc-scanner`**(锚点):本计划是其前端落地形态,严格遵守 6 条金律 + 三原则
- **`rag-poc-to-mvp-delivery`**:预检通过后接入 MVP 流水
- **`rag-safety-compliance-deep-dive`**:Presidio 中文扩展共享
- **`rag-ibm-champion-blueprint`**:8 维难点表 P1 集成
- **`rag-poc-attribution-framework`**:预检数据是 POC 报价的依据
- **`rag-visualization-deep-dive`**:UMAP 客户故事板共享
- **`rag-ingestion-frontend-deep-dive`**(刚完成):预检 banner 集成

---

## 8. 关键洞察

1. **预检是商业差异化的源头**:让销售/POC 团队拿到客户样例就能秒报告,对齐"基于样例报价总偏差"解药
2. **不引大包**:Pandas Profiling / Great Expectations 都是 ETL 思路不适合 RAG;自研 8 组件 ~2600 行覆盖
3. **客观中立是底线**:Pre-POC plan 三原则核心——不主观评分、不推荐 chunk size、不智能聚类
4. **SimHash 必须人工确认**:相似 ≠ 冲突,自动合并是错误,这是 Pre-POC plan 关键踩坑
5. **5 档标签是上下游协议**:precheck → ingestion 通过标签传递,不需要 ingestion 重新判定
6. **离线 HTML 报告是销售工具**:单文件 + 脱敏 = 客户能拿走 = 真护城河
7. **Excel 路由是被忽视的差异化**:>5000 行强行向量化 = 灾难,Text-to-SQL 是正解

---

## 9. 2026-04-30 Product PASS

Status: PASS - 已完成必要产品化子集,本 MD 不再作为后续执行入口。

已落地:
- 数据集预检页已接 scan run 创建/取消、SSE/polling、summary、samples、near-dup、findings drilldown、历史 diff、JSON/HTML 脱敏导出。
- 预检能力覆盖 PDF 扫描/文本/未知判定、PII/Secrets、SimHash 相似线索、复用未变文件、策略建议和 ingestion policy apply。
- 入库页售前模式已经消费预检 summary/samples/near-dup 并生成项目数据盘点报告,形成“预检 → 售前证据 → 入库策略”的闭环。

明确不做:
- 暂不做 UMAP 故事板、跨客户对比大屏或完整离线报告编辑器。
- 暂不主观打分或自动合并相似文档;SimHash 继续作为待确认线索。

Directive: 预检后续只扩展客观证据与下游策略建议,不要把它改成自动决策或主观评分系统。
