# Plans Remediation Wave 1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the next three highest-leverage gaps from the plans audit: hard-negative stress evaluation, prompt-based FLARE scaffold, and parse benchmark automation.

**Architecture:** Keep every deliverable deterministic and test-first. Build each missing artifact as a bounded helper that reuses existing evaluation, workflow, and parsing infrastructure instead of introducing new framework layers.

**Tech Stack:** Python, pytest, existing `app.rag.evaluation`, `app.rag.workflows`, `app.parsing`, and local benchmark scripts under `plans/scripts`.

---

### Task 1: Hard Negative Stress Runner

**Files:**
- Create: `app/rag/evaluation/hard_negative_stress.py`
- Test: `tests/test_hard_negative_stress.py`
- Reference: `app/rag/evaluation/metrics/answer_det.py`, `app/rag/evaluation/results/schema.py`

**Step 1: Write the failing test**

```python
from app.rag.evaluation.hard_negative_stress import evaluate_hard_negative_case, run_hard_negative_stress


def test_evaluate_hard_negative_case_flags_entity_match_but_fact_mismatch() -> None:
    result = evaluate_hard_negative_case(
        {
            "case_id": "hn-001",
            "query": "华发股份董事会有多少位董事？",
            "answer": "华发股份董事会有 9 位董事。",
            "gold_answer": "华发股份董事会有 14 位董事。",
            "citations": [{"chunk_id": "chunk-a"}],
        }
    )

    assert result["passed"] is False
    assert "hard_negative_triggered" in result["reason_codes"]
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_hard_negative_stress.py`
Expected: FAIL with `ModuleNotFoundError: app.rag.evaluation.hard_negative_stress`

**Step 3: Write minimal implementation**

```python
def evaluate_hard_negative_case(case: dict[str, Any]) -> dict[str, Any]:
    answer = str(case.get("answer") or "").strip()
    gold = str(case.get("gold_answer") or "").strip()
    hard_negative = bool(answer and gold and answer != gold and bool(case.get("citations")))
    return {
        "schema": "mimirq.hard_negative_case.v1",
        "case_id": str(case.get("case_id") or ""),
        "passed": not hard_negative,
        "reason_codes": ["hard_negative_triggered"] if hard_negative else [],
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_hard_negative_stress.py`
Expected: PASS

**Step 5: Commit**

```bash
git add app/rag/evaluation/hard_negative_stress.py tests/test_hard_negative_stress.py
git commit -m "Close hard-negative blind spots in evaluation"
```

### Task 2: Prompt-Based FLARE Scaffold

**Files:**
- Create: `app/rag/workflows/flare.py`
- Test: `tests/test_flare_workflow.py`
- Reference: `app/rag/core/confidence.py`, `app/rag/workflows/self_rag.py`, `app/rag/workflows/crag_streaming.py`

**Step 1: Write the failing test**

```python
from app.rag.workflows.flare import run_flare_refinement


def test_run_flare_refinement_requests_followup_retrieval_when_confidence_is_low() -> None:
    out = run_flare_refinement(
        question="485 watchdog 怎么配置？",
        draft_answer="应该是 30 秒。",
        evidence_gap={"has_gap": True, "severity": "high"},
        confidence_score=0.2,
    )

    assert out["schema"] == "mimirq.flare_refinement.v1"
    assert out["need_retrieval"] is True
    assert out["reason_codes"] == ["low_confidence"]
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_flare_workflow.py`
Expected: FAIL with `ModuleNotFoundError: app.rag.workflows.flare`

**Step 3: Write minimal implementation**

```python
def run_flare_refinement(*, question: str, draft_answer: str, evidence_gap: dict[str, Any] | None, confidence_score: float | None) -> dict[str, Any]:
    low_confidence = float(confidence_score or 0.0) < 0.5 or bool((evidence_gap or {}).get("has_gap"))
    return {
        "schema": "mimirq.flare_refinement.v1",
        "need_retrieval": low_confidence,
        "rewrite_query": question if low_confidence else None,
        "reason_codes": ["low_confidence"] if low_confidence else [],
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_flare_workflow.py`
Expected: PASS

**Step 5: Commit**

```bash
git add app/rag/workflows/flare.py tests/test_flare_workflow.py
git commit -m "Add bounded FLARE-style retrieval trigger scaffold"
```

### Task 3: Parse Benchmark Runner

**Files:**
- Create: `plans/scripts/parse_bench.py`
- Test: `tests/test_parse_bench_runner.py`
- Reference: `app/parsing/quality/benchmark.py`, `app/parsing/quality/competition.py`, `plans/rag-parsing-chunking-deep-dive-2026-q2.md`

**Step 1: Write the failing test**

```python
from plans.scripts.parse_bench import build_parse_bench_plan


def test_build_parse_bench_plan_lists_enabled_parsers_and_output_schema() -> None:
    out = build_parse_bench_plan(
        parsers=["deepdoc", "mineru", "docling"],
        dataset="omnidocbench-mini",
    )

    assert out["schema"] == "mimirq.parse_bench_plan.v1"
    assert out["dataset"] == "omnidocbench-mini"
    assert out["parsers"] == ["deepdoc", "mineru", "docling"]
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_parse_bench_runner.py`
Expected: FAIL with `ModuleNotFoundError` or missing symbol

**Step 3: Write minimal implementation**

```python
def build_parse_bench_plan(*, parsers: list[str], dataset: str) -> dict[str, Any]:
    return {
        "schema": "mimirq.parse_bench_plan.v1",
        "dataset": str(dataset),
        "parsers": [str(parser) for parser in parsers if str(parser).strip()],
        "metrics": ["accuracy", "latency_ms", "cost_usd"],
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_parse_bench_runner.py`
Expected: PASS

**Step 5: Commit**

```bash
git add plans/scripts/parse_bench.py tests/test_parse_bench_runner.py
git commit -m "Add parse benchmark runner scaffold for audit wave 1"
```

### Task 4: Verification Sweep

**Files:**
- Test: `tests/test_hard_negative_stress.py`
- Test: `tests/test_flare_workflow.py`
- Test: `tests/test_parse_bench_runner.py`
- Test: `tests/test_agent_redteam.py`
- Test: `tests/test_ragcap_bench_runner.py`

**Step 1: Run the focused verification suite**

Run: `pytest -q tests/test_hard_negative_stress.py tests/test_flare_workflow.py tests/test_parse_bench_runner.py tests/test_agent_redteam.py tests/test_ragcap_bench_runner.py`
Expected: PASS

**Step 2: Run lint on new files**

Run: `ruff check app/rag/evaluation/hard_negative_stress.py app/rag/workflows/flare.py plans/scripts/parse_bench.py tests/test_hard_negative_stress.py tests/test_flare_workflow.py tests/test_parse_bench_runner.py`
Expected: `All checks passed!`

**Step 3: Commit**

```bash
git add app/rag/evaluation/hard_negative_stress.py app/rag/workflows/flare.py plans/scripts/parse_bench.py tests/test_hard_negative_stress.py tests/test_flare_workflow.py tests/test_parse_bench_runner.py
git commit -m "Advance audit wave 1 remediation plan"
```
