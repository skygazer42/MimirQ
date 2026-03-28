# MimirQ-w1wo DSPy / Prompt Optimization Workflow Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define a practical DSPy-based workflow for improving MimirQ prompts and prompt-backed retrieval policies offline, without introducing DSPy into the live request path first.

**Architecture:** Use DSPy as an offline optimizer sitting on top of existing MimirQ evaluation assets. Candidate prompts should be generated, scored, and promoted through the current versioned prompt/policy hooks such as query rewrite strategies, rather than replacing the runtime orchestration layer.

**Tech Stack:** Python, DSPy, existing retrieval regression bundles, query rewrite strategy registry, adaptive routing configs

---

## Current MimirQ Baseline

Relevant repo anchors:

- `app/rag/core/query_rewrite_strategy.py`
  Query rewrite already has versioned strategy ids and hashes, which is exactly the kind of stable promotion surface DSPy needs.
- `app/rag/retrieval/orchestrator.py`
  Rewrite, decomposition, adaptive routing, KG injection, and evidence diagnostics are already bounded and instrumented.
- `docs/guides/public_benchmarks_zh.md`
  Public benchmark and regression bundle workflows already exist.
- `tests/test_multilingual_recall_regression.py`
  There is already a lightweight multilingual regression slice, which is useful as a stable guardrail.
- `app/services/dataset_profile_service.py`
  Dataset/profile slices can be reused for evaluation cohorts and hard-case bucketing.

Key implication:

- MimirQ already has the pieces needed to evaluate prompts.
- What is missing is a disciplined loop for optimizing and promoting prompt candidates.

## Options Compared

| Option | Description | Upside | Main drawback | Recommendation |
| --- | --- | --- | --- | --- |
| A | Manual prompt editing only | Lowest tooling cost | Slow, anecdotal, hard to reproduce | Keep as baseline, not enough alone |
| B | DSPy offline optimization feeding versioned prompt strategies | Reproducible experiments; can use existing eval suites; low runtime risk | Requires harness work and careful anti-overfitting discipline | Recommended |
| C | DSPy inside the live request path | Maximum automation | Higher latency, more complexity, hard to debug, not justified yet | Reject for first phase |

## Recommendation

Use DSPy only offline in the first phase.

The workflow should look like this:

1. Select a bounded prompt family to optimize.
2. Train/optimize on existing retrieval or evidence tasks.
3. Produce a candidate prompt/template plus metrics report.
4. Promote the winner manually into MimirQ's existing versioned strategy hooks.
5. Re-run normal regression gates before any rollout.

This is materially enough to satisfy the issue because it turns DSPy from "interesting idea" into an operational optimization workflow with defined promotion boundaries.

## Prompt Families Worth Optimizing First

Do not start with the whole system. Start with prompts that already have stable seams:

1. Query rewrite
   Best first target because MimirQ already exposes `QUERY_REWRITE_STRATEGY` and versioned templates.

2. Query decomposition
   Only after rewrite optimization has a reliable evaluation loop.

3. Abstain / evidence follow-up prompting
   Useful later, but only if the metric definition is tight enough to avoid optimizing for verbosity.

Not recommended as the first DSPy target:

- the deterministic intent router,
- full answer generation prompts,
- or end-to-end agent workflows.

## Minimum POC Boundary

The first DSPy POC should optimize exactly one prompt family:

- target: query rewrite for multilingual follow-up and retrieval-friendly standalone questions
- candidates: current `kb_followup.v1` and `kb_followup.v2` as baseline seeds
- datasets:
  - MIRACL-zh based retrieval bundle
  - existing multilingual hard cases
  - a small internal holdout set if available
- outputs:
  - one candidate prompt strategy, e.g. `kb_followup.v3`
  - an experiment report
  - explicit promotion / rollback criteria

Keep the first run intentionally narrow:

- one optimizer family, such as MIPROv2 or equivalent DSPy optimizer;
- one prompt family;
- one primary metric;
- one holdout set.

## Evaluation Contract

DSPy should optimize against MimirQ-native success signals, not generic LLM quality scores.

Primary metrics should be one or more of:

- retrieval hit / recall on `reference_sources`
- evidence-anchor success
- must-recall proof / required source coverage
- slice-level performance on multilingual or hard-case buckets

Secondary metrics:

- prompt length / token cost
- stability across reruns
- degradation on non-target slices

Non-goals for the first phase:

- optimizing free-form answer style,
- maximizing subjective fluency,
- or using answer-level preference signals as the primary metric.

## Required Dependencies and Data

1. Stable experiment dataset
   Reuse `mimirq.regression_cases.v1` bundles and existing regression workflows instead of inventing a new dataset format.

2. Slice metadata
   Keep per-case tags such as:
   - `lang:zh`
   - `lang:en`
   - `lang:mixed`
   - dataset or quality buckets

3. Offline runner
   A future execution issue should build a simple experiment runner that:
   - loads cases,
   - calls DSPy optimizer,
   - evaluates against MimirQ metrics,
   - writes a report artifact.

4. Promotion surface
   Candidate winners should land as normal MimirQ configuration:
   - prompt template file or registry entry
   - strategy id bump
   - metrics snapshot attached to the change

## Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Overfitting to tiny benchmark | A prompt can win on a narrow set and regress in practice | Separate train/dev/holdout and report slice-level metrics |
| Metric mismatch | Optimizing answer text can hide retrieval regressions | Use retrieval/evidence metrics as the primary objective |
| Non-deterministic optimization output | Hard to compare candidates fairly | Fix model/provider where possible and run repeated evaluations |
| Runtime creep | DSPy online would add latency and complexity | Keep DSPy offline in v1 |
| Promotion ambiguity | Optimized prompt may never get adopted cleanly | Require strategy id, report, and rollback gate before merge |

## Rollout Steps

### Phase 1: Lock evaluation target

- Define the first prompt family: query rewrite only.
- Freeze datasets and slice tags.
- Define promotion criteria such as minimum uplift and maximum regression tolerance.

### Phase 2: Offline experiment harness

- Build a scriptable DSPy experiment runner.
- Feed existing prompts as baselines.
- Export candidate prompts and metrics reports.

### Phase 3: Human review and promotion

- Inspect the winning prompt for failure modes and hidden assumptions.
- Promote it as a new strategy id, not as an in-place overwrite.

### Phase 4: Post-promotion regression

- Run the normal MimirQ regression suites and targeted multilingual slices.
- Roll back if uplift is not robust outside the training set.

## No-Go Criteria

Do not continue into broader DSPy adoption if:

- the optimized prompt gains are small and unstable,
- candidate prompts improve one slice by degrading several others,
- or the workflow becomes too provider/model-specific to be maintainable.

## What Would Justify Closing `MimirQ-w1wo`

This issue can be closed once the team has:

- chosen "offline DSPy optimization" rather than runtime DSPy orchestration;
- selected the first prompt family to optimize;
- defined the input datasets, objective metrics, and promotion path;
- documented a follow-on execution backlog for building the experiment harness and promoting the first candidate strategy.

## References

- DSPy docs: `https://dspy.ai/learn/optimization/optimizers/`
- DSPy repository: `https://github.com/stanfordnlp/dspy`
