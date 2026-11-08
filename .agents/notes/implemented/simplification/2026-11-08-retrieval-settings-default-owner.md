# Agent Note: Settings defaults belong to their declarations

Status: implemented

## Problem

Retrieval consumers repeated Settings defaults using truthiness. Explicit zero values became unrelated literals: KG chunk weight zero became 0.25 despite the declaration's default 0.15, calibration zero became 0.7, and a zero multi-query cap became eight. Diagnostic snapshots also converted invalid missing required numbers into fabricated zero values.

## Decision

The bounded retrieval slice reads declared non-Optional Settings directly. Its 181 replacements cover 99 fields whose types and default expressions are verified against `config.py`. The slice includes `rag/retrieval`, the KG diagnostics snapshot in evaluations, and PDF preprocessing's sample-page setting. No declaration, environment example or deployment default changes.

Subsequent directory batches use the same declaration checks. Optional strings choose the literal default only for None; configured empty strings remain provided values. Configuration-validation presence checks and settings-to-settings precedence chains retain their original boolean meaning. Resource ceilings without a confirmed safe zero contract remain unchanged pending commander review. A zero redirect budget is safe and means no redirect hops, retaining the existing [0,20] bound.

Existing request override precedence, domain minimums/maximums and text normalization remain. Boolean combinations expressing forced multi-query experiments or policy enablement remain logical OR operations. This extends [direct value contracts](2026-11-07-direct-value-contracts.md) and follows [undeclared Settings probes](2026-11-08-remove-undeclared-settings-probes.md); it does not introduce probes or fields.

The first global scan exceeded the agreed 60-location threshold. The follow-up directory batches classify the remaining candidates in groups of at most 300. No `is None` branch is added for non-Optional fields; Optional/getattr forms are handled only after checking their actual declaration.

## Alternatives considered

- Replace `or` with `is None` checks everywhere: this preserves zero but adds a missing-value policy to fields whose declarations forbid missing values.
- Change configuration defaults to match old consumer literals: this would alter the declared contract and environment documentation rather than removing duplicate defaults.
- Delete every OR containing a Settings read: this would remove real experiment/policy combinations and request precedence.

## Consequences

Positive-minimum validators now inspect the actual zero instead of substituting a positive literal first. `RETRIEVAL_COMPACT_MIN_RECORDS`, `RETRIEVAL_OVERFETCH_MULTIPLIER` and `HIERARCHY_RECALL_OVERFETCH_FACTOR` therefore reject zero under their existing >=1 contracts. The former legacy-default validation test is intentionally updated; deployments using zero as an undocumented placeholder must provide a valid positive value. Genuine >=0/zero-disabled settings and empty-string presence checks keep their own contracts. Password length zero remains unresolved and retains the existing safety floor.

Explicit zero reaches existing domain constraints rather than selecting a second default. Zero KG boost/calibration/cap values retain their intended disabling or zero-budget meaning. A missing required evaluation value no longer creates a zero-valued snapshot; the existing optional snapshot failure handler owns that injected failure.

Representative runtime tests fail before the change and pass afterward, including zero/False settings and the real KG boost phase. Evaluation `or 0` already preserved valid zero; that test remains a passing control, while fault injection of None detects its former fabricated snapshot. Whole-module AST comparison verifies all 21 source files differ only by the approved fallback removals, apart from formatting. Tests do not execute every consumer or invoke parser/model services. Full per-location declaration mappings and deferred candidates live in the plan ledger.
API 可见性：MagicPDFConfig.device_mode schema 默认值与 config.py 空值声明对齐为 `""`，使 GET 未配置返回真实空值，PUT 不再静默写入 cpu。Optional 字符串的 `or ""` 与 strip 归一化是既定契约，后续批次不得改写成三元。
