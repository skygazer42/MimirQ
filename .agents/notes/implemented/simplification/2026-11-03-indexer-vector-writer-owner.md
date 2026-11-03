# Agent Note: Indexer vector-writer ownership

Status: implemented

## Problem

`indexer.py` 与 `app/services/indexing/vector_writer.py` 同时维护 shadow 向量配置、writer 缓存、embedding-space hash 和双写流程。两份实现容易在配置解释、失败策略和指标记录上分叉；索引器还保留了指向已迁移 helper 的调用。

## Decision

`app.services.indexing.vector_writer` 是向量写入与 Milvus 模式判断的唯一 owner。`indexer.py` 和 `chunks.py` 直接调用公开的 `milvus_backend_enabled`、`dataset_scoped_runtime_unavailable` 与 `dual_write_shadow_vectors_best_effort`。

Shadow embedding-space hash 计算失败时，记录 warning 并将可选 shadow writer 缓存为不可用；主向量写入仍可成功。不可用 hash 不会作为空字符串写入 shadow metadata。该缓存沿用配置签名边界，配置变化后重新解析。

## Alternatives considered

- 保留 `indexer.py` 中的副本或再加一层转发：调用仍有多个 owner，配置和失败策略可能继续漂移，因此不采用。
- hash 失败时返回空字符串并继续双写：这会把无法识别的 embedding space 写成有效 shadow 记录，因此不采用。

## Consequences

向量写入配置、runtime 错误类型和可选双写只有一个维护点，主索引流程不依赖 shadow 写入成功。hash 计算异常会停用该配置签名对应的 shadow writer，直到配置签名变化；当前验证是静态检查，Python 测试和运行时流程按用户要求未执行。

## Verification

Ruff check、Ruff format --check、`git diff --check` 与 helper owner 引用扫描通过；未运行 Python tests、导入应用或调用数据库／向量库。
