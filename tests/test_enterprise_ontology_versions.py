from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.knowledge_graph.enterprise_ontology import EnterpriseOntology, EnterpriseOntologyVersion
from app.rag.kg.enterprise_ontology.definition import load_ontology_definition
from app.rag.kg.enterprise_ontology.versions import (
    StaleDraftError,
    create_ontology,
    get_ontology,
    publish_version,
    update_draft,
)
from tests.test_enterprise_ontology_preview import MODEL


def test_published_version_is_immutable_and_tenant_scoped():
    engine = create_engine("sqlite://")
    EnterpriseOntology.__table__.create(engine)
    EnterpriseOntologyVersion.__table__.create(engine)
    tenant_id = uuid4()
    definition = load_ontology_definition(MODEL, format="yaml")
    with Session(engine, expire_on_commit=False) as db:
        workspace = create_ontology(db, tenant_id, definition, account_id="editor")
        assert get_ontology(db, uuid4(), workspace.id) is None
        first = publish_version(db, workspace, expected_revision=1, account_id="publisher")
        assert publish_version(db, workspace, expected_revision=1, account_id="publisher").id == first.id
        payload = definition.model_dump(mode="json", by_alias=True)
        payload["object_types"]["work_order"]["label"] = "维修工单"
        updated = type(definition).model_validate(payload)
        update_draft(db, workspace, updated, expected_revision=1)
        with pytest.raises(StaleDraftError):
            publish_version(db, workspace, expected_revision=1, account_id="publisher")
        second = publish_version(db, workspace, expected_revision=2, account_id="publisher")
        assert second.number == 2
        assert second.definition["object_types"]["work_order"]["label"] == "维修工单"
        assert first.definition["object_types"]["work_order"]["label"] == "工单"
