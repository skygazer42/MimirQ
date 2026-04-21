# RAG POC Attribution Framework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the backend Stage 0 POC attribution toolchain for `rag-poc-attribution-framework-2026-q2.md`, starting with telemetry normalization, negative-feedback attribution, and out-of-scope verification, then expanding to query pattern mining, report helpers, and industry rule bootstrapping.

**Architecture:** Reuse the existing `MessageFeedback` table, feedback API snapshots, and trace metadata as the canonical source instead of introducing a second telemetry store. Implement a new dependency-light package under `app/rag/evaluation/poc_runner/` so the analysis logic can be reused by API handlers, scripts, and tests without coupling to heavy runtime services.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy models, existing `app/models/feedback.py`, `app/api/v1/feedback.py`, `app/services/hardcase_discovery_service.py`, pytest.

---

## Scope Decisions

- Use `app/rag/evaluation/poc_runner/` as the canonical package root for this plan.
- Reuse existing feedback rows and `extra.retrieval_trace` snapshots before adding any new storage layer.
- Treat the source plan's SQLite-only telemetry suggestion as superseded by the existing `MessageFeedback` schema already present in this repo.
- Delay Streamlit demo and CMS/API management surfaces until the core analysis modules are implemented and verified.
- First execution batch is **Task 1 + Task 2 + Task 3** only.

## Out Of Scope For This Plan Pass

- `app/rag/demo/poc_streamlit.py`
- `app/api/v1/industry_rules.py`
- UMAP image generation and frontend visual polish
- End-to-end tenant UI workflows

## Task 1: Telemetry Normalization Layer

**Files:**
- Create: `app/rag/evaluation/poc_runner/__init__.py`
- Create: `app/rag/evaluation/poc_runner/telemetry.py`
- Test: `tests/test_poc_runner_telemetry.py`

**Intent:** Convert existing `MessageFeedback` rows plus feedback `extra` snapshots into a stable POC analysis row shape:
`session_id`, `original_query`, `llm_response`, `final_context_filenames`, `feedback_score`, `latency_total_ms`, plus bounded metadata.

- [ ] **Step 1: Write the failing test**

  ```python
  def test_build_poc_feedback_row_uses_feedback_extra_and_trace_snapshot() -> None:
      row = build_poc_feedback_row(
          feedback={
              "id": "fb-1",
              "rating": 1,
              "reason": "答非所问",
              "extra": {
                  "retrieval_trace_request_id": "req-1",
                  "retrieval_trace": {
                      "messages": {"user_question": "485 怎么配置"},
                      "answer": {"text": "请按手册配置"},
                      "retrieval": {"latency_total_ms": 3200},
                      "citations": [{"source": "manual-a.pdf"}],
                  },
              },
          }
      )
      assert row["session_id"] == "fb-1"
      assert row["original_query"] == "485 怎么配置"
      assert row["llm_response"] == "请按手册配置"
      assert row["final_context_filenames"] == ["manual-a.pdf"]
      assert row["feedback_score"] == 1
      assert row["latency_total_ms"] == 3200
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_telemetry.py
  ```

  Expected: `FAIL` with missing module or missing function.

- [ ] **Step 3: Write the minimal implementation**

  ```python
  POC_TELEMETRY_SCHEMA_V1 = "mimirq.poc.telemetry.v1"

  def build_poc_feedback_row(feedback: dict[str, Any]) -> dict[str, Any]:
      ...

  def build_poc_feedback_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
      ...
  ```

  Implementation rules:
  - Accept plain dict-like payloads first so tests stay dependency-light.
  - Prefer `feedback.extra.retrieval_trace` if present.
  - Fall back safely when question, answer, citations, or latency are missing.
  - Normalize filenames to a deduped list of strings.
  - Return bounded, PII-conscious payloads suitable for offline analysis.

- [ ] **Step 4: Run test to verify it passes**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_telemetry.py
  ```

  Expected: `PASS`.

- [ ] **Step 5: Commit**

  ```bash
  git add app/rag/evaluation/poc_runner/__init__.py app/rag/evaluation/poc_runner/telemetry.py tests/test_poc_runner_telemetry.py
  git commit -m "Create a telemetry normalization layer for POC feedback analysis"
  ```

## Task 2: Negative Feedback Attribution Classifier

**Files:**
- Create: `app/rag/evaluation/poc_runner/attribution_classifier.py`
- Test: `tests/test_poc_runner_attribution_classifier.py`

**Intent:** Implement the source plan's three-way negative feedback taxonomy:
`retrieval_miss`, `generation_error`, `out_of_scope`, with a manual-review queue for low-confidence labels.

- [ ] **Step 1: Write the failing test**

  ```python
  def test_classify_feedback_records_groups_examples_and_manual_review_queue() -> None:
      rows = [
          {"session_id": "a", "original_query": "485 怎么配置", "feedback_score": -1},
          {"session_id": "b", "original_query": "X9 新型号怎么接线", "feedback_score": -1},
      ]

      def fake_classifier(row: dict[str, object]) -> dict[str, object]:
          if row["session_id"] == "a":
              return {"category": "retrieval_miss", "confidence": 0.62, "rationale": "no matching evidence"}
          return {"category": "out_of_scope", "confidence": 0.91, "rationale": "knowledge gap"}

      summary = classify_feedback_records(rows, classifier=fake_classifier, review_confidence_threshold=0.7)
      assert summary["counts"]["retrieval_miss"] == 1
      assert summary["counts"]["out_of_scope"] == 1
      assert summary["manual_review_queue"][0]["session_id"] == "a"
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_attribution_classifier.py
  ```

  Expected: `FAIL`.

- [ ] **Step 3: Write the minimal implementation**

  ```python
  POC_ATTRIBUTION_SCHEMA_V1 = "mimirq.poc.attribution.v1"

  def classify_feedback_records(
      records: Sequence[dict[str, Any]],
      *,
      classifier: Callable[[dict[str, Any]], dict[str, Any]] | None,
      review_confidence_threshold: float = 0.7,
      max_examples_per_category: int = 10,
  ) -> dict[str, Any]:
      ...
  ```

  Implementation rules:
  - Only classify negative feedback rows.
  - Support a dependency-free heuristic fallback when no classifier callable is supplied.
  - Emit counts, ratios, top examples per category, and a manual-review queue.
  - Keep output deterministic and bounded.

- [ ] **Step 4: Run test to verify it passes**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_attribution_classifier.py
  ```

  Expected: `PASS`.

- [ ] **Step 5: Commit**

  ```bash
  git add app/rag/evaluation/poc_runner/attribution_classifier.py tests/test_poc_runner_attribution_classifier.py
  git commit -m "Add a three-way attribution classifier for negative POC feedback"
  ```

## Task 3: Out-Of-Scope Verifier

**Files:**
- Create: `app/rag/evaluation/poc_runner/out_of_scope_verifier.py`
- Test: `tests/test_poc_runner_out_of_scope_verifier.py`

**Intent:** Implement the source plan's three-stage scope check:
keyword expansion hit, vector similarity threshold, HyDE fallback.

- [ ] **Step 1: Write the failing test**

  ```python
  def test_verify_out_of_scope_query_returns_out_of_scope_when_all_signals_fail() -> None:
      result = verify_out_of_scope_query(
          query="X9 新型号怎么接线",
          glossary={"接线": ["接线图"]},
          keyword_search=lambda _query: [],
          vector_search=lambda _query: [{"score": 0.18}],
          hyde_generate=lambda _query: "如果知识库有答案，会提到 X9 接线图",
          vector_similarity_threshold=0.3,
          hyde_similarity_threshold=0.3,
      )
      assert result["l1_keyword_hit"] is False
      assert result["l2_top1_sim"] == 0.18
      assert result["verdict"] == "out_of_scope"
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_out_of_scope_verifier.py
  ```

  Expected: `FAIL`.

- [ ] **Step 3: Write the minimal implementation**

  ```python
  POC_SCOPE_VERDICT_SCHEMA_V1 = "mimirq.poc.scope_verdict.v1"

  def verify_out_of_scope_query(
      *,
      query: str,
      glossary: Mapping[str, Sequence[str]] | None,
      keyword_search: Callable[[str], Sequence[dict[str, Any]]],
      vector_search: Callable[[str], Sequence[dict[str, Any]]],
      hyde_generate: Callable[[str], str],
      vector_similarity_threshold: float,
      hyde_similarity_threshold: float,
  ) -> dict[str, Any]:
      ...
  ```

  Implementation rules:
  - Expand keywords from glossary terms before stage L1.
  - Compute the best vector score from stage L2 and HyDE stage L3.
  - Return one of `in_scope`, `ambiguous`, `out_of_scope`.
  - Keep search interfaces injectable for pure unit tests.

- [ ] **Step 4: Run test to verify it passes**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_out_of_scope_verifier.py
  ```

  Expected: `PASS`.

- [ ] **Step 5: Commit**

  ```bash
  git add app/rag/evaluation/poc_runner/out_of_scope_verifier.py tests/test_poc_runner_out_of_scope_verifier.py
  git commit -m "Add a three-stage out-of-scope verifier for POC analysis"
  ```

## Task 4: Query Pattern Miner

**Files:**
- Create: `app/rag/evaluation/poc_runner/query_pattern_miner.py`
- Test: `tests/test_poc_runner_query_pattern_miner.py`

**Intent:** Mine abbreviations, multi-intent questions, and hot documents from normalized telemetry rows.

- [ ] **Step 1: Write the failing test**

  ```python
  def test_mine_query_patterns_detects_abbreviations_multi_intent_and_document_heat() -> None:
      rows = [
          {"session_id": "q1", "original_query": "485 怎么配置？另外上次那个报错怎么处理？", "final_context_filenames": ["manual-a.pdf", "manual-b.pdf"]},
          {"session_id": "q2", "original_query": "485 没数据怎么办", "final_context_filenames": ["manual-a.pdf"]},
          {"session_id": "q3", "original_query": "485 通讯异常", "final_context_filenames": ["manual-a.pdf"]},
          {"session_id": "q4", "original_query": "485 参数设置步骤", "final_context_filenames": ["manual-c.pdf"]},
          {"session_id": "q5", "original_query": "485 驱动安装", "final_context_filenames": ["manual-a.pdf"]},
      ]
      summary = mine_query_patterns(rows, abbreviation_min_frequency=5, top_k_keywords=5)
      assert summary["abbreviations"][0]["token"] == "485"
      assert summary["document_heat"][0] == {"filename": "manual-a.pdf", "count": 4}
      assert summary["multi_intent_queries"][0]["session_id"] == "q1"
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_query_pattern_miner.py
  ```

  Expected: `FAIL`.

- [ ] **Step 3: Write the minimal implementation**

  ```python
  def mine_query_patterns(
      rows: Sequence[dict[str, Any]],
      *,
      abbreviation_min_frequency: int = 5,
      top_k_keywords: int = 20,
  ) -> dict[str, Any]:
      ...
  ```

  Implementation rules:
  - Keep logic dependency-light; no heavyweight ML dependency in the first slice.
  - Approximate TF-IDF using bounded token counts and inverse-frequency weights.
  - Detect abbreviations by short-token + frequency rules.
  - Detect multi-intent using connectors and multiple question cues.
  - Aggregate `final_context_filenames` into heat counts.

- [ ] **Step 4: Run test to verify it passes**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_query_pattern_miner.py
  ```

  Expected: `PASS`.

- [ ] **Step 5: Commit**

  ```bash
  git add app/rag/evaluation/poc_runner/query_pattern_miner.py tests/test_poc_runner_query_pattern_miner.py
  git commit -m "Mine abbreviations, multi-intent queries, and hot documents from POC telemetry"
  ```

## Task 5: Report Helpers And Corrected Metrics

**Files:**
- Create: `app/rag/evaluation/poc_runner/reports/__init__.py`
- Create: `app/rag/evaluation/poc_runner/reports/feedback_metrics.py`
- Create: `app/rag/evaluation/poc_runner/reports/attribution_report.py`
- Test: `tests/test_poc_runner_feedback_metrics.py`

**Intent:** Materialize the source plan's corrected metrics:
raw approval rate, controllable approval rate, knowledge-base coverage, retrieval accuracy, generation accuracy.

- [ ] **Step 1: Write the failing test**

  ```python
  def test_compute_feedback_metrics_emits_corrected_rates() -> None:
      summary = compute_feedback_metrics(
          total=10,
          positive=7,
          counts={"retrieval_miss": 1, "generation_error": 1, "out_of_scope": 1},
      )
      assert summary["raw_positive_rate"] == 0.7
      assert summary["controllable_positive_rate"] == 0.8
      assert summary["knowledge_base_coverage"] == 0.9
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_feedback_metrics.py
  ```

  Expected: `FAIL`.

- [ ] **Step 3: Write the minimal implementation**

  Create one pure metrics helper and one report formatter that accepts precomputed attribution summaries.

- [ ] **Step 4: Run test to verify it passes**

  Run:

  ```bash
  pytest -q tests/test_poc_runner_feedback_metrics.py
  ```

  Expected: `PASS`.

- [ ] **Step 5: Commit**

  ```bash
  git add app/rag/evaluation/poc_runner/reports/__init__.py app/rag/evaluation/poc_runner/reports/feedback_metrics.py app/rag/evaluation/poc_runner/reports/attribution_report.py tests/test_poc_runner_feedback_metrics.py
  git commit -m "Add corrected POC feedback metrics and attribution report helpers"
  ```

## Task 6: Industry Rules Bootstrap

**Files:**
- Create: `app/rag/industry_rules/__init__.py`
- Create: `app/rag/industry_rules/schema.py`
- Create: `app/rag/industry_rules/loaders/yaml_loader.py`
- Create: `app/rag/industry_rules/rulesets/industrial_control/glossary.yaml`
- Create: `app/rag/industry_rules/rulesets/industrial_control/patterns.yaml`
- Create: `app/rag/industry_rules/rulesets/industrial_control/intents.yaml`
- Create: `app/rag/industry_rules/appliers/query_rewrite.py`
- Create: `app/rag/industry_rules/appliers/pattern_matcher.py`
- Create: `app/rag/industry_rules/appliers/intent_classifier.py`
- Test: `tests/test_industry_rules_bootstrap.py`

**Intent:** Create the first reusable ruleset structure so `query_pattern_miner` outputs have a durable home.

- [ ] **Step 1: Write the failing test**

  ```python
  def test_load_industrial_control_ruleset_and_expand_query_terms() -> None:
      ruleset = load_ruleset("industrial_control")
      expanded = expand_query_terms("485 没数据", ruleset.glossary)
      assert "rs-485" in expanded.casefold()
  ```

- [ ] **Step 2: Run test to verify it fails**

  Run:

  ```bash
  pytest -q tests/test_industry_rules_bootstrap.py
  ```

  Expected: `FAIL`.

- [ ] **Step 3: Write the minimal implementation**

  Implement only:
  - YAML-backed ruleset loading
  - glossary expansion
  - bounded pattern and intent matching placeholders

  Do **not** integrate with `orchestrator.py` in this task.

- [ ] **Step 4: Run test to verify it passes**

  Run:

  ```bash
  pytest -q tests/test_industry_rules_bootstrap.py
  ```

  Expected: `PASS`.

- [ ] **Step 5: Commit**

  ```bash
  git add app/rag/industry_rules tests/test_industry_rules_bootstrap.py
  git commit -m "Bootstrap industry rulesets for POC query rewrite and routing"
  ```

## Task 7: Final Verification For This MD

**Files:**
- Verify only; no required file creation

- [ ] **Step 1: Run the targeted poc_runner and industry_rules test set**

  Run:

  ```bash
  pytest -q \
    tests/test_poc_runner_telemetry.py \
    tests/test_poc_runner_attribution_classifier.py \
    tests/test_poc_runner_out_of_scope_verifier.py \
    tests/test_poc_runner_query_pattern_miner.py \
    tests/test_poc_runner_feedback_metrics.py \
    tests/test_industry_rules_bootstrap.py
  ```

  Expected: all selected tests `PASS`.

- [ ] **Step 2: Run focused import smoke checks**

  Run:

  ```bash
  pytest -q tests/test_api_v1_lazy_router_import.py
  ```

  Expected: `PASS`.

- [ ] **Step 3: Update the master roadmap**

  Modify:
  - `docs/plans/2026-04-21-backend-plan-execution-roadmap.md`

  Mark completed checkboxes for the work actually shipped from this source plan.

- [ ] **Step 4: Commit the finished first source-plan batch**

  ```bash
  git add docs/plans/2026-04-21-backend-plan-execution-roadmap.md
  git commit -m "Complete the first implementation batch for the POC attribution framework"
  ```

## Notes For Execution

- Keep each module pure and injectable first; wire into APIs only after the pure analysis layer is green.
- Prefer existing feedback/tracing fields over inventing parallel storage.
- If an existing module already satisfies a task, document that fact and skip the implementation, but still add or confirm the regression test that proves it.
- After Task 3, stop and review before continuing if the feedback data shape in `MessageFeedback.extra` is weaker than expected.
