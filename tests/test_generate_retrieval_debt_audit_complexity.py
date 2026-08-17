from pathlib import Path

import pytest

from scripts import generate_retrieval_debt_audit as audit


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_hierarchy_audit_reports_missing_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)

    rendered, stats = audit._render_hierarchy_recall_audit()

    assert stats == {"risk_signals": 3, "checks": 3}
    assert rendered.splitlines() == [
        "| check | status | observed |",
        "|---|---|---|",
        "| hierarchy_profiles_present | warn | retrieval_profiles.py missing |",
        "| must_recall_anchor_excludes_hierarchy_context | warn | orchestrator.py missing |",
        "| eval_summary_includes_doc_family_recall | warn | evidence_retrieve_gate.py missing |",
    ]


def test_hierarchy_audit_accepts_profiles_safe_defaults_and_guardrails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    _write(
        tmp_path,
        "app/rag/core/retrieval_profiles.py",
        "\n".join(
            [
                "hierarchy_recall20 hierarchy_hybrid_ce hierarchy_grounded_strict",
                'out["hierarchy_parent_depth"] = 0',
                'out["hierarchy_sibling_window"] = 0',
            ]
        ),
    )
    _write(
        tmp_path,
        "app/rag/retrieval/orchestrator.py",
        "exclude_retrieval_role_prefixes = ['hierarchy_']",
    )
    _write(
        tmp_path,
        "app/rag/evaluation/evidence_retrieve_gate.py",
        "retrieval_doc_recall retrieval_family_recall",
    )

    rendered, stats = audit._render_hierarchy_recall_audit()

    assert stats == {"risk_signals": 0, "checks": 4}
    assert rendered.splitlines()[2:] == [
        "| hierarchy_profiles_present | ok | found hierarchy profiles |",
        "| hierarchy_overlay_safe_defaults | ok | parent_depth=0, sibling_window=0 |",
        "| must_recall_anchor_excludes_hierarchy_context | ok | "
        "exclude_retrieval_role_prefixes=['hierarchy_'] detected |",
        "| eval_summary_includes_doc_family_recall | ok | doc/family recall metrics detected |",
    ]


def test_hierarchy_audit_flags_nonzero_overlay_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    _write(
        tmp_path,
        "app/rag/core/retrieval_profiles.py",
        "\n".join(
            [
                "hierarchy_recall20 hierarchy_hybrid_ce hierarchy_grounded_strict",
                'out["hierarchy_parent_depth"] = 2',
                'out["hierarchy_sibling_window"] = 1',
            ]
        ),
    )

    rendered, stats = audit._render_hierarchy_recall_audit()

    assert stats == {"risk_signals": 3, "checks": 4}
    assert "| hierarchy_overlay_safe_defaults | warn | parent_depth=2, sibling_window=1 |" in rendered
