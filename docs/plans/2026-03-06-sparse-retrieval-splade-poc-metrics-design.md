# Sparse Retrieval（SPLADE POC）— Metrics + Regression Gate Design

Date: 2026-03-06

## 背景

MimirQ 检索栈已有一个可选的 sparse retrieval channel（SPLADE-style），并提供：
- `deterministic` provider：用于单测/离线回归（无模型下载）
- `splade` provider：面向生产实验（HF/transformers，需显式配置模型）
- 可选落盘的 scope-index（best-effort），用于跨重启冷启动加速

该通道默认关闭，目标是以最小风险引入“额外召回来源”，与 dense/BM25/lexical 一起参与融合。

## 目标（Wave26‑T31）

1) Feature-flagged：默认关闭；开启需要显式 opt-in  
2) Metrics：可观测、可诊断（不引入高基数/PII）  
3) Rollback：出现成本/错误/效果不佳时可快速回退  
4) Regression evaluated：提供可回归的验证入口，确保 plumbing 不会“看起来能跑但不可 gate”

## 方案

### 1) Prometheus 指标（PII-safe / 低基数）

新增 sparse 通道指标（仅 `PROMETHEUS_ENABLED=true` 时生效）：
- Search：
  - `rag_sparse_search_total{provider,outcome}`
  - `rag_sparse_search_duration_seconds{provider,outcome}`
  - `rag_sparse_search_candidates_count{provider,outcome}`
- Index：
  - `rag_sparse_index_load_total{provider,outcome}`（`hit|miss|error|skipped`）
  - `rag_sparse_index_save_total{provider,outcome}`（`ok|error|skipped`）
  - `rag_sparse_index_build_duration_seconds{provider,kind,outcome}`（`kind=full|incremental`）

Labels 只包含 `provider` 和少量 `outcome/kind`，避免 tenant/query/document 等高基数信息。

### 2) Instrumentation points（best-effort）

- `_search_sparse`：记录每次 sparse 检索调用的耗时、候选数、以及“是否尝试从落盘索引 load”及其 hit/miss/error。
- `_build_sparse_index`：记录 full build 耗时 + save outcome。
- `_upsert_sparse_index_incremental`：记录增量 upsert 耗时 +（可选）load/save outcome。

### 3) Regression evaluated（不依赖模型下载）

添加一个 retrieval gate smoke test：
- 构造一个 BM25 会被 distractors 填满而 reference chunk 不在 top_k 的用例
- sparse 开启时走 `splade` provider 路径，但通过 monkeypatch 注入 fake encoder，确保 sparse 能召回 reference
- 通过 `budgeted_rrf` 的 per-instance budgets（bm25:4, sparse:1）保证 sparse 对可见 Top‑K 的贡献可被 gate

该测试验证：sparse 是 feature-flagged 的、且在 CI/单测环境可稳定回归。

## Rollback Playbook（配置）

1) 关闭 sparse：`SPARSE_RETRIEVAL_ENABLED=false`  
2) 降级 provider：`SPARSE_RETRIEVAL_PROVIDER=deterministic`  
3) 禁用落盘缓存：`SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED=false`  
4) （可选）清理 `SPARSE_RETRIEVAL_INDEX_DIR` 历史文件（只影响冷启动性能，不影响 correctness）

