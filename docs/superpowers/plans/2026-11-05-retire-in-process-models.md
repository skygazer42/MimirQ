# Retire in-process models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 API 内的神经模型推理及本地 CLIP 图片向量检索，保留服务调用、轻量检索和其他图片能力。

**Architecture:** 在实际 provider 所有者退出本地实现，输入和运行时边界拒绝旧选项。现有 HTTP 模型接口与 OCR、BM25 所有者继续工作，前端选择与 CI 依赖同步收窄。

**Tech Stack:** Python、FastAPI/Pydantic、React/Next.js、既有 pytest/Vitest、pip requirements。

**Spec:** [.agents/notes/implemented/architecture/2026-11-05-retire-in-process-models.md](../../../.agents/notes/implemented/architecture/2026-11-05-retire-in-process-models.md)

## Global Constraints

- 用户明确退出本地 CLIP 图片向量检索，保留上传、预览、OCR、模型看图对话。
- 保留远程模型客户端、BM25/jieba、ONNX OCR 和独立解析容器。
- 不静默替换旧模型或向量空间；旧 local/HanLP/SPLADE/HF 选择明确失败。
- 不删除现有数据，不启动模型/解析服务，不卸载原环境，不改无关重构。
- 当前工作树已同步主项目至 75e36e7c4；最新集成基线 a9b2eb54a01d40fee32596642bee6752af03dcc1，保留其图谱和分块预览变更。

## Review Focus

- 持久配置、数据集覆盖和模型工厂绕过前端校验：旧 local provider 必须在实际选择边界失败。
- fallback 把已退出 SPLADE/HF 变成确定性检索：退出错误不能被吞掉。
- 图片引用辅助函数与向量代码共处：删除索引不能破坏上传、引用和模型看图。
- 关键词 auto 依赖包是否安装：统一采用 jieba，保留可观察的实际失败。
- 前端保留已退出值与新候选不一致：显示旧值和可修正错误，不自动换模型保存。

### Task 1: Retire local execution throughout the actual configuration and request chain

**Files:**

- Modify/delete actual owners in `app/rag/embedding/`, `app/rag/reranker/`, `app/rag/retrieval/sparse.py`, `app/rag/retrieval/colbert_ann.py`, `app/rag/preprocessing/keyword.py`.
- Modify actual callers in `app/core/`, `app/api/`, `app/services/`, `app/rag/engine_support/`, `app/parsing/`, and related feature configuration.
- Modify frontend provider/keyword selectors in `web/app/settings/`, `web/components/knowledge/`, `web/components/pipeline-options-panel.tsx`, `web/lib/` and generated contract types.
- Delete `requirements-local-models.txt`; update CI, audit, documentation and related existing tests.

**Interfaces:**

- Consumes: current provider/config factory contracts and service-based model clients.
- Produces: a service-only neural model boundary with explicit retired-selection errors and no CLIP vector index/query path.

- [x] Record focused baseline and write failing behavior checks for old provider requests.
- [x] Delete local Embedding/CrossEncoder/BGE/HanLP implementations and clean actual selectors/validators.
- [x] Remove SPLADE/HF ColBERT implementation and configuration branches, preserving deterministic test contracts.
- [x] Remove CLIP indexing/query and keep image upload/OCR/citation/multimodal owners; reject retired interface/config explicitly.
- [x] Clean frontend choices, local dependency/wheel installation, documentation and generated types.
- [x] Run focused integration, type/static checks and independent review; fix concrete findings.
- [x] Complete decision record, commit reviewable work and transfer only task changes to E:/MimirQ.
