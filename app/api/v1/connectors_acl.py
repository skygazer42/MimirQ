
import contextlib
import sys
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.document import Document as DBDocument
from app.rag.core.logging import get_logger
from app.services.document_permission_service import (
    DocumentGroupPermissionService,
    DocumentPermissionService,
)

_leader_module = None
_CONNECTORS_MODULE_NAME = "app.api.v1.connectors"
logger = get_logger(__name__)


def _resolve_acl_helper(name: str):  # noqa: ANN202
    local_helper = globals().get(name)
    real_module = sys.modules.get(_CONNECTORS_MODULE_NAME)
    real_helper = getattr(real_module, name, None) if real_module is not None else None
    if (
        callable(real_helper)
        and real_helper is not local_helper
        and str(getattr(real_helper, "__module__", "")) != _CONNECTORS_MODULE_NAME
    ):
        return real_helper

    leader = globals().get("_leader_module")
    helper = getattr(leader, name, None) if leader is not None else None
    leader_name = str(getattr(leader, "__name__", "") or "")
    if callable(helper) and helper is not local_helper and leader_name.startswith("test_"):
        return helper
    if callable(helper) and helper is not local_helper:
        return helper

    if callable(real_helper) and real_helper is not local_helper:
        return real_helper

    preferred_modules = (
        _CONNECTORS_MODULE_NAME,
        "test_saved_state_connectors",
        "test_support_connectors_module",
    )
    for module_name in preferred_modules:
        for key, module in sys.modules.items():
            if key == module_name or key.startswith(f"{module_name}_"):
                helper = getattr(module, name, None) if module is not None else None
                if callable(helper):
                    return helper
    helper = globals().get(name)
    if callable(helper):
        return helper
    raise RuntimeError(f"connectors acl helper not available: {name}")


def _now():
    helper = _resolve_acl_helper("_now")
    if helper is not _now:
        return helper()
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _apply_document_access_from_config(
    db: Session,
    *,
    tenant_id: UUID,
    requested_by: str,
    doc,  # noqa: ANN001
    access: dict | None,
    connector_id: str | None = None,
) -> None:
    access_mode = (
        str(access.get("mode") or "inherit").strip().lower()
        if isinstance(access, dict)
        else "inherit"
    )
    access_members = access.get("partial_member_list") if isinstance(access, dict) else None
    if not isinstance(access_members, list):
        access_members = []
    access_members = [
        str(v).strip()
        for v in access_members
        if isinstance(v, (str, int, float)) and str(v).strip()
    ]
    access_groups = access.get("partial_group_list") if isinstance(access, dict) else None
    if not isinstance(access_groups, list):
        access_groups = []
    access_groups = [
        str(v).strip()
        for v in access_groups
        if isinstance(v, (str, int, float)) and str(v).strip()
    ]

    try:
        doc.access_mode = None if access_mode == "inherit" else access_mode
        if not (getattr(doc, "owner_id", None) or "").strip():
            doc.owner_id = requested_by

        if access_mode == "partial_members":
            DocumentPermissionService.update_partial_member_list(
                db, tenant_id, doc.id, list(access_members)
            )
            DocumentGroupPermissionService.update_partial_group_list(
                db, tenant_id, doc.id, list(access_groups)
            )
        else:
            DocumentPermissionService.clear_partial_member_list(
                db, tenant_id, doc.id
            )
            DocumentGroupPermissionService.clear_partial_group_list(
                db, tenant_id, doc.id
            )
    except Exception:
        with contextlib.suppress(Exception):
            from app.services.connector_acl_prometheus_metrics import (
                observe_connector_acl_apply_error,
            )

            observe_connector_acl_apply_error(
                connector_id=connector_id, mode=access_mode
            )
        raise
    else:
        with contextlib.suppress(Exception):
            from app.services.connector_acl_prometheus_metrics import (
                observe_connector_acl_apply,
            )

            observe_connector_acl_apply(
                connector_id=connector_id,
                mode=access_mode,
                member_count=len(access_members),
                group_count=len(access_groups),
            )


def _delta_sync_connector_documents_acl_by_source_url(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    connector_id: str,
    source_url: str,
    requested_by: str,
    access: dict | None,
    acl_provenance: dict | None,
    max_docs: int = 50_000,
) -> int:
    if dataset_id is None:
        return 0
    source_url = str(source_url or "").strip()
    if not source_url:
        return 0

    q = (
        db.query(DBDocument)
        .join(ConnectorRunDocument, ConnectorRunDocument.document_id == DBDocument.id)
        .join(ConnectorRun, ConnectorRun.id == ConnectorRunDocument.run_id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
            ConnectorRun.tenant_id == tenant_id,
            ConnectorRun.dataset_id == dataset_id,
            ConnectorRun.connector_id == str(connector_id or "").strip(),
        )
        .filter(DBDocument.doc_metadata["source_url"].astext == source_url)  # type: ignore[attr-defined]
        .distinct()
        .order_by(DBDocument.created_at.desc())
    )

    max_docs = max(0, int(max_docs or 0))
    if max_docs:
        q = q.limit(max_docs)

    updated = 0
    for doc in q.yield_per(200):
        _resolve_acl_helper("_apply_document_access_from_config")(
            db,
            tenant_id=tenant_id,
            requested_by=requested_by,
            doc=doc,
            access=access,
            connector_id=connector_id,
        )
        if isinstance(acl_provenance, dict):
            try:
                meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                meta0["acl_provenance"] = dict(acl_provenance)
                doc.doc_metadata = meta0
            except Exception as exc:
                logger.debug("Ignoring connector ACL provenance metadata update failure: %s", exc)
        updated += 1

    return int(updated)


def _soft_disable_connector_documents_by_source_url(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    connector_id: str,
    source_url: str,
    connector_config_id: UUID | None = None,
    max_docs: int = 50_000,
) -> int:
    if dataset_id is None:
        return 0
    source_url = str(source_url or "").strip()
    if not source_url:
        return 0

    q = (
        db.query(DBDocument)
        .join(ConnectorRunDocument, ConnectorRunDocument.document_id == DBDocument.id)
        .join(ConnectorRun, ConnectorRun.id == ConnectorRunDocument.run_id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
            ConnectorRun.tenant_id == tenant_id,
            ConnectorRun.dataset_id == dataset_id,
            ConnectorRun.connector_id == str(connector_id or "").strip(),
        )
        .filter(DBDocument.doc_metadata["source_url"].astext == source_url)  # type: ignore[attr-defined]
        .distinct()
        .order_by(DBDocument.created_at.desc())
    )
    if connector_config_id is not None:
        q = q.filter(ConnectorRun.stats["config_id"].astext == str(connector_config_id))  # type: ignore[attr-defined]

    max_docs = max(0, int(max_docs or 0))
    if max_docs:
        q = q.limit(max_docs)

    now = _now()
    disabled = 0
    for doc in q.yield_per(200):
        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            disabled += 1

    return int(disabled)


def _soft_disable_connector_documents_by_source_ref(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    connector_id: str,
    source_ref: str,
    connector_config_id: UUID | None = None,
    exclude_document_id: UUID | None = None,
    max_docs: int = 50_000,
) -> int:
    if dataset_id is None:
        return 0
    source_ref = str(source_ref or "").strip()
    if not source_ref:
        return 0

    q = (
        db.query(DBDocument)
        .join(ConnectorRunDocument, ConnectorRunDocument.document_id == DBDocument.id)
        .join(ConnectorRun, ConnectorRun.id == ConnectorRunDocument.run_id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.dataset_id == dataset_id,
            DBDocument.archived_at.is_(None),
            DBDocument.disabled_at.is_(None),
            ConnectorRun.tenant_id == tenant_id,
            ConnectorRun.dataset_id == dataset_id,
            ConnectorRun.connector_id == str(connector_id or "").strip(),
            ConnectorRunDocument.source_ref == source_ref,
        )
        .distinct()
        .order_by(DBDocument.created_at.desc())
    )
    if connector_config_id is not None:
        q = q.filter(ConnectorRun.stats["config_id"].astext == str(connector_config_id))  # type: ignore[attr-defined]
    if exclude_document_id is not None:
        q = q.filter(DBDocument.id != exclude_document_id)

    max_docs = max(0, int(max_docs or 0))
    if max_docs:
        q = q.limit(max_docs)

    now = _now()
    disabled = 0
    for doc in q.yield_per(200):
        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            disabled += 1

    return int(disabled)


def _delta_sync_jira_documents_acl_by_issue_url(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    project_key: str,
    issue_url: str,
    requested_by: str,
    access: dict | None,
    acl_provenance: dict | None,
    max_docs_scan: int = 5000,
) -> int:
    if dataset_id is None:
        return 0

    base_url = str(base_url or "").strip().rstrip("/")
    project_key = str(project_key or "").strip().upper()
    issue_url = str(issue_url or "").strip()
    if not base_url or not project_key or not issue_url:
        return 0

    updated = 0
    try:
        q = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "jira_project")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["project_key"].astext == project_key)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["issue_url"].astext == issue_url)  # type: ignore[attr-defined]
            .order_by(DBDocument.created_at.desc())
        )
        for doc in q.yield_per(200):
            _resolve_acl_helper("_apply_document_access_from_config")(
                db,
                tenant_id=tenant_id,
                requested_by=requested_by,
                doc=doc,
                access=access,
                connector_id="jira_project",
            )
            if isinstance(acl_provenance, dict):
                try:
                    meta0 = dict(getattr(doc, "doc_metadata", None) or {})
                    meta0["acl_provenance"] = dict(acl_provenance)
                    doc.doc_metadata = meta0
                except Exception as exc:
                    logger.debug("Ignoring Jira connector ACL provenance metadata update failure: %s", exc)
            updated += 1
    except Exception:
        max_docs_scan = max(0, int(max_docs_scan or 0))
        if max_docs_scan <= 0:
            max_docs_scan = 5000
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .order_by(DBDocument.created_at.desc())
            .limit(max_docs_scan)
            .all()
        )
        for doc in docs or []:
            meta = (
                doc.doc_metadata
                if isinstance(getattr(doc, "doc_metadata", None), dict)
                else {}
            )
            conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
            if str(conn.get("connector_id") or "") != "jira_project":
                continue
            if str(conn.get("base_url") or "").strip().rstrip("/") != base_url:
                continue
            if str(conn.get("project_key") or "").strip().upper() != project_key:
                continue
            if str(conn.get("issue_url") or "").strip() != issue_url:
                continue
            _resolve_acl_helper("_apply_document_access_from_config")(
                db,
                tenant_id=tenant_id,
                requested_by=requested_by,
                doc=doc,
                access=access,
                connector_id="jira_project",
            )
            if isinstance(acl_provenance, dict):
                try:
                    meta0 = dict(meta or {})
                    meta0["acl_provenance"] = dict(acl_provenance)
                    doc.doc_metadata = meta0
                except Exception as exc:
                    logger.debug("Ignoring Jira connector ACL provenance fallback metadata update failure: %s", exc)
            updated += 1

    return int(updated)


def _soft_disable_jira_attachment_documents_missing_from_issue(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    project_key: str,
    issue_url: str,
    seen_attachment_urls: set[str],
    max_docs_scan: int = 5000,
) -> int:
    if dataset_id is None:
        return 0

    base_url = str(base_url or "").strip().rstrip("/")
    project_key = str(project_key or "").strip().upper()
    issue_url = str(issue_url or "").strip()
    seen_urls = {
        str(url or "").strip()
        for url in (seen_attachment_urls or set())
        if str(url or "").strip()
    }
    if not base_url or not project_key or not issue_url:
        return 0

    docs: list[Any]
    try:
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "jira_project")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["doc_kind"].astext == "attachment")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["project_key"].astext == project_key)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["issue_url"].astext == issue_url)  # type: ignore[attr-defined]
            .order_by(DBDocument.created_at.desc())
            .all()
        )
    except Exception:
        max_docs_scan = max(0, int(max_docs_scan or 0))
        if max_docs_scan <= 0:
            max_docs_scan = 5000
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .order_by(DBDocument.created_at.desc())
            .limit(max_docs_scan)
            .all()
        )

    now = _now()
    disabled = 0
    for doc in docs or []:
        meta = (
            doc.doc_metadata
            if isinstance(getattr(doc, "doc_metadata", None), dict)
            else {}
        )
        conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
        if str(conn.get("connector_id") or "") != "jira_project":
            continue
        if str(conn.get("doc_kind") or "") != "attachment":
            continue
        if str(conn.get("base_url") or "").strip().rstrip("/") != base_url:
            continue
        if str(conn.get("project_key") or "").strip().upper() != project_key:
            continue
        if str(conn.get("issue_url") or "").strip() != issue_url:
            continue

        download_url = str(conn.get("download_url") or meta.get("source_url") or "").strip()
        if not download_url or download_url in seen_urls:
            continue

        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            disabled += 1

    return int(disabled)


def _soft_disable_jira_linked_artifact_documents_missing_from_issue(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    base_url: str,
    project_key: str,
    issue_url: str,
    seen_link_urls: set[str],
    max_docs_scan: int = 5000,
) -> int:
    if dataset_id is None:
        return 0

    base_url = str(base_url or "").strip().rstrip("/")
    project_key = str(project_key or "").strip().upper()
    issue_url = str(issue_url or "").strip()
    seen_urls = {
        str(url or "").strip()
        for url in (seen_link_urls or set())
        if str(url or "").strip()
    }
    if not base_url or not project_key or not issue_url:
        return 0

    docs: list[Any]
    try:
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .filter(DBDocument.doc_metadata["connector"]["connector_id"].astext == "jira_project")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["doc_kind"].astext == "linked_artifact")  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["base_url"].astext == base_url)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["project_key"].astext == project_key)  # type: ignore[attr-defined]
            .filter(DBDocument.doc_metadata["connector"]["issue_url"].astext == issue_url)  # type: ignore[attr-defined]
            .order_by(DBDocument.created_at.desc())
            .all()
        )
    except Exception:
        max_docs_scan = max(0, int(max_docs_scan or 0))
        if max_docs_scan <= 0:
            max_docs_scan = 5000
        docs = (
            db.query(DBDocument)
            .filter(
                DBDocument.tenant_id == tenant_id,
                DBDocument.dataset_id == dataset_id,
                DBDocument.archived_at.is_(None),
                DBDocument.disabled_at.is_(None),
            )
            .order_by(DBDocument.created_at.desc())
            .limit(max_docs_scan)
            .all()
        )

    now = _now()
    disabled = 0
    for doc in docs or []:
        meta = (
            doc.doc_metadata
            if isinstance(getattr(doc, "doc_metadata", None), dict)
            else {}
        )
        conn = meta.get("connector") if isinstance(meta.get("connector"), dict) else {}
        if str(conn.get("connector_id") or "") != "jira_project":
            continue
        if str(conn.get("doc_kind") or "") != "linked_artifact":
            continue
        if str(conn.get("base_url") or "").strip().rstrip("/") != base_url:
            continue
        if str(conn.get("project_key") or "").strip().upper() != project_key:
            continue
        if str(conn.get("issue_url") or "").strip() != issue_url:
            continue

        artifact_url = str(conn.get("artifact_url") or meta.get("source_url") or "").strip()
        if not artifact_url or artifact_url in seen_urls:
            continue

        if getattr(doc, "disabled_at", None) is None:
            doc.disabled_at = now
            disabled += 1

    return int(disabled)
