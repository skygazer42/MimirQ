# MimirQ 功能优化（可视化 / 文档解析 / 文档入库 / 文档治理）30 条任务路线图

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不推翻现有架构（FastAPI + Postgres + Milvus + MinIO + Next.js）的前提下，围绕“可视化可解释 / 解析可回溯 / 入库可控 / 治理可合规”，补齐关键功能与工作流闭环，形成可执行的 30 条任务 backlog。

**Architecture:** 以现有 `Parse → Governance → Chunk → Index` 为主线；新增能力优先做成 **可配置（profile/policy）+ 可审计（snapshot/log）+ 可视化（diff/metrics）**，避免一次性“大而全”。

**Tech Stack:** Backend: FastAPI, SQLAlchemy, LangChain/LangGraph, Milvus, Postgres, MinIO, Redis. Frontend: Next.js (App Router), Tailwind/shadcn, pdfjs-dist, vitest.

## 执行顺序建议（按依赖与 ROI 排序）

- Wave 1（打地基 + 立刻提升可见性）：Task 8、Task 6、Task 7、Task 17、Task 24
- Wave 2（体验与质量闭环）：Task 2、Task 4、Task 5、Task 9、Task 14、Task 23
- Wave 3（扩展连接器 + 治理合规）：Task 20、Task 21、Task 25-30

---

## 可视化（Visual）

### Task 1：开源/竞品对标清单 + Feature Gap 文档化（一次性梳理，后续按清单迭代）

**Files:**
- Create: `docs/plans/2026-01-29-kb-gap-analysis.md`

**What:**
- 对标 3-5 个“RAG 知识库”开源项目（KB 工作流、可视化、连接器、治理、版本/审计）。
- 产出：Feature Gap 列表 + 你项目对应模块映射 + 优先级（P0/P1/P2）与预估工作量。

**Acceptance:**
- 文档包含：对标对象、差距条目、落地路径（落到本仓库的模块/文件）、推荐优先级。

---

### Task 2：Chunk Preview 增强：PDF 视图高亮“Chunk → 页面框”与“Chunk → 原文偏移”双定位

**Files:**
- Modify: `web/components/chunk-preview/*`
- Reuse: `web/components/parsing/pdf-viewer.tsx`
- Modify: `app/api/v1/documents.py`（`/chunk-preview` 输出增强：可选返回 page-box 结构）

**What:**
- 在 `/chunk-preview` 增加“PDF 面板”模式：选中 chunk 时在 PDF 上画框；悬浮 chunk 时临时高亮。
- 当解析器没有 box 信息时，退化到现有的“原文面板 char offset 高亮”。

**Acceptance:**
- 选中 chunk 可一键跳到 PDF 对应页；高亮框不漂移（缩放/滚动/窗口变化下保持一致）。

---

### Task 3：Chunk 质量仪表盘：长度分布 / overlap 浪费 / coverage / gap 统计可视化 + 可导出

**Files:**
- Modify: `web/components/chunk-preview/components/*`
- Modify: `web/components/chunk-preview/utils/export.ts`
- (Optional) Modify: `app/api/v1/documents.py`（新增统计字段/细分维度）

**What:**
- 以图表展示 chunk 分布（按 section / parent-child / SKIP / 文件等维度切片）。
- 一键导出到 `review-report.json` 增强字段，用于 QA/评审留痕。

**Acceptance:**
- 支持保存当前筛选条件；导出包含图表对应的聚合数据（可复现）。

---

### Task 4：数据治理 Diff 解释器：规则归因（哪条 rule 改了哪些段落）+ “影响面”统计

**Files:**
- Modify: `web/components/data-governance-panel.tsx`
- Modify: `app/rag/preprocessing/processor.py`（返回 rule-level stats）
- Modify: `app/api/v1/pipeline.py`（`clean-preview` 返回增强）

**What:**
- 在治理预览中提供“归因视图”：展示每条规则的命中次数/删改段落示例。
- 提供“影响面”指标：删除字符数、段落数、URL 变化数、PII/Secrets 命中数等。

**Acceptance:**
- 前端能按规则过滤 diff；用户能快速定位“哪条规则过猛”。

---

### Task 5：解析对比工作台：同一文件多解析器 A/B 输出对比（Markdown diff + PDF box overlay）

**Files:**
- Modify: `web/app/parsing/page.tsx`
- Modify: `web/components/parsing/pdf-viewer.tsx`
- Modify: `app/api/v1/pipeline.py`（新增 parse-compare API 或复用现有 preview API）

**What:**
- 同一文件选择多个 `parser_backend` 批量解析，展示输出差异与质量评分。
- 支持把“最佳解析结果”一键推送到治理/切块流程（缓存复用）。

**Acceptance:**
- A/B 对比可保存为一次“Parse Run”记录；支持复制复现配置（curl/JSON）。

---

### Task 6：数据集健康看板（Dataset Health Dashboard）：格式分布 / 扫描件占比 / PII/Secrets / 近重复 / 失败率

**Files:**
- Modify: `web/app/knowledge/page.tsx`（或拆出 `web/app/datasets/*` 详情页）
- Modify: `app/api/v1/datasets.py`（新增 dashboard 聚合接口）
- Modify/Create: `app/services/dataset_metrics_service.py`

**What:**
- 将预检扫描 + 入库统计 + 治理统计汇总到“数据集健康”。
- 给出“下一步建议”（例如：扫描件高 → 建议 OCR；PII 高 → 建议开启脱敏；重复高 → 建议去重策略）。

**Acceptance:**
- 面板能在 1-2 秒内加载（聚合接口带缓存/限流）；支持导出 JSON/CSV。

---

### Task 7：Connector Run 可视化监控：进度条 + 错误聚类 + 一键重试/续跑 + 产物文档列表

**Files:**
- Modify: `web/app/knowledge/page.tsx`（或新增 `web/app/connectors/*`）
- Modify: `app/api/v1/connectors.py`
- Modify: `app/models/connector.py`（如需更细粒度状态/错误结构）

**What:**
- 运行维度：统计抓取/入库成功数、失败数、被过滤数；失败原因聚类（SSRF/超时/解析失败/治理过滤等）。
- 支持“只重试失败项”“从中断点续跑”（best-effort）。

**Acceptance:**
- 任意 run 都能点开看到“具体失败 URL/错误”；可导出错误报告（JSON）。

---

### Task 8：文档血缘时间线（Lineage Timeline）：解析/治理/切块/入库/版本/权限的事件串联

**Files:**
- Modify/Create: `app/models/audit_log.py`（或复用现有审计表结构）
- Modify: `app/api/v1/documents.py`（新增 `/documents/{id}/timeline`）
- Modify: `web/app/knowledge/page.tsx`（文档详情增加 Timeline tab）

**What:**
- 把一次文档处理的关键事件结构化：pipeline_hash、参数快照、耗时、失败原因、操作者、重试次数。

**Acceptance:**
- UI 可按 stage 过滤；事件包含 request_id，可跳转到 `/audit` 做溯源。

---

## 文档解析（Parsing）

### Task 9：解析质量 Gate 2.0：统一 PDF/Office/HTML 质量评分 + 可解释原因 + 自动 fallback 策略

**Files:**
- Modify: `app/parsing/quality/*`
- Modify: `app/parsing/factory.py`
- Modify: `app/api/v1/pipeline.py`（解析预览返回 quality_gate 细节）

**What:**
- 将“质量评分”标准化输出为：`pass/warn/fail + reasons[] + evidence`。
- 对 `parser_backend=auto` 提供可配置 fallback 顺序（按文件类型/扫描件/表格密度）。

**Acceptance:**
- 解析预览与入库流程都能得到一致的 gate 结果；UI 能展示原因与建议后端。

---

### Task 10：解析产物持久化增强：page_count/table_count/image_count/blocks 统计与可检索元数据

**Files:**
- Modify: `app/models/document.py`（或 `documents.metadata` 结构定义）
- Modify: `app/services/indexer.py`（入库时写入统计/元数据）
- Modify: `web/app/parsing/page.tsx`（展示与筛选）

**What:**
- 把解析阶段的统计写到 document 级别（便于后续查询、筛选、治理策略分流）。

**Acceptance:**
- 能按“扫描件概率高/表格密集/图片多”等标签筛选文档并批量处理。

---

### Task 11：结构化表格增强：Table Tag 的“预览 → 路由 → 检索”闭环（小表入 chunk，大表入 table store）

**Files:**
- Modify: `app/parsing/parsers/*`（表格输出规范化）
- Modify: `app/storage/*`（table store / tag routing）
- Modify: `web/app/parsing/page.tsx`（表格预览、路由提示）
- Docs: `docs/guides/table_tag.md`

**What:**
- 给表格一个稳定的 `table_id` / `source_ref`；大表走结构化存储，小表仍进入文本 chunks。

**Acceptance:**
- 对话引用能同时引用“文本 chunk”和“表格单元格/行”（带来源定位）。

---

### Task 12：图片理解增强：OCR/Caption 作为可检索文本（可选启用，默认保守）

**Files:**
- Modify: `app/parsing/parsers/*`（图片抽取/引用）
- Create: `app/parsing/enrich/image_caption.py`
- Modify: `app/api/schemas/document.py`（pipeline options 增加开关）
- Modify: `web/app/parsing/page.tsx`

**What:**
- 对带图的 PDF/Office：可选对图片做 OCR/Caption，把结果挂到 chunk metadata 或作为独立 chunk。

**Acceptance:**
- 能在 chunk preview 中看到图片对应的 OCR 文本；可一键关闭（成本控制）。

---

### Task 13：多语言分句/分段策略优化：中英混排更稳、标点/列表/代码块更鲁棒

**Files:**
- Modify: `app/parsing/chunking/*`
- Modify: `app/rag/preprocessing/language.py`
- Modify: `web/components/chunk-preview/*`（策略说明与示例）

**What:**
- 在 `separator`/`langchain_recursive` 等策略中优化中英句边界与列表边界。

**Acceptance:**
- 给定一组混排样例（tests fixture），chunk 边界稳定且不切断代码块/表格。

---

### Task 14：解析缓存工程化：file_sha256 + parser_backend + parser_version 维度缓存与失效策略

**Files:**
- Modify: `app/parsing/cache.py`（如果不存在则 Create）
- Modify: `app/api/v1/documents.py`（chunk-preview/by-sha 与 parsing/governance 复用）
- Modify: `web/app/parsing/page.tsx`

**What:**
- 让 parsing / governance / chunk-preview 能复用同一份 parse cache，减少重复解析与上传。

**Acceptance:**
- 重复预览耗时显著下降；缓存命中/年龄可视化；升级解析器后自动失效（避免脏缓存）。

---

### Task 15：章节/标题抽取统一：将 outline_path/header_path 作为一等元数据（用于分组/过滤/引用）

**Files:**
- Modify: `app/parsing/utils/*`
- Modify: `app/services/indexer.py`（把 outline_path 写入 chunk metadata）
- Modify: `web/components/chunk-preview/*`（强化 Section 视图）

**What:**
- 强化“章节路径”的抽取与一致性，让 chunk 分组、引用溯源更稳定。

**Acceptance:**
- 不同解析器下同一文档的章节路径差异缩小；chunk list 的分组准确。

---

### Task 16：解析失败的自助诊断：按页采样 + 错误分类 + 一键切换解析器重试

**Files:**
- Modify: `app/api/v1/pipeline.py`
- Modify: `web/app/parsing/page.tsx`
- Modify: `docs/guides/*`（补充排障文档）

**What:**
- 将解析失败原因结构化（依赖缺失/格式不支持/超时/扫描件 OCR 不可用等）。

**Acceptance:**
- 用户在 UI 内能完成 80% 的自助排障，不需要查服务日志。

---

## 文档入库（Ingestion）

### Task 17：数据集级入库策略（Ingestion Policy）：profile/pipeline/chunk/retrieval 默认配置 + 版本化

**Files:**
- Modify/Create: `app/models/dataset_policy.py`
- Modify: `app/api/v1/datasets.py`
- Modify: `web/app/knowledge/page.tsx`（策略编辑与应用）

**What:**
- 把“建议配置”从一次性参数变成可版本化的 policy，并可应用到批量入库/连接器。

**Acceptance:**
- policy 有版本号与变更记录；可回滚；新入库默认继承 policy。

---

### Task 18：批量上传 UX 2.0：目录结构保留、元数据映射、队列并发与失败重试

**Files:**
- Modify: `web/app/parsing/page.tsx`、`web/app/knowledge/page.tsx`
- Modify: `app/api/v1/documents.py`（批量接口完善）

**What:**
- 支持“文件夹上传/ZIP 保留路径”；把相对路径写入 document metadata。
- 队列支持并发上限、失败重试、断点续传（best-effort）。

**Acceptance:**
- 1000+ 文件批量上传可控；失败项可单独重试；可导出上传结果清单。

---

### Task 19：URL 入库增强：sitemap 导入、canonical/robots 处理、正文提取策略（XPath/Readability）

**Files:**
- Modify: `app/api/v1/documents.py`（url ingest）
- Modify: `app/api/utils/url_ingest.py`
- Modify: `app/services/web_crawler.py`
- Docs: `docs/guides/url_ingest.md`、`docs/guides/web_crawl.md`

**What:**
- 支持 sitemap.xml 批量导入；可配置 robots 遵循策略与 canonical 去重。

**Acceptance:**
- 同站点重复页面明显减少；抓取范围可控；错误分类清晰。

---

### Task 20：Connector 框架升级：定时任务（cron）+ 增量同步（etag/last-modified）+ secret 轮换

**Files:**
- Modify: `app/models/connector.py`
- Modify: `app/api/v1/connectors.py`
- Modify: `app/tasks/*`

**What:**
- 让连接器从“一次性 run”升级为可周期同步；支持增量拉取与差异入库。

**Acceptance:**
- 定时同步可配置启停；同步记录可审计；secret 在 API 返回里默认脱敏。

---

### Task 21：新增 3-5 个高价值连接器（优先企业常见）：Confluence / Notion / GitHub / Google Drive / S3

**Files:**
- Create: `app/services/connectors/*`
- Modify: `app/api/v1/connectors.py`（connector registry）
- Create: `web/app/connectors/*`（配置表单）

**What:**
- 每个连接器要支持：映射 metadata（作者/时间/标签）、权限同步（至少 owner + dataset 继承）。

**Acceptance:**
- 连接器 run 可追踪每个源文档到本系统 document_id 的映射；支持一键 re-sync。

---

### Task 22：入库去重闭环：同文件/近重复/跨版本重复的识别、解释与处理建议

**Files:**
- Modify: `app/services/indexer.py`（near dedup）
- Modify: `app/api/v1/documents.py`
- Modify: `web/app/knowledge/page.tsx`

**What:**
- 把 simhash 近重复结果变成“可查看、可决策”：保留哪个版本、合并还是跳过。

**Acceptance:**
- UI 能列出重复候选并解释相似度；支持批量 SKIP/合并策略。

---

### Task 23：按 pipeline_hash 的“再入库”能力：重切块/重嵌入/重建 BM25（异步、可取消、可限流）

**Files:**
- Modify: `app/api/v1/documents.py`（新增 reindex endpoint）
- Modify: `app/tasks/*`
- Modify: `web/app/knowledge/page.tsx`（版本页增加 reindex）

**What:**
- 允许针对某个版本执行重建索引，不影响旧版本（符合你已有版本体系）。

**Acceptance:**
- 任务可取消；支持并发控制；完成后可一键激活新版本。

---

## 文档治理（Governance）

### Task 24：治理 Profile 管理 UI：创建/编辑/导入导出 + 正则规则安全提示 + 沙盒测试

**Files:**
- Modify/Create: `web/app/data-governance/*`
- Modify: `app/api/v1/pipeline.py`（profiles 增强：导入冲突策略）
- Modify: `app/services/governance_profiles.py`

**What:**
- 把 `governance-profiles` API 用起来：支持 custom profile 的全生命周期管理。

**Acceptance:**
- profile 可分享（导出 JSON）；导入时可选择覆盖/跳过/重命名；规则有 ReDoS 风险提示。

---

### Task 25：Quarantine 工作流：治理过滤的文档进入隔离区，可人工复核/批准/永久丢弃

**Files:**
- Modify: `app/models/document.py`（增加 quarantined 状态/原因）
- Modify: `app/api/v1/documents.py`
- Create: `web/app/quarantine/*`（或数据集内 Tab）

**What:**
- 当 `drop_outline_only/drop_low_density` 等触发时，支持“不失败而隔离”，并在 UI 给出修复建议。

**Acceptance:**
- 隔离区支持批量审批；审批后自动走入库；丢弃有审计日志。

---

### Task 26：PII/Secrets 合规增强：规则包（policy pack）+ 阈值 gate + 脱敏审计与例外名单

**Files:**
- Modify: `app/rag/preprocessing/pii_anonymizer.py`
- Modify: `app/rag/preprocessing/secrets.py`
- Modify: `app/api/v1/pipeline.py`
- Modify: `web/components/data-governance-panel.tsx`

**What:**
- 支持按 dataset/tenant 配置 PII/Secrets 的阈值与动作（mask/token/quarantine）。

**Acceptance:**
- 治理预览能看到命中类型与数量；对敏感片段默认不展示原文（可控开关）。

---

### Task 27：页眉/页脚/样板的“学习模式”：跨文档发现候选 common lines，人工确认后一键写入 profile

**Files:**
- Modify: `app/rag/preprocessing/cleaning.py`
- Modify: `app/api/v1/pipeline.py`
- Modify: `web/components/data-governance-panel.tsx`

**What:**
- 用数据集级统计找出最常见的重复行（页眉/页脚/导航），避免靠猜正则。

**Acceptance:**
- UI 能展示候选行及出现比例；确认后生成对应规则并写入 profile。

---

### Task 28：URL 规范化与 canonical 去重：治理阶段写入 canonical_url 并作为去重键之一

**Files:**
- Modify: `app/rag/preprocessing/urls.py`
- Modify: `app/api/v1/documents.py`（元数据写入）
- Modify: `app/services/indexer.py`（去重键）

**What:**
- 解决“同一页面不同 tracking 参数/不同锚点”导致重复入库的问题。

**Acceptance:**
- Web crawl / url_batch 的重复率下降；重复被跳过时能解释原因（canonical 相同）。

---

### Task 29：文档生命周期治理：保留期/自动归档/到期删除/Legal Hold（按数据集配置）

**Files:**
- Create: `app/models/retention_policy.py`
- Modify: `app/api/v1/datasets.py`
- Modify: `app/tasks/jobs.py`
- Modify: `web/app/settings/*`（或 dataset 设置）

**What:**
- 让知识库具备基本的数据生命周期能力，适配企业合规场景。

**Acceptance:**
- 到期文档自动归档或删除（可配置）；Legal Hold 可阻止删除并留痕。

---

### Task 30：治理/入库报告中心：一键导出“质量报告 + 合规报告”（含 pipeline 版本快照）

**Files:**
- Create: `app/api/v1/reports.py`
- Create: `app/services/report_service.py`
- Create: `web/app/reports/*`

**What:**
- 把 chunk stats、治理 stats、PII/Secrets、失败/隔离、连接器 run 等聚合成可交付报告。

**Acceptance:**
- 报告可按 dataset/pipeline_hash 过滤；导出 JSON + HTML（便于分享/交付）。

