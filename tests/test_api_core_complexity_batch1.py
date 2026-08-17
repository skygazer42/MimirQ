from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.api.schemas.rag_config_template import RagConfigTemplateUpdate
from app.api.v1 import rag_config_templates
from app.core.token_utils import total_token_count_from_response


class _TemplateQuery:
    def __init__(self, template: object) -> None:
        self.template = template

    def filter(self, *_args: object) -> _TemplateQuery:
        return self

    def first(self) -> object:
        return self.template


class _TemplateDB:
    def __init__(self, template: object) -> None:
        self.template = template
        self.events: list[str] = []

    def query(self, *_args: object) -> _TemplateQuery:
        return _TemplateQuery(self.template)

    def commit(self) -> None:
        self.events.append("commit")

    def refresh(self, template: object) -> None:
        assert template is self.template
        self.events.append("refresh")


def test_total_token_count_supports_provider_shapes_and_rejects_boolean_counts() -> None:
    assert total_token_count_from_response(SimpleNamespace(usage=SimpleNamespace(total_tokens=12))) == 12
    assert total_token_count_from_response(SimpleNamespace(usage_metadata=SimpleNamespace(total_tokens=13))) == 13
    assert total_token_count_from_response({"usage": {"input_tokens": 5, "output_tokens": 7}}) == 12
    assert total_token_count_from_response({"meta": {"tokens": {"input_tokens": 2, "output_tokens": 3}}}) == 5
    assert total_token_count_from_response({"usage": {"total_tokens": True}}) == 0


def test_update_rag_config_template_applies_explicit_fields_in_one_write(monkeypatch) -> None:
    tenant_id = uuid4()
    template = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        template_key="old-key",
        name="old name",
        description="old",
        config_patch={},
        is_active=False,
        version=1,
        parent_id=None,
        ab_experiment_key=None,
        ab_variant=None,
        ab_weight=1.0,
    )
    db = _TemplateDB(template)
    request = RagConfigTemplateUpdate(
        template_key=" new-key ",
        name=" new name ",
        description=None,
        is_active=True,
        version=2,
        ab_experiment_key=" experiment ",
        ab_variant=" variant ",
        ab_weight=0.4,
    )
    monkeypatch.setattr(rag_config_templates.DatasetService, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(rag_config_templates, "_ensure_write", lambda *_args: None)

    result = rag_config_templates.update_rag_config_template(
        template.id,
        request,
        tenant_id=tenant_id,
        account_id="account-1",
        db=db,
    )

    assert result is template
    assert template.template_key == "new-key"
    assert template.name == "new name"
    assert template.description == "old"
    assert template.is_active is True
    assert template.version == 2
    assert template.ab_experiment_key == "experiment"
    assert template.ab_variant == "variant"
    assert template.ab_weight == 0.4
    assert db.events == ["commit", "refresh"]
