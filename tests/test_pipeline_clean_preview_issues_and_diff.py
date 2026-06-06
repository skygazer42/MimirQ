from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_clean_preview_includes_issues_and_diff(monkeypatch: pytest.MonkeyPatch):
    from app.api.schemas.pipeline import CleanPreviewRequest
    from app.api.v1.pipeline import clean_preview
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    body = CleanPreviewRequest(
        markdown="A\x00\nB\n",
        include_diff=True,
        use_default_rules=True,
    )

    out = await clean_preview(
        body=body,
        tenant_id=UUID(int=1),
        account_id="u",
        db=object(),
    )

    assert out.changed is True
    assert isinstance(out.diff_unified, str)
    assert out.diff_unified.strip()
    assert isinstance(out.issues, list)
    assert any(getattr(it, "code", "") == "control_chars" for it in out.issues)


@pytest.mark.asyncio
async def test_governance_analyze_returns_suggestions(monkeypatch: pytest.MonkeyPatch):
    from app.api.schemas.pipeline import GovernanceAnalyzeRequest
    from app.api.v1.pipeline import governance_analyze
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    body = GovernanceAnalyzeRequest(
        markdown=("Line wrapped text " * 3 + "\n") * 120,
        input_format="markdown",
        unwrap_lines=False,
    )

    out = await governance_analyze(
        body=body,
        tenant_id=UUID(int=1),
        account_id="u",
        db=object(),
    )

    assert isinstance(out.issues, list)
    patch = out.suggested_pipeline_patch.model_dump(exclude_none=True)
    assert "business_only_window_chars" not in patch
    # Best-effort heuristic; when it triggers it should suggest enabling unwrap_lines.
    if any(getattr(it, "code", "") == "pdf_soft_line_breaks" for it in out.issues):
        assert patch.get("governance_unwrap_lines") is True


def test_governance_issue_suggested_patch_openapi_contract_is_typed():
    from app.api.schemas.pipeline import GovernanceIssue

    schema = GovernanceIssue.model_json_schema()
    patch_schema = schema["properties"]["suggested_pipeline_patch"]

    assert patch_schema["$ref"].endswith("/DocumentPipelineOptions")
