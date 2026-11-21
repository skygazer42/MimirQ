"""Register all ORM tables at application, Alembic and database CLI entry points.

Domain packages do not register tables implicitly. Individual consumers import
entities from their actual modules; process entry points load this registry
before using Base.metadata or configuring string relationships.
"""

import app.models.audit_log as _audit_log
import app.models.connectors.configs as _connectors_configs
import app.models.connectors.runs as _connectors_runs
import app.models.conversations.chat as _conversations_chat
import app.models.datasets.access as _datasets_access
import app.models.datasets.catalog as _datasets_catalog
import app.models.datasets.records as _datasets_records
import app.models.datasets.scans as _datasets_scans
import app.models.documents.access as _documents_access
import app.models.documents.indexing as _documents_indexing
import app.models.documents.ingestion as _documents_ingestion
import app.models.documents.records as _documents_records
import app.models.evaluation.evidence as _evaluation_evidence
import app.models.evaluation.results as _evaluation_results
import app.models.identity.accounts as _identity_accounts
import app.models.identity.workspaces as _identity_workspaces
import app.models.knowledge_graph.entities as _knowledge_graph_entities
import app.models.pipelines.profiles as _pipelines_profiles
import app.models.templates.versions as _templates_versions

REGISTERED_MODEL_MODULES = (
    _audit_log,
    _identity_accounts,
    _identity_workspaces,
    _conversations_chat,
    _datasets_records,
    _datasets_access,
    _datasets_scans,
    _datasets_catalog,
    _documents_records,
    _documents_access,
    _documents_ingestion,
    _documents_indexing,
    _connectors_configs,
    _connectors_runs,
    _pipelines_profiles,
    _templates_versions,
    _evaluation_results,
    _evaluation_evidence,
    _knowledge_graph_entities,
)
