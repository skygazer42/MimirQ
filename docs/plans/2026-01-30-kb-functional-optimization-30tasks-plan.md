# KB Functional Optimization (30 Tasks) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不推翻现有架构（FastAPI + Postgres + Milvus + MinIO + Next.js）的前提下，围绕“可视化可解释 / 解析可回溯 / 入库可控 / 治理可合规 / 数据可运营”，完成 30 条可执行任务，显著提升知识库质量与可用性。

**Architecture:** 以现有 `Parse → Governance → Chunk → Index` 为主线；优先补齐 **可配置（profile/policy）+ 可审计（timeline/log）+ 可视化（diff/metrics）** 的闭环，确保每一步都能被定位、对比、回滚与复现。

**Tech Stack:** Backend: FastAPI, SQLAlchemy, LangChain/LangGraph, Milvus, Postgres, MinIO, Redis. Frontend: Next.js (App Router), Tailwind/shadcn, pdfjs-dist, vitest.

---

## Repo / Execution Setup

- Worktree branch: `kb-opt-2026-01-30` (path: `.worktrees/kb-opt-2026-01-30/`)
- Python: use venv python: `./.venv/bin/python`
- Baseline verification: `./.venv/bin/python -m pytest -q` (should be green before starting each wave)

---

## External Rules (Web Research → Implementation Heuristics)

- Markdown chunking: split by heading hierarchy and preserve header context (LangChain `MarkdownHeaderTextSplitter`).  
  Ref: https://python.langchain.com/docs/how_to/markdown_header_metadata_splitter/
- Markdown structure split (optional): use a syntax-aware splitter to preserve code/list blocks (LangChain `ExperimentalMarkdownSyntaxTextSplitter`).  
  Ref: https://python.langchain.com/api_reference/text_splitters/markdown/langchain_text_splitters.markdown.ExperimentalMarkdownSyntaxTextSplitter.html
- General text chunk defaults (tokens): LlamaIndex `SentenceSplitter` defaults are a practical baseline (`chunk_size=1024`, `chunk_overlap=200`).  
  Ref: https://docs.llamaindex.ai/en/stable/api_reference/node_parsers/sentence_splitter/
- Semi-structured long docs: Unstructured chunking supports title-aware strategies and char-based thresholds (`max_characters`, `new_after_n_chars`, `combine_text_under_n_chars`).  
  Ref: https://unstructured.readthedocs.io/en/latest/core/chunking.html
- Hybrid retrieval fusion: use Reciprocal Rank Fusion (RRF) as a stable, explainable rank-fusion method when combining BM25 + vector results.  
  Ref: https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking

These rules are used to: (1) set safer defaults, (2) improve auto routing, (3) provide UI guidance and exportable reports.

---

## Execution Discipline (TDD + Small Commits)

For each task:
1) Add/adjust a *failing* test (or confirm an existing test fails for the right reason)
2) Run the smallest verification command
3) Implement minimal code to pass
4) Re-run verification
5) Commit (one task = one commit, unless the task is purely docs)

---

## The 30 Tasks (Backlog → Implement in Waves)

This plan follows the existing roadmap:
- Reference: `docs/plans/2026-01-29-kb-functional-optimization-roadmap.md`
- Detailed wave plan (first 20 tasks): `docs/plans/2026-01-29-kb-20-tasks-wave-plan-12345.md`

### Task 1: Gap Analysis (竞品对标 → 模块映射 → 优先级)
**Files:** `docs/plans/2026-01-30-kb-gap-analysis.md` (new) / reuse `docs/plans/2026-01-29-kb-gap-analysis.md`

### Task 2: Chunk Preview (PDF box 高亮 + offset 双定位)
**Files:** `web/components/chunk-preview/*`, `web/components/parsing/pdf-viewer.tsx`, `app/api/v1/documents.py`

### Task 3: Chunk 质量仪表盘 (length/coverage/overlap/gap + export)
**Files:** `web/components/chunk-preview/*`, `web/components/chunk-preview/utils/export.ts`, optional backend stats

### Task 4: 治理 Diff 解释器 (rule attribution + impact stats)
**Files:** `web/components/data-governance-panel.tsx`, `app/api/v1/pipeline.py`, preprocessing stats

### Task 5: 解析对比工作台 (多解析器 A/B 输出对比)
**Files:** `web/app/parsing/page.tsx`, `app/api/v1/pipeline.py`

### Task 6: Dataset Health Dashboard (聚合指标 + 建议 + export)
**Files:** `app/api/v1/datasets.py` (or new), `app/services/*metrics*`, `web/app/datasets/[id]/health/*`

### Task 7: Connector Run 监控 (进度/错误聚类/重试/产物列表)
**Files:** `app/api/v1/connectors.py`, `app/models/connector*.py`, `web/app/*connectors*`

### Task 8: 文档血缘时间线 (timeline)
**Files:** `app/api/v1/documents.py`, `web/components/document-detail-dialog.tsx`

### Task 9: 解析质量 Gate 2.0 (统一评分 + reasons/evidence + fallback)
**Files:** `app/parsing/quality/*`, `app/parsing/factory.py`, `app/api/v1/pipeline.py`

### Task 10: 解析产物统计写入 (page/table/image/blocks)
**Files:** `app/models/document.py`, `app/parsing/*`, `web/app/parsing/*`

### Task 11: 表格闭环 (TAG: preview → route → retrieval)
**Files:** `app/storage/*`, `app/parsing/parsers/*`, docs

### Task 12: 图片理解 (OCR/Caption 可检索，默认保守)
**Files:** `app/parsing/enrich/*`, pipeline options

### Task 13: 多语言分句/分段鲁棒性 (中英混排/列表/代码块)
**Files:** `app/rag/chunking/strategies/semantic.py`, `app/rag/chunking/strategies/markdown.py`, tests

### Task 14: 解析缓存工程化 (file_sha256+backend+version)
**Files:** parsing pipeline cache layer, metadata keys, tests

### Task 15: 统一章节/标题元数据 (outline_path/header_path 一级字段)
**Files:** chunkers + `app/parsing/processors/processor.py` metadata normalization

### Task 16: 解析失败自助诊断 (按页采样 + 错误分类 + 一键重试)
**Files:** `app/api/v1/pipeline.py`, `web/app/parsing/*`

### Task 17: 数据集级 Ingestion Policy (defaults + versioning)
**Files:** `app/services/ingestion_policy.py`, `app/services/dataset_precheck_ingestion_suggestion.py`, UI apply

### Task 18: 批量上传 UX 2.0 (目录保留/元数据映射/并发重试)
**Files:** `web/components/upload/*`, backend upload endpoints

### Task 19: URL 入库增强 (sitemap/canonical/robots/readability)
**Files:** `app/services/web_crawler.py`, connectors, governance html profile

### Task 20: Connector 框架升级 (cron/增量/secret 轮换)
**Files:** connector configs + scheduler/worker

### Task 21: 新增 3-5 个连接器 (Confluence/Notion/GitHub/Drive/S3)
**Files:** new connector modules + UI

### Task 22: 入库去重闭环 (同文件/近重复/跨版本重复)
**Files:** precheck + ingestion dedup metadata + UI explain

### Task 23: pipeline_hash 再入库 (重切块/重嵌入/重建 BM25)
**Files:** async job + cancellation + rate limit

### Task 24: Governance Profile 管理 UI (CRUD + import/export + sandbox)
**Files:** `docs/plans/2026-01-29-governance-profiles-ui.md` (execute it)

### Task 25: Quarantine 工作流 (隔离区 + 人工复核/批准/丢弃)
**Files:** document status workflow + UI

### Task 26: PII/Secrets 合规增强 (policy pack + thresholds + audit + allowlist)
**Files:** governance pipeline + dataset policies + reports

### Task 27: 页眉/页脚/样板学习模式 (cross-doc candidates → confirm → write profile)
**Files:** preprocessing analyzer + UI approve flow

### Task 28: URL 规范化 + canonical 去重 (governance stage writes canonical_url)
**Files:** governance url normalization + metadata keys

### Task 29: 文档生命周期治理 (retention/legal hold)
**Files:** dataset config + scheduled jobs + UI

### Task 30: 报告中心 (质量报告 + 合规报告 + pipeline version snapshot)
**Files:** export endpoints + UI download center
