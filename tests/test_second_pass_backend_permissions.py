from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.schemas.rbac import TenantMemberUpdateRequest
from app.models.tenant import TenantMember


class _CommitOnlyDB:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_global_chunk_preset_mutation_requires_editor_role(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import chunk_presets

    write_called = False

    def _create(**_kwargs):
        nonlocal write_called
        write_called = True
        return SimpleNamespace(id=uuid4(), name="shared", description=None, payload={})

    monkeypatch.setattr(
        chunk_presets.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="viewer"),
    )
    monkeypatch.setattr(chunk_presets, "_create_chunk_preset_row", _create)

    with pytest.raises(HTTPException) as exc_info:
        chunk_presets.create_chunk_preset(
            chunk_presets.ChunkPresetCreateRequest(name="shared", payload={}),
            db=object(),
            tenant_id=uuid4(),
            account_id="viewer",
        )

    assert exc_info.value.status_code == 403
    assert write_called is False


@pytest.mark.asyncio
async def test_rtbf_execution_requires_lifecycle_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import rtbf

    cascade_called = False

    def _deny(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=403, detail="denied")

    async def _cascade(*_args, **_kwargs) -> dict:
        nonlocal cascade_called
        cascade_called = True
        return {"deleted": 1}

    monkeypatch.setattr(rtbf, "ensure_tenant_permission", _deny, raising=False)
    monkeypatch.setattr(rtbf, "run_rtbf_cascade", _cascade, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await rtbf.request_rtbf_cascade(
            rtbf.RTBFRequest(subject_account_id="victim", dry_run=False),
            tenant_id=uuid4(),
            account_id="viewer",
            db=object(),
        )

    assert exc_info.value.status_code == 403
    assert cascade_called is False


def test_prompt_template_mutations_require_settings_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import prompt_templates

    def _deny(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(prompt_templates, "ensure_tenant_permission", _deny, raising=False)
    monkeypatch.setattr(prompt_templates, "list_builtin_prompt_templates", lambda: [])
    db = _CommitOnlyDB()
    tenant_id = uuid4()
    template_id = uuid4()
    operations = (
        lambda: prompt_templates.sync_builtin_prompt_templates(
            tenant_id=tenant_id,
            account_id="viewer",
            db=db,
        ),
        lambda: prompt_templates.create_prompt_template(
            prompt_templates.PromptTemplateCreate(name="test", content="content"),
            tenant_id=tenant_id,
            account_id="viewer",
            db=db,
        ),
        lambda: prompt_templates.create_prompt_template_version(
            template_id,
            prompt_templates.PromptTemplateNewVersion(),
            tenant_id=tenant_id,
            account_id="viewer",
            db=db,
        ),
        lambda: prompt_templates.update_prompt_template(
            template_id,
            prompt_templates.PromptTemplateUpdate(name="updated"),
            tenant_id=tenant_id,
            account_id="viewer",
            db=db,
        ),
        lambda: prompt_templates.delete_prompt_template(
            template_id,
            tenant_id=tenant_id,
            account_id="viewer",
            db=db,
        ),
        lambda: prompt_templates.duplicate_prompt_template(
            template_id,
            tenant_id=tenant_id,
            account_id="viewer",
            db=db,
        ),
    )

    for operation in operations:
        with pytest.raises(HTTPException) as exc_info:
            operation()
        assert exc_info.value.status_code == 403
    assert db.commits == 0


def test_industry_rule_write_requires_system_settings_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import industry_rules

    write_called = False

    def _deny(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=403, detail="denied")

    def _write(*_args, **_kwargs) -> dict:
        nonlocal write_called
        write_called = True
        return {"ruleset": "industrial_control", "section": "glossary", "updated_count": 0}

    monkeypatch.setattr(industry_rules, "_ensure_write", _deny, raising=False)
    monkeypatch.setattr(industry_rules, "replace_ruleset_glossary", _write, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        industry_rules.put_industry_ruleset_glossary(
            "industrial_control",
            industry_rules.IndustryRulesGlossaryUpdateRequest(glossary={}),
            tenant_id=uuid4(),
            account_id="viewer",
            db=object(),
        )

    assert exc_info.value.status_code == 403
    assert write_called is False


def test_industry_ruleset_name_cannot_escape_ruleset_root() -> None:
    from app.rag.industry_rules.loaders import replace_ruleset_glossary, ruleset_exists

    assert ruleset_exists("..") is False
    with pytest.raises(FileNotFoundError):
        replace_ruleset_glossary("..", {})


@pytest.mark.asyncio
async def test_cannot_demote_the_only_active_admin() -> None:
    from app.api.v1.rbac import patch_tenant_member_role

    engine = create_engine("sqlite:///:memory:")
    TenantMember.__table__.create(engine)
    tenant_id = uuid4()

    with Session(engine) as db:
        db.add(
            TenantMember(
                tenant_id=tenant_id,
                user_id="only-owner",
                role="owner",
                is_active=True,
                is_current=True,
            )
        )
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            await patch_tenant_member_role(
                "only-owner",
                TenantMemberUpdateRequest(role="viewer"),
                tenant_id=tenant_id,
                account_id="only-owner",
                db=db,
            )

        assert exc_info.value.status_code == 409
        db.expire_all()
        member = db.query(TenantMember).filter(TenantMember.user_id == "only-owner").one()
        assert member.role == "owner"


def test_can_demote_an_admin_when_another_active_admin_remains() -> None:
    from app.api.v1.rbac import patch_tenant_member_role

    engine = create_engine("sqlite:///:memory:")
    TenantMember.__table__.create(engine)
    tenant_id = uuid4()

    with Session(engine) as db:
        db.add_all(
            [
                TenantMember(
                    tenant_id=tenant_id,
                    user_id="owner",
                    role="owner",
                    is_active=True,
                    is_current=True,
                ),
                TenantMember(
                    tenant_id=tenant_id,
                    user_id="admin",
                    role="admin",
                    is_active=True,
                    is_current=True,
                ),
            ]
        )
        db.commit()

        updated = patch_tenant_member_role(
            "admin",
            TenantMemberUpdateRequest(role="viewer"),
            tenant_id=tenant_id,
            account_id="owner",
            db=db,
        )

        assert updated.role == "viewer"
