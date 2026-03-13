# Evaluation Maturity Model (for RAG Quality)

This guide is a pragmatic maturity model for evaluating and gating RAG quality in MimirQ—starting from ad-hoc QA and evolving toward **continuous**, **slice-aware**, **PII-safe** evaluation with CI gates.

> 目标（中文摘要）：把“感觉更好”变成“可测、可回归、可解释、可审计”，并且默认 **PII-safe**。

---

## Non‑negotiable principles

1) **Measure before tuning**  
   Never merge “quality improvements” without a comparable before/after eval run.

2) **Deterministic where it matters (CI)**  
   If an eval is used to *block merges*, it should be deterministic (or as close as possible).

3) **PII-safe by default**  
   Artifacts (JSON/HTML/diffs/logs) should not contain raw queries, document text, tenant identifiers, or metadata filters in plaintext. Prefer hashes, counters, and redaction.

4) **Slice-first evaluation**  
   Global averages hide regressions. Always track per-slice deltas (file type, language, source, quality bucket, permission mode, etc.).

5) **Version everything you compare**  
   At minimum: dataset, pipeline config, retrieval config, reranker config, judge model/prompt (if used), and threshold file.

---

## What to measure (taxonomy)

### A) Retrieval quality (no generation)

Use this when you want **fast, cheap, deterministic** gating:

- Evidence recall / hit rate (e.g. `retrieval_recall`, `retrieval_hit_at_k`)
- Ranking quality (e.g. `retrieval_mrr`, `retrieval_ndcg_at_k`)
- Multi-hop chain quality（当 case 提供 `reasoning_hops/evidence_chain`）：
  `multihop_path_completeness`, `multihop_order_consistency`, `multihop_chain_hit_rate`
- Empty/weak evidence rates (`abstain_rate` is a strong proxy when using strict grounding)
- Latency (p50/p95) and error rate

MimirQ supports a **retrieval-only regression gate** that does not depend on RAGAS/LLMs. See:
- `docs/guides/regression_gate.md`
- `docs/guides/evidence_retrieval_gate.md`

### B) Answer quality / grounding

Use this when retrieval is “good enough” and you need to validate the end-to-end system:

- Grounding / faithfulness (e.g. RAGAS `faithfulness`)
- Relevance / usefulness (e.g. RAGAS `response_relevancy`)
- Refusal correctness (when `visible_evidence_only` or guardrails are enabled)
- Citation coverage / supported-claim ratio (best tracked as a metric and a diffable artifact)
- Proof coverage / must-recall consistency（`must_recall_pass_rate` + proof audit）

Note: answer-level evaluation is usually **less deterministic** (judge model variance, provider drift). Treat it as a *signal* unless you pin the judge model/prompt and budget it carefully.

For deterministic CI checks on answer-side summary metrics, MimirQ also provides:

- `scripts/answer_quality_gate.py`
- thresholds artifact: `ci/answer_quality_thresholds.v1.json`

This gate is designed for summary-level checks (`faithfulness_det`, refusal correctness, abstain behavior) and can run without live judge-model calls.

### C) System / operations quality

These often correlate with “quality regressions in practice”:

- Cost (tokens, provider calls) per request/run
- Tail latency and timeouts
- Drift indicators (embedding model change, data churn, index changes)
- Safety/compliance rates (PII/secret leakage alarms, policy refusal rate)

---

## Maturity levels

Think of this as a ladder. You can adopt Levels 2–4 incrementally, per dataset.

### Level 0 — Ad‑hoc QA (no artifacts)

**You have:** manual spot checks and subjective feedback.  
**Risk:** regressions are invisible; improvements are unprovable.

**Exit criteria:**
- A small, curated set of “golden questions” exists (even in a doc/spreadsheet).
- You can reproduce the same questions against the same dataset.

### Level 1 — Reproducible “golden questions” (still manual)

**You add:** a stable, shareable question set + basic run artifacts.

**Practices:**
- Curate 20–100 representative questions per dataset (include “hardcases”).
- Export/share regression case bundles across environments.
- Record the run context (pipeline/retrieval/rerank configs).

**MimirQ building blocks:**
- Regression case export/import + runs: `docs/guides/regression_gate.md`
- Evidence Pack → regression cases: `docs/guides/evidence_pack_to_regression.md`

**Exit criteria:**
- Regression cases are stored in a versioned form (repo or artifact storage).
- Anyone on the team can re-run the same cases and compare results.

### Level 2 — Deterministic retrieval gate in CI (merge-blocking)

**You add:** a deterministic gate that blocks merges when retrieval quality regresses.

**Why retrieval-only first:** it’s fast, stable, and isolates the biggest driver of RAG failures (missing evidence).

**Practices:**
- Gate on retrieval metrics only (no judge LLM required).
- Store threshold files in-repo (or an immutable artifact store).
- Always attach run JSON + diff artifacts to CI for debugging.
- For multi-hop datasets, add explicit thresholds for chain coverage/order metrics.
- Run proof-consistency audit artifact (`must_recall_proof_audit`) for release evidence.

**MimirQ building blocks:**
- CLI gate: `scripts/regression_gate.py` (run with `--metrics ""` for retrieval-only)
- Thresholds v2 (slice-aware): documented in `docs/guides/regression_gate.md`
- Seeded CI fixture exists (good for wiring the workflow before using real data)

**Exit criteria:**
- PRs cannot merge when the gate fails.
- A failing gate produces actionable artifacts (summary + per-slice deltas).
- Multi-hop/proof-capability datasets have dedicated gate thresholds, not only global recall metrics.

### Level 3 — Answer-level evaluation (scheduled, budgeted, diff-first)

**You add:** answer-level eval runs (RAGAS / judge-based) that are scheduled (nightly / pre-release) and produce diffable reports.

**Practices:**
- Run answer-level evaluation on:
  - golden questions + hardcases, and
  - the slices that historically regress (e.g. `file_type=pdf`, `language=zh`, “ACL-trimmed datasets”).
- Budget it (max cost + time) and retain artifacts for debugging.
- Treat it as a release gate only if judge determinism is acceptable (pinned model/prompt, retry policy, and variance tracking).

**Exit criteria:**
- You can answer: “What got better/worse, in which slice, and why?”
- You have a stable baseline and an “eval diff” workflow.

### Level 4 — Continuous evaluation & governance (enterprise grade)

**You add:** continuous pipelines and governance so evaluation scales with product and org complexity.

**Practices:**
- Continuous hardcase mining + synthetic hardcase generation (PII-safe).
- Nightly ablation runner (compare retrieval/rerank variants systematically).
- Provider/model parity checks (detect judge/provider drift).
- Artifact bundling + retention policies (what to keep, how long, where).
- “Fail-closed” policy: regressions block releases, with an explicit override workflow and audit trail.

**Exit criteria:**
- Evaluation is part of the SDLC: PR gate + nightly + release sign-off.
- Regressions are caught early, scoped to slices, and traceable to changes.

---

## Suggested adoption path for MimirQ (lowest effort → highest leverage)

1) **Wire the workflow** using the existing retrieval-only gate docs and fixture:
   - Start here: `docs/guides/regression_gate.md`

2) **Create real regression cases** from production-like questions:
   - Prefer Evidence Pack → regression bundle to keep evidence grounded:
     `docs/guides/evidence_pack_to_regression.md`

3) **Generate slice-aware thresholds** from a baseline run and commit them:
   - Use thresholds v2 (per-slice): `docs/guides/regression_gate.md`

4) **Add an ablation workflow** so improvements are intentional:
   - `docs/guides/retrieval_ablation.md`

5) **Add answer-level evaluation** as a scheduled signal (then graduate to a gate if stable):
   - RAGAS/regression usage: `docs/guides/regression_gate.md`

---

## How this maps to Wave21 (Continuous Evaluation & CI Gates)

Wave21 defines the “end state” capabilities for continuous evaluation. This maturity model is the on-ramp.

| Wave21 Task | Fits best at level | Why it matters |
|---|---:|---|
| Wave21‑T085: “golden questions” per dataset + governance | 1+ | Makes quality comparable and repeatable. |
| Wave21‑T089: CI fail on quality regression beyond threshold | 2 | Turns evaluation into a merge gate. |
| Wave21‑T084: dataset slice taxonomy v3 | 2+ | Prevents global averages from hiding regressions. |
| Wave21‑T088: “eval diff” scoring (baseline vs candidate) | 3+ | Makes changes explainable and reviewable. |
| Wave21‑T081: answer-level regression gate (faithfulness + refusal correctness) | 3–4 | Validates end-to-end behavior beyond retrieval. |
| Wave21‑T083: continuous ablation runner (nightly) | 4 | Systematically compares knobs/variants over time. |
| Wave21‑T082: synthetic hardcase generation (PII‑safe) | 4 | Scales coverage without leaking sensitive data. |
| Wave21‑T087: model/provider parity checks | 4 | Detects silent drift across LLM providers/versions. |
| Wave21‑T086: eval artifacts bundling + retention policies | 2–4 | Keeps evidence for debugging, audits, and rollbacks. |
| Wave21‑T090: docs: evaluation maturity model | (this doc) | Defines the ladder and adoption path. |

## Common anti-patterns (and what to do instead)

- **“We improved quality” without a baseline run** → always produce a diffable eval artifact.
- **Using non-deterministic judge eval as a merge blocker** → gate retrieval deterministically; schedule judge eval nightly.
- **Only tracking global averages** → add slices early; regressions are usually slice-local.
- **Overfitting thresholds to one dataset** → keep per-dataset thresholds and track drift over time.
- **Artifacts contain plaintext customer data** → treat eval artifacts as exportable; keep them PII-safe by default.
