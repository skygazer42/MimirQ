from __future__ import annotations

from pathlib import Path


def test_lint_fast_workflow_exists_and_runs_on_prs() -> None:
    text = Path(".github/workflows/lint-fast.yml").read_text(encoding="utf-8")

    assert "name: Lint Fast" in text
    assert "pull_request:" in text
    assert "push:" in text
    assert "branches:" in text
    assert "- main" in text
    assert "workflow_dispatch:" in text


def test_lint_fast_workflow_stays_lightweight() -> None:
    text = Path(".github/workflows/lint-fast.yml").read_text(encoding="utf-8")

    assert "timeout-minutes: 10" in text
    assert "ruff==0.15.9" in text
    assert "python -m ruff check app tests scripts main.py" in text
    assert "pnpm install --frozen-lockfile --ignore-scripts" in text
    assert "pnpm run lint" in text
    assert "pnpm run typecheck" in text
    assert "requirements-dev.txt" not in text
    assert "playwright" not in text.lower()
