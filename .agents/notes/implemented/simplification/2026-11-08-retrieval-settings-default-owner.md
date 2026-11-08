# Agent Note: Retrieval Settings defaults belong to their declarations

Status: implemented

## Problem

Retrieval consumers repeated Settings defaults using truthiness. Explicit zero values became unrelated literals: KG chunk weight zero became 0.25 despite the declaration's default 0.15, calibration zero became 0.7, and a zero multi-query cap became eight. Diagnostic snapshots also converted invalid missing required numbers into fabricated zero values.

## Decision

The bounded retrieval slice reads declared non-Optional Settings directly. Its 181 replacements cover 99 fields whose types and default expressions are verified against `config.py`. The slice includes `rag/retrieval`, the KG diagnostics snapshot in evaluations, and PDF preprocessing's sample-page setting. No declaration, environment example or deployment default changes.

Existing request override precedence, domain minimums/maximums and text normalization remain. Boolean combinations expressing forced multi-query experiments or policy enablement remain logical OR operations. This extends [direct value contracts](2026-11-07-direct-value-contracts.md) and follows [undeclared Settings probes](2026-11-08-remove-undeclared-settings-probes.md); it does not introduce probes or fields.

The global scan exceeds the agreed 60-location threshold. Candidates outside this slice, including Optional and getattr forms, remain listed for later boundary decisions. No `is None` branch is added here because every changed field already excludes None and owns its default.

## Alternatives considered

- Replace `or` with `is None` checks everywhere: this preserves zero but adds a missing-value policy to fields whose declarations forbid missing values.
- Change configuration defaults to match old consumer literals: this would alter the declared contract and environment documentation rather than removing duplicate defaults.
- Delete every OR containing a Settings read: this would remove real experiment/policy combinations and request precedence.

## Consequences

Explicit zero reaches existing domain constraints rather than selecting a second default. Zero KG boost/calibration/cap values retain their intended disabling or zero-budget meaning. A missing required evaluation value no longer creates a zero-valued snapshot; the existing optional snapshot failure handler owns that injected failure.

Representative runtime tests fail before the change and pass afterward, including zero/False settings and the real KG boost phase. Evaluation `or 0` already preserved valid zero; that test remains a passing control, while fault injection of None detects its former fabricated snapshot. Whole-module AST comparison verifies all 21 source files differ only by the approved fallback removals, apart from formatting. Tests do not execute every consumer or invoke parser/model services. Full per-location declaration mappings and deferred candidates live in the plan ledger.
