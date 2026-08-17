"""Import all SQLAlchemy model modules for metadata registration.

Alembic autogeneration relies on `Base.metadata` to contain *every* table. In this
codebase, not all model modules are imported from `app.models.__init__`, so Alembic
must import them explicitly.

This module should only be imported by tooling (e.g. Alembic) or test code. Importing
it in request paths is discouraged to avoid eager loading side effects.
"""

# Import each module for side effects: table registration into Base.metadata.
from app.models import audit_log as _audit_log
from app.models import chat as _chat
from app.models import chunk as _chunk
from app.models import chunk_preset as _chunk_preset
from app.models import connector as _connector
from app.models import connector_config as _connector_config
from app.models import conversation_summary as _conversation_summary
from app.models import dataset as _dataset
from app.models import dataset_category as _dataset_category
from app.models import dataset_precheck_scan as _dataset_precheck_scan
from app.models import dataset_profile_scan as _dataset_profile_scan
from app.models import db_catalog as _db_catalog
from app.models import document as _document
from app.models import document_index_channel as _document_index_channel
from app.models import evaluation as _evaluation
from app.models import evidence as _evidence
from app.models import feedback as _feedback
from app.models import governance_profile as _governance_profile
from app.models import group_permissions as _group_permissions
from app.models import index_drift_item as _index_drift_item
from app.models import ingest_dead_letter as _ingest_dead_letter
from app.models import ingestion_run as _ingestion_run
from app.models import prompt_template as _prompt_template
from app.models import rag_config_template as _rag_config_template
from app.models import tenant as _tenant
from app.models import tenant_group as _tenant_group
from app.models import user as _user
from app.rag.kg import models as _kg_models

REGISTERED_MODEL_MODULES = (
    _audit_log,
    _chat,
    _chunk,
    _chunk_preset,
    _connector,
    _connector_config,
    _conversation_summary,
    _dataset,
    _dataset_category,
    _dataset_precheck_scan,
    _dataset_profile_scan,
    _db_catalog,
    _document,
    _document_index_channel,
    _evaluation,
    _evidence,
    _feedback,
    _governance_profile,
    _group_permissions,
    _index_drift_item,
    _ingest_dead_letter,
    _ingestion_run,
    _prompt_template,
    _rag_config_template,
    _tenant,
    _tenant_group,
    _user,
    _kg_models,
)
