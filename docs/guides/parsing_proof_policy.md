# Parsing Proof Policy

## Purpose

`parsing-proof` artifacts exist to answer one question:

Does stronger parsing materially improve downstream retrieval and extraction behavior in a deterministic, reviewable way?

This policy defines how the repo treats those artifacts, who should update them, and when informational checks may be promoted into blocking gates.

## Current Scope

The current parsing-proof surface covers sample deterministic cases derived from the broader parsing corpus:

- table continuity and table retrieval
- layout-sensitive retrieval
- cross-page table extraction evidence

Current execution surfaces:

- `make parsing-proof-sample`
- `scripts/run_sample_parsing_retrieval_proof.py`
- `scripts/run_parsing_retrieval_proof_batch.py`
- `scripts/build_parsing_retrieval_proof_artifacts.py`
- `scripts/parsing_retrieval_proof_gate.py`
- `scripts/diff_parsing_retrieval_proof_summaries.py`

## Artifact Contract

The broader parsing-proof sample currently emits:

- `parsing_proof_batch.spec.json`
- per-case `*.fixture.json`
- per-case `*.report.json`
- `batch.report.json`
- `rollout.json`
- `summary.json`
- `report.json`
- `gate.json`
- `diff.json`
- `diff.md`
- `review.md`

Schemas:

- `mimirq.parsing_retrieval_proof_batch.v1`
- `mimirq.parsing_retrieval_proof_batch_report.v1`
- `mimirq.parsing_retrieval_proof_summary.v1`
- `mimirq.parsing_retrieval_proof_report.v1`
- `mimirq.parsing_retrieval_proof_gate_report.v1`
- `mimirq.parsing_retrieval_proof_diff.v1`

## Ownership

Recommended ownership model:

- Parsing owner:
  Responsible for parser behavior, fixture evolution, and broader corpus additions.
- Retrieval owner:
  Responsible for retrieval benchmark semantics and proof-query quality.
- Release/quality owner:
  Responsible for deciding whether an informational parsing-proof signal should become a gate.

The repo does not currently encode personal owners in code. Treat these as role responsibilities, not named individuals.

## Baseline Update Rules

Baseline file:

- `ci/parsing_retrieval_proof_summary_baseline.v1.json`

Rollout policy file:

- `ci/parsing_retrieval_proof_rollout.v1.json`

Only update the baseline when at least one of these is true:

1. The broader sample corpus changed intentionally.
2. The proof semantics changed intentionally.
3. A parser improvement intentionally changes the expected deterministic proof outcome.

Do not update the baseline only to silence regressions.

Every baseline update should include:

- why the expected proof output changed
- whether the change reflects parser behavior, retrieval semantics, or fixture design
- what command or workflow produced the new baseline candidate

## Informational vs Blocking

Current state:

- `parsing-proof` is informational
- CI and `rag-quality-gate` publish artifacts
- `gate.json` exists, but does not fail the workflow

Promotion from informational to blocking should require all of the following:

1. The sample corpus is considered stable for at least one full release cycle.
2. Owners agree the proof cases represent real downstream risk, not only convenience checks.
3. The baseline update process is documented and socially enforced.
4. The thresholds are shown to be low-noise across repeated runs.

## Threshold Guidance

Current sample thresholds:

- `hit_at_k_mean >= 1.0`
- `mrr_mean >= 1.0`

These are acceptable only because the current sample set is tiny and deterministic.

If the corpus broadens:

- expect thresholds to relax or become slice-specific
- consider separate levels:
  - informational threshold
  - soft fail / warn threshold
  - hard fail threshold

## Review Expectations

When a parsing-proof diff changes:

1. Read `rollout.json` to confirm the current stage and next promotion target.
2. Read `summary.json`
3. Read `report.json`
4. Read `review.md`
5. Read `diff.json` and `diff.md`
6. Determine whether the change is:
   - intentional parser improvement
   - fixture drift
   - retrieval semantics drift
   - regression

## Near-Term Policy

Near-term recommendation:

- keep the broader parsing-proof sweep non-blocking
- require artifact publication in CI and dedicated workflow
- review diffs when parser, retrieval, or fixture logic changes

## Future Promotion Path

Recommended path to stricter enforcement:

1. Expand the broader proof case set modestly.
2. Track several cycles of stable artifact output.
3. Introduce a PR comment or release-note summary from `diff.md`.
4. Only then consider a warning gate.
5. Consider a fail gate last.
