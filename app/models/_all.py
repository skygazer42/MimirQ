"""Import all SQLAlchemy model modules for metadata registration.

Alembic autogeneration relies on `Base.metadata` to contain *every* table. In this
codebase, not all model modules are imported from `app.models.__init__`, so Alembic
must import them explicitly.

This module should only be imported by tooling (e.g. Alembic) or test code. Importing
it in request paths is discouraged to avoid eager loading side effects.
"""


# Import each module for side effects: table registration into Base.metadata.
from app.models import audit_log as _audit_log  # noqa: F401
from app.models import chat as _chat  # noqa: F401
from app.models import chunk as _chunk  # noqa: F401
from app.models import chunk_preset as _chunk_preset  # noqa: F401
from app.models import connector as _connector  # noqa: F401
from app.models import connector_config as _connector_config  # noqa: F401
from app.models import conversation_summary as _conversation_summary  # noqa: F401
from app.models import dataset as _dataset  # noqa: F401
from app.models import dataset_category as _dataset_category  # noqa: F401
from app.models import dataset_precheck_scan as _dataset_precheck_scan  # noqa: F401
from app.models import dataset_profile_scan as _dataset_profile_scan  # noqa: F401
from app.models import db_catalog as _db_catalog  # noqa: F401
from app.models import document as _document  # noqa: F401
from app.models import evaluation as _evaluation  # noqa: F401
from app.models import evidence as _evidence  # noqa: F401
from app.models import feedback as _feedback  # noqa: F401
from app.models import governance_profile as _governance_profile  # noqa: F401
from app.models import group_permissions as _group_permissions  # noqa: F401
from app.models import index_drift_item as _index_drift_item  # noqa: F401
from app.models import ingest_dead_letter as _ingest_dead_letter  # noqa: F401
from app.models import ingestion_run as _ingestion_run  # noqa: F401
from app.models import prompt_template as _prompt_template  # noqa: F401
from app.models import rag_config_template as _rag_config_template  # noqa: F401
from app.models import tenant as _tenant  # noqa: F401
from app.models import tenant_group as _tenant_group  # noqa: F401
from app.models import user as _user  # noqa: F401
from app.rag.kg import models as _kg_models  # noqa: F401
