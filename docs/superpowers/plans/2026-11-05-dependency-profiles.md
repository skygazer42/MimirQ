# Optional dependency profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 默认 API 安装不携带本地 Torch 推理和 Chroma/FAISS，显式安装保留已有可选功能。

**Architecture:** 基础 requirements 保持既有核心服务依赖，可选 requirements 引用基础配置。Docker、现有 Compose、CI 和审计选择实际需要的配置，不增加运行时回退或修改检索行为。

**Tech Stack:** Python 3.11/3.12、pip requirements、Docker Compose、GitHub Actions。

**Spec:** [.agents/notes/implemented/process/2026-11-05-optional-model-vector-dependencies.md](../../../.agents/notes/implemented/process/2026-11-05-optional-model-vector-dependencies.md)

## Global Constraints

- 保留现有依赖版本、默认 Milvus 与远程 Embedding 配置。
- HanLP 和 Accelerate 随本地模型拆出，防止间接引入 Torch。
- 保留 rank-bm25 及其知识库、聊天记忆调用。
- 不安装/启动模型、解析服务或完整容器栈，不卸载原开发环境。
- 使用已批准方向在当前会话执行；只转移本次明确文件的改动到原工作区。

## Review Focus

- 某个间接依赖重新引入 Torch：完整解析基础依赖图核查。
- lite/retrieval-dev 仍默认 Chroma：Compose 必须选择包含 Chroma 的镜像配置。
- CPU wheel 与固定安全版本漂移：既有 wheel 契约跟随本地模型配置。
- FAISS 专用 CI 缺包：原有 FAISS 作业显式安装 FAISS 配置。
- 修改文件不能缩小已安装环境：文档说明使用新环境验证，不能声称已节省实际磁盘空间。

### Task 1: Split installation profiles and update their actual consumers

**Files:**
- Modify: `requirements.txt`, `docker/Dockerfile`, `docker/docker-compose.yml`, `docker/docker-compose.lite.yml`, `docker/docker-compose.retrieval-dev.yml`, `Makefile`, `scripts/audit.ps1`.
- Create: `requirements-local-models.txt`, `requirements-chroma.txt`, `requirements-faiss.txt`, `requirements-ci.txt`.
- Modify: `.github/workflows/ci.yml`, `.github/workflows/api-docs.yml`, `docs/guides/dependencies.md`.
- Test: existing `tests/test_dependency_audit_contract.py`, `tests/test_ci_workflow_contracts.py`.

**Interfaces:**
- Consumes: existing pinned requirement versions, CPU wheel manifest, existing Compose backend defaults.
- Produces: standalone optional requirements profiles and Docker `REQUIREMENTS_FILE` build argument.

- [x] Record existing contract-check baseline and the approved installation boundary.
- [x] Update existing dependency contracts first; verify the default-heavy configuration fails the new installation boundary.
- [x] Move model/local-vector packages into explicit profiles; preserve the original version pins.
- [x] Remove mandatory Torch installation from the default image and documentation CI; wire actual CI/Compose consumers and audit coverage.
- [x] Rewrite installation guidance and complete the Agent Note.
- [x] Resolve the complete core graph for Linux 3.11 and Windows 3.12; verify excluded packages stay absent.
- [ ] Run relevant contract/static/note/Compose checks, inspect the final diff, and request one fresh code review.
- [ ] Transfer only reviewed task files into the original checkout, preserving concurrent work.
