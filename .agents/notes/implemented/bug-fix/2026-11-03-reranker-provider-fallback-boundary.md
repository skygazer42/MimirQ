# Agent Note: Reranker provider fallback boundary

Status: implemented

## Problem

Retrieval orchestration converted every factory exception into an identity reranker. The real factory reports an unknown provider with `ValueError`, so a misspelled or unsupported configuration could silently disable ranking. The registry also defines explicit disabled aliases and the reranker implementation is loaded lazily, so those two fallback cases still need handling.

## Decision

The orchestration shim maps an empty provider and the registry's `none` family aliases to identity directly. It also uses identity when lazy provider loading raises `ModuleNotFoundError`. Other factory errors propagate to the caller. Identity scoring reads the declared candidate fields in one pass; malformed numeric metadata maps to the existing `0.0` score only for standard numeric conversion errors.

## Alternatives considered

- Keep catching every exception: this preserves silent fallback for unsupported providers and invalid initialization values, which hides deterministic configuration errors.
- Remove identity fallback entirely: this would make the explicit disabled aliases and missing optional provider modules fail, changing their existing retrieval policy.

## Consequences

Invalid provider configuration is now visible to retrieval callers. Disabled reranking and missing optional provider modules keep the existing identity result and `fallback=identity` marker. The remaining fallback is limited to those named conditions; Python tests and model-runtime checks were not run per user instruction.

[混合检索排名整理](../simplification/2026-11-05-hybrid-ranking-owned-values.md)保持这里的工厂、禁用别名和 provider 失败归属，只调整排名内部记录与重复赋值。

[检索编排内部记录](../simplification/2026-11-05-retrieval-orchestration-owned-values.md)保留这里的工厂与回调错误归属，原始 provider 分数继续转换，仅清理本地已归一化的记录和计数。

## Verification

Ruff check, Ruff format --check, and `git diff --check` passed for the shim and its direct hybrid caller. Static inspection confirmed unknown providers raise in the real factory and disabled aliases are gated before the hybrid factory call. Python tests were not run.
