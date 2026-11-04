# Agent Note: Shared scalar coercion owner

Status: implemented

## Problem

`common.py` exposed `_safe_int` and `_safe_float` alongside nearly identical `_coerce_optional_int` and `_coerce_optional_float`. The parallel helpers repeated conversion and clamping behavior, while callers had to infer whether the lower bound came from the helper or the call site.

## Decision

`common.py` keeps `_safe_int` and `_safe_float` as the shared numeric conversion owners. Callers pass their original default, minimum, and maximum explicitly. Missing and malformed optional numbers retain their existing fallback values; only standard numeric conversion failures (`OverflowError`, `TypeError`, `ValueError`) use those defaults. The typed LangChain `Document.id` field is read directly.

`kg_merge_boost._coerce_optional_int` remains local because it returns `None` for an absent metadata field; that is a different contract from a defaulting integer conversion. Its invalid-value path catches only standard numeric conversion failures.

Citation parse-quality summaries use the same standard numeric conversion error list. A malformed optional score tries the next declared metadata field; unexpected errors are not treated as missing metadata.

chunk 质量追踪的可选分数也使用相同的标准转换异常列表，意外失败继续交给既有追踪入口记录。其实际调用链与未接入模块的退出条件见[质量评分所有者](2026-11-05-chunk-quality-score-owner.md)。

## Alternatives considered

- Keep both common helper pairs: this avoids caller edits, but leaves two implementations of the same defaulting and clamping rules.
- Remove numeric defaults and let every malformed optional value fail: that would change the existing contract for JSON metadata and request state, beyond the goal of consolidating the owner.

## Consequences

Numeric defaults and bounds are visible at each call site, and shared conversion behavior has one implementation. Unexpected custom conversion exceptions are no longer silently normalized; the supported JSON and settings values use standard numeric types. Python tests were not run per user instruction.

## Verification

Ruff check, Ruff format --check, and `git diff --check` passed for the affected Python files. Static reference scanning confirmed the common optional wrappers have no remaining callers; Python tests and runtime retrieval checks were not run.
