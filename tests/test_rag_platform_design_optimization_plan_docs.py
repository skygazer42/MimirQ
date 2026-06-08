from __future__ import annotations

from pathlib import Path


def test_rag_platform_design_optimization_plan_has_decision_framework() -> None:
    plan_path = Path("docs/plans/2026-06-09-rag-platform-design-optimization-plan.md")
    assert plan_path.exists()

    text = plan_path.read_text(encoding="utf-8")

    required_sections = (
        "## Design Philosophy Decision Matrix",
        "## Optimization Priority Ladder",
        "## Options Considered",
        "## Completion Definition",
    )
    for section in required_sections:
        assert section in text

    required_contracts = (
        "Platform core must not learn business meanings",
        "Plugin packages own business interpretation",
        "Deployment adapters own external binding and network evidence",
        "Optimize evidence retrieval before answer generation",
        "Contract-first plugin system",
    )
    for contract in required_contracts:
        assert contract in text


def test_rag_platform_design_principles_link_to_optimization_plan() -> None:
    principles = Path("docs/guides/rag_platform_design_principles.md").read_text(encoding="utf-8")
    assert "../plans/2026-06-09-rag-platform-design-optimization-plan.md" in principles
