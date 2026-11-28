from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import JSON, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.api.schemas.conversations.rag_config_templates import RagConfigTemplateNewVersion, RagConfigTemplateUpdate
from app.api.v1.retrieval import config_templates as rag_config_templates
from app.models.audit_log import AuditLog
from app.models.templates.versions import RagConfigTemplate
from app.services.observability.audit_log import audit_log_event


@pytest.fixture
def local_db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    for model in (RagConfigTemplate, AuditLog):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


@pytest.fixture
def current_template(local_db: Session, monkeypatch: pytest.MonkeyPatch) -> RagConfigTemplate:
    template = RagConfigTemplate(
        tenant_id=uuid4(), name="original", template_key="key-1", config_patch={}, is_active=True, ab_weight=1.0
    )
    local_db.add(template)
    local_db.commit()
    monkeypatch.setattr(rag_config_templates.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(rag_config_templates, "_ensure_write", lambda *_args: None)
    return template


def test_template_patch_does_not_restore_old_name_for_an_explicit_empty_value(
    local_db: Session, current_template: RagConfigTemplate
) -> None:
    result = rag_config_templates.update_rag_config_template(
        current_template.id,
        RagConfigTemplateUpdate(name=""),
        tenant_id=current_template.tenant_id,
        account_id="writer",
        db=local_db,
    )
    local_db.refresh(current_template)

    assert result.name == ""
    assert current_template.name == ""


def test_template_version_preserves_zero_experiment_weight(
    local_db: Session, current_template: RagConfigTemplate
) -> None:
    result = rag_config_templates.create_rag_config_template_version(
        current_template.id,
        RagConfigTemplateNewVersion(ab_weight=0.0),
        tenant_id=current_template.tenant_id,
        account_id="writer",
        db=local_db,
    )
    local_db.refresh(result)

    assert result.ab_weight == 0.0
    assert result.parent_id == current_template.id
    assert result.version == 2


@pytest.mark.parametrize("field", ["template_key", "ab_experiment_key", "ab_variant"])
def test_template_patch_keeps_the_supplied_empty_selector(
    local_db: Session, current_template: RagConfigTemplate, field: str
) -> None:
    result = rag_config_templates.update_rag_config_template(
        current_template.id,
        RagConfigTemplateUpdate(**{field: ""}),
        tenant_id=current_template.tenant_id,
        account_id="writer",
        db=local_db,
    )

    assert getattr(result, field) == ""


class _FalsyDetails(dict):
    def __bool__(self) -> bool:
        return False


def test_audit_record_preserves_empty_fields_and_falsy_mapping_contents(local_db: Session) -> None:
    audit_log_event(
        local_db,
        tenant_id=uuid4(),
        actor_id="writer",
        action="record",
        resource_type="",
        resource_id="",
        request_id="",
        ip="",
        user_agent="",
        details=_FalsyDetails(count=0, enabled=False),
    )
    local_db.flush()
    record = local_db.query(AuditLog).one()

    assert record.resource_type == ""
    assert record.resource_id == ""
    assert record.request_id == ""
    assert record.ip == ""
    assert record.user_agent == ""
    assert record.details == {"count": 0, "enabled": False}


def test_scim_audit_preserves_actual_request_metadata(local_db: Session) -> None:
    from starlette.requests import Request

    from app.api.v1.identity.scim import _commit_scim_audit

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"user-agent", b"")]})
    request.state.request_id = ""
    _commit_scim_audit(
        local_db,
        tenant_id=uuid4(),
        actor_id="writer",
        action="scim.read",
        resource_type="user",
        resource_id="user-1",
        http_request=request,
        details={},
    )
    local_db.flush()
    record = local_db.query(AuditLog).one()

    assert record.request_id == ""
    assert record.user_agent == ""


def test_clean_preview_stats_preserve_actual_source_metadata() -> None:
    from app.api.v1.pipelines.support.clean_preview import _clean_preview_rule_stats
    from app.rag.ingestion.governance.cleaning import RegexRule

    records = _clean_preview_rule_stats([RegexRule(pattern="a", repl="b")], [{"source": "", "pack": False}], [0])

    assert records[0]["source"] == ""
    assert records[0]["pack"] is False
    assert records[0]["hits"] == 0
