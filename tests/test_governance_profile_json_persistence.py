from datetime import UTC, datetime
from uuid import uuid4
import json

import pytest
from sqlalchemy.dialects import postgresql

from app.api.schemas.governance_profile import (
    GovernanceProfileCreate, GovernanceProfilePayload, GovernanceProfileUpdate,
)
from app.models.governance_profile import GovernanceProfile


class ProfileSession:
    """Exercise the same JSONB bind serializer without touching a business row."""
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.encode = postgresql.JSONB().bind_processor(postgresql.dialect())

    def query(self, _column):
        return self

    def filter(self, *_clauses):
        return self

    def first(self):
        return None

    def add(self, row):
        row.id = uuid4()
        row.created_at = row.updated_at = datetime.now(UTC)
        self.rows.append(row)

    def flush(self):
        for row in self.rows:
            row.payload = json.loads(self.encode(row.payload))

    def commit(self):
        self.flush()

    def refresh(self, _row):
        pass


def script_payload():
    return GovernanceProfilePayload(processing_scripts=[{
        'name': 'draft.py', 'language': 'python', 'content': '# review attachment',
        'enabled': False, 'created_at': datetime(2026, 10, 27, 1, 0, tzinfo=UTC),
    }])


@pytest.mark.parametrize('operation', ['create', 'update'])
def test_profile_endpoints_store_timestamped_drafts_as_json(monkeypatch, operation):
    from app.api.v1 import pipeline
    tenant_id, account_id = uuid4(), str(uuid4())
    member_checks = []
    monkeypatch.setattr(pipeline.DatasetService, 'ensure_member', lambda db, tenant, account: member_checks.append((tenant, account)))
    db = ProfileSession()
    if operation == 'create':
        result = pipeline.create_governance_profile(
            GovernanceProfileCreate(name='JSON timestamp test', key='json-timestamp-test', payload=script_payload()),
            tenant_id=tenant_id, account_id=account_id, db=db,
        )
    else:
        row = GovernanceProfile(id=uuid4(), tenant_id=tenant_id, key='json-timestamp-test', name='JSON timestamp test', payload={})
        db.add(row)
        monkeypatch.setattr(pipeline, '_resolve_custom_profile_row', lambda **_kwargs: row)
        result = pipeline.update_governance_profile(
            str(row.id), GovernanceProfileUpdate(payload=script_payload()),
            tenant_id=tenant_id, account_id=account_id, db=db,
        )
    stored = db.rows[0].payload['processing_scripts'][0]
    assert isinstance(stored['created_at'], str)
    assert stored['enabled'] is False
    assert result.payload.processing_scripts[0].created_at == script_payload().processing_scripts[0].created_at
    assert member_checks == [(tenant_id, account_id)]


@pytest.mark.parametrize('overwrite', [False, True])
def test_profile_import_preserves_timestamped_drafts_in_json(monkeypatch, overwrite):
    from app.api.v1.pipeline_support import governance_profiles as owner
    tenant_id = uuid4()
    row = GovernanceProfile(id=uuid4(), tenant_id=tenant_id, key='json-timestamp-test', name='Previous', payload={}) if overwrite else None
    db = ProfileSession([row] if row is not None else [])
    monkeypatch.setattr(owner, '_find_existing_governance_profile', lambda *_args: row)
    record = owner._GovernanceProfileImportRecord(name='Imported', key='json-timestamp-test', description=None, payload=script_payload())
    owner._upsert_governance_profile_import_record(db=db, tenant_id=tenant_id, record=record, overwrite=overwrite)
    db.commit()
    stored = db.rows[0].payload['processing_scripts'][0]
    assert isinstance(stored['created_at'], str)
    assert stored['content'] == '# review attachment'
    assert stored['enabled'] is False
