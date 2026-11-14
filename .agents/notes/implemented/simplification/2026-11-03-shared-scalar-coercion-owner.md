# Agent Note: Shared scalar coercion owner

Status: implemented

## Problem

`common.py` exposed `_safe_int` and `_safe_float` alongside nearly identical `_coerce_optional_int` and `_coerce_optional_float`. The parallel helpers repeated conversion and clamping behavior, while callers had to infer whether the lower bound came from the helper or the call site.

## Decision

`common.py` keeps `_safe_int` and `_safe_float` as the shared numeric conversion owners. Callers pass their original default, minimum, and maximum explicitly. Missing and malformed optional numbers retain their existing fallback values; only standard numeric conversion failures (`OverflowError`, `TypeError`, `ValueError`) use those defaults. The typed LangChain `Document.id` field is read directly.

原始解析 metadata 的可选整数和浮点数使用独立的 `app.parsing.utils.scalars` 所有者。该边界拒绝 `None` 与 bool，整数使用原 `int` 规则，浮点继续过滤 NaN；只有 `OverflowError`、`TypeError`、`ValueError` 转换失败返回 `None`，自定义数值协议的意外异常继续传播，不伪装成缺失。它不引入检索层的默认值或上下限。

质量门禁与文档评分的同义布尔解析使用该模块的 `coerce_bool`，保留实际布尔、缺失与原字符串集合的规则。文档评分的浮点入口仍独立：其历史合同允许 bool 参与 0／1 评分，不能替换为拒绝 bool 的共享浮点入口。两处原始边界的差异保持，不为统一函数名改变分数。

质量门禁[内部结果的所有权](2026-11-13-parse-quality-decision-owner.md)只收窄已构造记录，不改变这里的原始标量解析职责。

`kg_merge_boost._coerce_optional_int` remains local because it returns `None` for an absent metadata field; that is a different contract from a defaulting integer conversion. Its invalid-value path catches only standard numeric conversion failures.

Citation parse-quality summaries use the same standard numeric conversion error list. A malformed optional score tries the next declared metadata field; unexpected errors are not treated as missing metadata.

chunk 质量追踪的可选分数也使用相同的标准转换异常列表，意外失败继续交给既有追踪入口记录。其实际调用链与未接入模块的退出条件见[质量评分所有者](2026-11-05-chunk-quality-score-owner.md)。

[混合检索排名的内部记录](2026-11-05-hybrid-ranking-owned-values.md)沿用原始输入在边界解析的原则，仅清理已构造记录的重复转换；其既有数值失败区别保持。

[语料与索引内部值](2026-11-05-retrieval-corpus-owned-values.md)保留可变 Settings、原始向量与持久化文件的转换，只收窄真实索引记录和本地生成值的访问。

[安全、反馈与行业规则](2026-11-05-policy-feedback-owned-values.md)沿用归一化边界原则，保留空匹配结果分数和原始反馈、YAML、元数据的转换，只清理实际生产者已确定的内部值。

## Alternatives considered

- Keep both common helper pairs: this avoids caller edits, but leaves two implementations of the same defaulting and clamping rules.
- Remove numeric defaults and let every malformed optional value fail: that would change the existing contract for JSON metadata and request state, beyond the goal of consolidating the owner.

## Consequences

Numeric defaults and bounds are visible at each call site, and shared conversion behavior has one implementation. Unexpected custom conversion exceptions are no longer silently normalized; the supported JSON and settings values use standard numeric types. Python tests were not run per user instruction.

## Verification

Ruff check, Ruff format --check, and `git diff --check` passed for the affected Python files. Static reference scanning confirmed the common optional wrappers have no remaining callers; Python tests and runtime retrieval checks were not run.
