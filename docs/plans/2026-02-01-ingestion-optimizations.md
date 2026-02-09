# Ingestion & RAG 可视化增强 + PaddleOCR-VL v1.5 集成 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 优化切块/解析/治理/入库分析与 RAG 可视化链路，并按现有外部服务方式升级 PaddleOCR-VL 到 v1.5，同时在设置页替换更一致的模型提供商图标。

**Architecture:** 维持 “Parse → Governance → Chunk → Index” 主流程不变；加强外部解析 ZIP 产物标准化；统一入库分析统计结构并在 Web 端可视化；扩充治理 rule packs 与自定义规则能力；补齐 RAG explainability 与观测入口。

**Tech Stack:** FastAPI + SQLAlchemy + LangChain/LangGraph；Next.js 14 + Tailwind + Recharts；外部解析服务（Docker）+ ZIP artifacts；可选 MinIO 图片托管。

---

## 执行约定（DRY）

- **分支/工作区**：在 worktree 分支 `feat/ingestion-optimizations` 上执行（已创建）。
- **TDD**：凡涉及行为/逻辑变更，按 Red → Green → Refactor；配置/文档类任务允许跳过测试但要跑校验命令。
- **验证命令（最小集）**：
  - 后端：`python -m pytest -q`（或针对单测文件）、`python -m compileall -q app`
  - 前端：`cd web; pnpm run lint && pnpm run typecheck && pnpm run ui-check`
- **提交粒度**：每个 Task 1 个 commit（必要时拆分为 “test” + “feat” 两个 commit）。

---

## Workstream A：PaddleOCR-VL v1.5（外部服务 + ZIP 产物标准化）

### Task 1: 为 PaddleVL 增加“版本/模式”配置字段（仅用于展示与可审计）

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/api/v1/settings.py`
- Test: `tests/test_settings_endpoints.py`

**Steps:**
1. 写测试：`GET /api/v1/settings` 返回 `paddle_vl` 配置字段（例如 `pipeline_version` / `mode`）。
2. 跑测试验证失败：`python -m pytest -q tests/test_settings_endpoints.py::test_settings_get_includes_url_ingest_and_governance`
3. 实现：在 SettingsResponse 中增加 `paddle_vl.pipeline_version`（默认 `v1.5`）与 `paddle_vl.mode`（默认 `doc_parser`），并在 `update_settings` 写入 env（可选）。
4. 跑单测：`python -m pytest -q tests/test_settings_endpoints.py`
5. Commit：`feat(settings): expose paddle_vl pipeline version`

### Task 2: paddle_vl parser-status 增强：探测外部服务 /health 版本信息（best-effort）

**Files:**
- Modify: `app/api/v1/settings.py`
- Test: `tests/test_settings_endpoints.py`

**Steps:**
1. 写测试：mock `requests.get(PADDLE_VL_API_URL.replace('/convert','/health'))`，断言 parsers["paddle_vl"].version 字段存在（或 message 增强）。
2. 跑测试失败。
3. 实现：仅当 `PADDLE_VL_ENABLED && PADDLE_VL_API_URL` 时进行短超时探测；失败不影响主请求（message 标注 `configured (health_unreachable)`）。
4. 跑单测通过。
5. Commit：`feat(settings): probe paddle_vl health metadata`

### Task 3: 升级 `docker/paddlevl` 依赖到 PaddleOCR doc_parser（v1.5）

**Files:**
- Modify: `docker/paddlevl/requirements.txt`
- Modify: `docker/paddlevl/Dockerfile`
- Modify: `docker/docker-compose.parsers.yml`
- Docs: `docs/guides/paddlevl_guide.md`

**Steps:**
1. 依赖更新：使用 `paddleocr[doc-parser]` + 固定 `paddlepaddle` 版本（跟随 PaddleOCR-VL v1.5 文档）。
2. 为服务增加 env：`PADDLE_VL_PIPELINE_VERSION=v1.5`、`PADDLE_VL_DEVICE=cpu|gpu`（仅服务侧使用）。
3. 更新 compose 注释与 healthcheck（仍然走 `/health`）。
4. 运行 Docker build（可选）：`docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile paddlevl build mimirq-paddlevl`
5. Commit：`chore(paddlevl): bump to PaddleOCR doc_parser v1.5`

### Task 4: `docker/paddlevl` 服务实现 doc_parser 推理 + ZIP 输出（保持 /convert 契约）

**Files:**
- Modify: `docker/paddlevl/server.py`
- (Optional) Add: `docker/paddlevl/README.md`

**Steps:**
1. 先写最小“无模型”单测（可选）：把核心“ZIP 打包 + 输出目录选择”做成纯函数并单测（避免引入真实模型）。
2. 实现：`POST /convert` 落盘 PDF → 调用 `paddleocr doc_parser -i input.pdf -o output --pipeline_version v1.5`（或 Python API `PaddleOCRVL`），然后将 output 目录打包为 ZIP 返回。
3. `/health` 返回 `{ ok: true, pipeline_version, mode }`。
4. 本地 smoke（可选）：容器内 `curl -F file=@sample.pdf http://localhost:9030/convert -o out.zip`。
5. Commit：`feat(paddlevl): doc_parser v1.5 convert api`

### Task 5: 后端新增 ZIP 归一化 helper（通用：md/json/images），并为 paddlevl 写单测

**Files:**
- Add: `app/parsing/utils/artifact_normalizer.py`
- Test: `tests/test_artifact_normalizer.py`

**Steps:**
1. 写 failing test：构造一个临时目录模拟 zip 解压结果（md + 嵌套 images），断言归一化后得到 `result.md` + `images/` +（可选）`result.json`。
2. 跑测试失败：`python -m pytest -q tests/test_artifact_normalizer.py`
3. 实现最小归一化：选择 md（复用 `ZipImageProcessor._choose_markdown_file`）、收敛图片到 `images/`、重写 md 引用（md/img tag）。
4. 跑测试通过。
5. Commit：`feat(parsing): add artifact normalizer for zip outputs`

### Task 6: `PaddleVLParser` 使用归一化 helper，并补齐 MinIO 图片上传（可选）

**Files:**
- Modify: `app/parsing/parsers/paddle_vl_parser.py`
- Test: `tests/test_paddle_vl_parser.py`

**Steps:**
1. 写 failing test：提供一个 zip bytes（fixture）包含 md+png；当 `MINIO_ENABLED=false` 时应剔除 image refs；当 `MINIO_ENABLED=true` 时应调用 `ZipImageProcessor.process_zip_with_images`（mock minio）。
2. 跑测试失败。
3. 实现：zip 分支走统一归一化；按 MinIO 开关处理图片。
4. 跑测试通过。
5. Commit：`refactor(parsing): normalize paddle_vl zip outputs`

### Task 7: UI：解析工作台展示 paddle_vl 的“服务模式/版本”（来自 settings/parsers）

**Files:**
- Modify: `web/app/parsing/page.tsx`
- Modify: `web/lib/parser-options.ts` (if exists)
- Verify: `web/package.json` scripts (lint/typecheck)

**Steps:**
1. UI 增加一个小 Badge：`PaddleOCR-VL v1.5`（仅当 available 且探测到版本）。
2. `cd web; pnpm run typecheck`。
3. Commit：`feat(web): show paddle_vl version badge in parsing`

### Task 8: 文档：更新 `paddlevl_guide.md`，明确 v1.5、性能与资源提示

**Files:**
- Modify: `docs/guides/paddlevl_guide.md`

**Steps:**
1. 补充：服务侧 env（pipeline_version/device）、输出 ZIP schema、建议配 MinIO 以便预览图片。
2. `python -m compileall -q app`（快速自检）。
3. Commit：`docs: update paddlevl v1.5 guide`

---

## Workstream B：切块（Chunking）质量与可视化增强

### Task 9: Chunk Preview 响应补齐“长度直方图/重叠浪费/覆盖率”结构（API）

**Files:**
- Modify: `app/api/v1/documents.py`
- Modify: `app/rag/chunking/*` (existing chunk stats)
- Test: `tests/test_chunk_preview.py`

**Steps:**
1. 写 failing test：调用 chunk-preview handler（或直接测 stats 计算函数），断言返回 `stats.histogram` 等字段。
2. 跑测试失败。
3. 实现：生成 buckets（chars/tokens 两套），并输出 `overlap_waste_ratio/coverage_ratio`。
4. 跑测试通过。
5. Commit：`feat(chunk-preview): add histogram + coverage stats`

### Task 10: Chunk Preview 增加 “quality gate reasons” 的可读化枚举（API）

**Files:**
- Modify: `app/api/v1/documents.py`
- Modify: `app/rag/preprocessing/diagnostics.py`
- Test: `tests/test_chunk_preview.py`

**Steps:**
1. 写 failing test：输入极端参数/文本触发 warn/fail，断言 reasons 结构稳定（code/message/severity）。
2. 实现 + 跑测试。
3. Commit：`feat(chunk-preview): stabilize quality gate reasons`

### Task 11: Web：Chunk Preview 增加直方图与关键指标卡（UI）

**Files:**
- Modify: `web/app/chunk-preview/page.tsx`
- Add/Modify: `web/components/charts/*`

**Steps:**
1. 使用 Recharts：展示 chunk 长度直方图（chars/tokens 切换）。
2. 指标卡：chunk_count / avg / p95 / overlap_waste_ratio / coverage_ratio。
3. `cd web; pnpm run lint && pnpm run typecheck`。
4. Commit：`feat(web): chunk preview histogram + stats`

### Task 12: Chunk Preview：A/B 对比增强（同一文件不同配置）输出 diff 摘要

**Files:**
- Modify: `app/api/v1/documents.py`
- Modify: `web/app/chunk-preview/page.tsx`

**Steps:**
1. 后端：对比接口/逻辑输出 `diff_summary`（chunk_count delta、avg/p95、overlap 估算）。
2. 前端：展示 delta chips。
3. Verify：`make verify`（或分步）。
4. Commit：`feat(chunk-preview): AB diff summary`

### Task 13: 新增“可复用 Chunk Preset”（团队默认参数）模型与 API

**Files:**
- Add: `app/models/chunk_preset.py`
- Add: `app/api/v1/chunk_presets.py`
- Modify: `app/api/v1/router.py`
- Test: `tests/test_chunk_presets.py`

**Steps:**
1. TDD：CRUD（list/create/update/delete），tenant-scoped。
2. Verify：`python -m pytest -q tests/test_chunk_presets.py`
3. Commit：`feat: add chunk presets api`

### Task 14: Web：Chunk Preset UI（选择/保存/导入导出）

**Files:**
- Add: `web/app/chunk-preview/presets/*` (or integrate in page)
- Modify: `web/app/chunk-preview/page.tsx`

**Steps:**
1. UI：Preset 下拉 + Save/Save As + Import/Export JSON。
2. Verify：`cd web; pnpm run typecheck`
3. Commit：`feat(web): chunk preset manager`

### Task 15: Chunk Strategy：新增 `markdown_outline`（按标题层级优先切分，保留 section path）

**Files:**
- Modify: `app/rag/chunking/*`
- Modify: `docs/guides/chunk_strategies.md`
- Test: `tests/test_chunk_strategies.py`

**Steps:**
1. TDD：给定 markdown（多级标题 + 段落），输出 metadata.header_path / outline_path。
2. 实现：优先在标题边界切，超长再按句子/段落兜底。
3. Verify：pytest。
4. Commit：`feat(chunking): add markdown_outline strategy`

### Task 16: Web：Chunk List 支持按 section 分组/过滤（复用现有 section breadcrumb）

**Files:**
- Modify: `web/app/chunk-preview/page.tsx`

**Steps:**
1. UI：Group=Section 与 Section filter 下拉（已有则完善）。
2. Verify：`pnpm run ui-check`
3. Commit：`feat(web): chunk list section grouping improvements`

---

## Workstream C：入库文档分析可视化（Parsing/Governance/Dataset Precheck）

### Task 17: 后端统一“文档画像”结构（DocumentAnalytics），可由 parsing/governance/chunk 阶段填充

**Files:**
- Add: `app/types/document_analytics.py`
- Modify: `app/parsing/processors/processor.py`
- Test: `tests/test_document_analytics.py`

**Steps:**
1. TDD：给定 markdown，输出 char/line/heading/table/image 统计、语言检测结果（可选）。
2. 实现：纯函数 + processor 注入。
3. Verify：pytest。
4. Commit：`feat(ingestion): add document analytics schema + computation`

### Task 18: 解析预览接口返回 analytics（解析前后对比：raw vs cleaned）

**Files:**
- Modify: `app/api/v1/documents.py` (preview/parse endpoints)
- Test: `tests/test_documents_preview.py`

**Steps:**
1. TDD：preview 响应包含 analytics.raw / analytics.cleaned。
2. 实现。
3. Verify：pytest。
4. Commit：`feat(api): include analytics in parse preview`

### Task 19: Web Parsing：展示 analytics 面板（指标卡 + 分布图）

**Files:**
- Modify: `web/app/parsing/page.tsx`
- Add: `web/components/analytics/*`

**Steps:**
1. UI：StatsGrid（chars/lines/pages/tables/images/blocks）+ 关键提示（scanned pdf / low density）。
2. Verify：`cd web; pnpm run typecheck`
3. Commit：`feat(web): parsing analytics panel`

### Task 20: Web Governance：clean-preview 增加“命中规则归因”可视化（default/pack/custom）

**Files:**
- Modify: `web/app/data-governance/page.tsx` (or relevant page)
- Modify: `app/api/v1/pipeline.py` (clean-preview already builds meta)

**Steps:**
1. 后端：clean-preview 输出 `rules_summary`（各 source 命中计数）。
2. 前端：显示堆叠条形图/列表。
3. Verify：`make verify`
4. Commit：`feat(governance): visualize rule attribution`

### Task 21: Dataset Precheck：把“代表性样本/问题分桶”增强为可视化仪表盘

**Files:**
- Modify: `web/app/datasets/[id]/precheck/page.tsx`
- Modify: `app/api/v1/precheck.py` (if needed)

**Steps:**
1. UI：文件类型分布、扫描件占比、长度分布、PII/Secrets 线索计数。
2. Verify：`pnpm run typecheck`
3. Commit：`feat(web): precheck dashboard enhancements`

### Task 22: 入库后文档详情页：增加“解析/治理/切块”溯源卡（pipeline_hash + 统计）

**Files:**
- Modify: `web/app/knowledge/page.tsx` (documents tab)
- Modify: `app/api/v1/documents.py` (document detail response)

**Steps:**
1. API：document detail 返回 pipeline snapshot（parser_backend/chunk_strategy/governance flags + analytics）。
2. UI：详情弹窗显示。
3. Verify：`make api-check`
4. Commit：`feat: show pipeline provenance in doc detail`

---

## Workstream D：文档治理规则扩展 + 可自定义规则

### Task 23: 扩充内置 rule packs（更贴近企业文档/网页导入）

**Files:**
- Modify: `app/rag/preprocessing/rule_packs.py`
- Test: `tests/test_governance_rule_packs.py`

**Steps:**
1. TDD：新增 pack keys（例如 `wechat_mp_noise` / `pdf_header_footer_cn` / `notion_export_noise`）并验证被 `build_governance_rules` 扩展。
2. Implement + pytest。
3. Commit：`feat(governance): add more rule packs`

### Task 24: API：列出 rule packs（用于 UI 下拉）

**Files:**
- Add: `app/api/v1/governance.py`
- Modify: `app/api/v1/router.py`
- Test: `tests/test_governance_rule_packs.py`

**Steps:**
1. TDD：`GET /api/v1/governance/rule-packs` 返回 key 列表。
2. Implement + pytest。
3. Commit：`feat(api): list governance rule packs`

### Task 25: UI：Data Governance Profiles 支持选择 rule packs + 管理 regex_rules（带校验/限制提示）

**Files:**
- Modify: `web/app/data-governance/profiles/*`
- Modify: `web/lib/api-client.ts`

**Steps:**
1. UI：rule packs multi-select；regex rule editor（pattern/repl/flags）+ 本地 compile 校验。
2. Verify：`pnpm run lint`
3. Commit：`feat(web): governance profile rule packs + regex editor`

### Task 26: Server-side：regex_rules 更强校验（长度/数量/危险模式）并返回结构化错误

**Files:**
- Modify: `app/core/validation/regex_safety.py` (or create)
- Modify: `app/api/v1/pipeline.py` / profiles endpoints
- Test: `tests/test_regex_safety.py`

**Steps:**
1. TDD：危险正则（嵌套量词）被拒绝；返回 400 与字段错误。
2. Implement + pytest。
3. Commit：`feat(security): harden regex rule validation`

---

## Workstream E：RAG 可解释性与可视化增强

### Task 27: 后端：统一 RAG trace 结构（retrieve/rerank/citations），并暴露给 history 详情

**Files:**
- Modify: `app/api/v1/conversations.py` (or history endpoints)
- Modify: `app/rag/core/*` (trace emit)
- Test: `tests/test_rag_trace_schema.py`

**Steps:**
1. TDD：trace schema（steps/timings/topk/citations_count）。
2. Implement + pytest。
3. Commit：`feat(rag): stabilize trace schema for visualization`

### Task 28: Web：History 详情页增加 “RAG Trace” 面板（检索→重排→引用）

**Files:**
- Modify: `web/app/history/page.tsx`
- Add: `web/components/rag-trace/*`

**Steps:**
1. UI：时间线 + TopK 列表 + 引用卡（可跳转到 chunk）。
2. Verify：`pnpm run typecheck`
3. Commit：`feat(web): rag trace panel in history`

### Task 29: Web：Graph 页面补齐“与真实检索一致”的路径分析（从 trace 回放）

**Files:**
- Modify: `web/app/graph/page.tsx`

**Steps:**
1. 增加导入 trace JSON 并回放高亮路径（不强依赖后端）。
2. Verify：`pnpm run lint`
3. Commit：`feat(web): graph trace replay`

---

## Workstream F：设置页 LLM 图标替换（LobeHub）

### Task 30: 引入 LobeHub 彩色 SVG 图标并落地到 `web/public/logos/`

**Files:**
- Add: `web/scripts/sync-lobehub-icons.mjs`
- Add: `web/public/logos/lobehub/*.svg`

**Steps:**
1. 脚本：从 `@lobehub/icons-static-svg`（或 unpkg）下载指定 provider 的 svg 并写入目录。
2. 运行：`node web/scripts/sync-lobehub-icons.mjs`（产物进入 git）。
3. Commit：`chore(web): add lobehub colored provider icons`

### Task 31: ProviderIcon 统一改为优先使用 LobeHub SVG（保留旧映射兜底）

**Files:**
- Modify: `web/components/provider-icon.tsx`
- Modify: `web/app/logos-preview/page.tsx`
- Verify: `web/scripts/check-design-tokens.mjs` (ui-check)

**Steps:**
1. 实现：providerId → iconName 映射（openai/anthropic/deepseek/qwen/…），默认 fallback。
2. Verify：`cd web; pnpm run lint && pnpm run typecheck && pnpm run ui-check`
3. Commit：`feat(web): switch provider icons to lobehub colored svgs`

### Task 32: Settings 页面：模型提供商卡片/弹窗使用新的 ProviderIcon 并统一尺寸/对齐

**Files:**
- Modify: `web/components/model-provider-card.tsx`
- Modify: `web/components/model-config-dialog.tsx`
- Modify: `web/app/settings/page.tsx`

**Steps:**
1. 对齐：44x44 touch target、focus ring、dark bg 可读性（按 ui-ux-pro-max）。
2. Verify：`pnpm run typecheck`
3. Commit：`feat(web): align provider icon usage in settings`

---

## 收尾：质量门禁与文档

### Task 33: 更新 `docs/guides/chunk_preview.md`（新指标/图表/AB diff）

**Files:**
- Modify: `docs/guides/chunk_preview.md`

**Steps:**
1. 补充字段说明与截图占位（可后补）。
2. Commit：`docs: update chunk preview guide`

### Task 34: 更新 `docs/guides/data_governance.md`（rule packs 与自定义规则 UI）

**Files:**
- Modify: `docs/guides/data_governance.md`
- Modify: `docs/data-governance-profiles.md`

**Steps:**
1. 补充 rule packs 列表与 profiles schema 示例。
2. Commit：`docs: expand governance rules docs`

### Task 35: 增加回归门禁：paddle_vl zip 归一化 fixtures（防止输出结构漂移）

**Files:**
- Add: `tests/fixtures/paddlevl/` (zip fixtures)
- Modify: `tests/test_paddle_vl_parser.py`

**Steps:**
1. 增加 2 个 fixture：旧 lite 输出 / 新 doc_parser 输出（最小化）。
2. pytest 验证解析稳定。
3. Commit：`test: add paddlevl fixtures for regression`

### Task 36: 运行全量自检（CI 一致）并修复发现的问题

**Files:**
- Modify: (as needed)

**Steps:**
1. `make verify`
2. `make enterprise-checks`（如果耗时过长可先跑后端 pytest + 前端 test）
3. Commit：`chore: enterprise checks`

---

## 额外增强（填满到 40 个任务，按需执行）

### Task 37: Chunk Preview “Retrieve” 面板补齐 reranker 模拟与可视化（本地/后端可选）

**Files:**
- Modify: `web/app/chunk-preview/page.tsx`
- Modify: `web/lib/retrieval-sim/*`

**Steps:** 同上（实现 + typecheck + commit）

### Task 38: Parsing：结构化 JSON 抽样页 bbox overlay（仅预览，不入库）

**Files:**
- Modify: `web/components/parsing/pdf-viewer.tsx`
- Add: `web/components/parsing/bbox-overlay.tsx`

**Steps:** 同上（实现 + typecheck + commit）

### Task 39: Governance：新增“自定义规则导出为 ingestion policy”按钮（闭环）

**Files:**
- Modify: `web/app/data-governance/page.tsx`
- Modify: `app/api/v1/pipeline.py`

**Steps:** 同上（实现 + verify + commit）

### Task 40: 发布准备：更新 CHANGELOG + 快速演示脚本（可复现）

**Files:**
- Modify: `CHANGELOG.md`
- Add: `scripts/demo_ingestion_flow.ps1` (Windows)
- Add: `scripts/demo_ingestion_flow.sh` (POSIX, optional)

**Steps:** 更新文档 + 验证脚本可跑 + commit

