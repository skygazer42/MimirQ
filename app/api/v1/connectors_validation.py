from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.connector import (
    CONNECTOR_CONFIG_MODELS,
    ConnectorRunConfig,
    ConnectorValidateRequest,
    ConnectorValidateResponse,
    JiraProjectConnectorConfig,
    MySQLCatalogConnectorConfig,
    SQLServerCatalogConnectorConfig,
    UrlBatchConnectorConfig,
    WebCrawlConnectorConfig,
)
from app.api.utils.url_ingest import validate_url_for_ingest
from app.api.v1.connectors_common import _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.connectors.registry import ConnectorNotFoundError
from app.connectors.registry import registry as connector_class_registry
from app.core.database import get_db
from app.core.secrets import redact_secrets
from app.services import dataset_service
from app.services.connector_document_access import _unknown_tenant_groups
from app.services.connector_egress_policy import validate_db_connector_config
from app.services.connector_execution.shared.common import _safe_error_str
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.security_redaction import redact_connection_info

_DB_CONNECTOR_IDS = {"mysql_catalog", "sqlserver_catalog"}
UNSUPPORTED_CONNECTOR_ID_DETAIL = "Unsupported connector_id"
_DB_CONNECTOR_PERMISSION_DETAIL = "No permission to validate DB connector config"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _format_validation_error(exc: ValidationError) -> list[dict[str, Any]]:
    """
    Convert Pydantic ValidationError into a JSON-safe, UI-friendly list.
    """
    out: list[dict[str, Any]] = []
    for e in exc.errors() or []:
        out.append(
            {
                "loc": e.get("loc"),
                "msg": e.get("msg"),
                "type": e.get("type"),
            }
        )
        if len(out) >= 50:
            break
    return out or [{"msg": "invalid config"}]


def _validate_connector_schema(connector_id: str, config: dict[str, Any]) -> tuple[ConnectorRunConfig, dict[str, Any]]:
    config_model = CONNECTOR_CONFIG_MODELS.get(connector_id.strip())
    if config_model is None:
        raise ValueError(UNSUPPORTED_CONNECTOR_ID_DETAIL)
    cfg_obj = config_model.model_validate(config or {})

    # Use JSON mode to ensure the output is JSON-serializable (UUIDs, datetimes, etc.).
    cfg_dict = cfg_obj.model_dump(mode="json", exclude_none=True)
    return cfg_obj, cfg_dict


async def _check_ingest_url_candidates(
    *,
    urls: list[str],
    invalid_code: str,
    check_error_code: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    checked: list[dict[str, Any]] = []
    ok = 0
    warnings: list[dict[str, Any]] = []

    for raw in urls[:3]:
        url = raw.strip()
        if not url:
            continue
        try:
            normalized = await validate_url_for_ingest(url)
            checked.append({"url": url, "ok": True, "normalized_url": normalized})
            ok += 1
        except HTTPException as exc:
            error = exc.detail[:200]
            checked.append({"url": url, "ok": False, "error": error})
            warnings.append({"code": invalid_code, "url": url, "error": error})
        except Exception as exc:  # noqa: BLE001
            error = _safe_error_str(exc)
            checked.append({"url": url, "ok": False, "error": error})
            warnings.append({"code": check_error_code, "url": url, "error": error})

    return {"checked": checked, "ok": ok == len(checked) if checked else True}, warnings


async def _url_ingest_connectivity_check(
    *, cfg: UrlBatchConnectorConfig
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return await _check_ingest_url_candidates(
        urls=cfg.urls,
        invalid_code="url_invalid",
        check_error_code="url_check_error",
    )


async def _web_crawl_connectivity_check(*, cfg: WebCrawlConnectorConfig) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return await _check_ingest_url_candidates(
        urls=cfg.start_urls,
        invalid_code="start_url_invalid",
        check_error_code="start_url_check_error",
    )


def _jira_project_connectivity_check(cfg: JiraProjectConnectorConfig) -> dict[str, Any]:
    base_url = cfg.base_url.strip()
    project_key = cfg.project_key.strip()
    return {
        "ok": bool(base_url and project_key),
        "base_url": base_url,
        "project_key": project_key,
    }


async def _best_effort_connectivity_checks(
    *, connector_id: str, cfg: ConnectorRunConfig
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Run bounded, best-effort connectivity checks.

    These checks are designed to be safe:
    - No large downloads
    - No redirects (SSRF defense-in-depth)
    - Fail-open (warnings) unless schema is invalid
    """
    cid = connector_id.strip()
    if cid == "url_batch":
        url_check, warnings = await _url_ingest_connectivity_check(cfg=cast(UrlBatchConnectorConfig, cfg))
        return {"url_ingest": url_check}, warnings

    if cid == "web_crawl":
        url_check, warnings = await _web_crawl_connectivity_check(cfg=cast(WebCrawlConnectorConfig, cfg))
        return {"url_ingest": url_check}, warnings

    if cid == "jira_project":
        return {"jira_project": _jira_project_connectivity_check(cast(JiraProjectConnectorConfig, cfg))}, []

    if cid in _DB_CONNECTOR_IDS:
        # Patchable helper for unit tests; best-effort, fail-open warnings.
        db_check, db_warn = await _check_db_connectivity_best_effort(
            connector_id=cid,
            cfg=cast(MySQLCatalogConnectorConfig | SQLServerCatalogConnectorConfig, cfg),
        )
        return {"db_connectivity": db_check}, db_warn

    return {}, []


async def _check_db_connectivity_best_effort(
    *, connector_id: str, cfg: MySQLCatalogConnectorConfig | SQLServerCatalogConnectorConfig
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Patchable DB connectivity check helper for validate endpoint.

    Unit tests should monkeypatch this function to avoid real outbound DB calls.
    """

    # Ensure DB catalog connector classes are imported so registration side-effects run.
    from app.connectors import db as db_connectors_module

    _ = db_connectors_module

    cid = connector_id.strip()
    try:
        connector_cls = connector_class_registry.get(cid)
    except ConnectorNotFoundError:
        return {}, []

    connector = connector_cls()
    result = await connector.test_connection(cfg)
    details = result.details
    warnings = details.get("warnings") if isinstance(details.get("warnings"), list) else []
    check: dict[str, Any] = {
        "ok": result.ok,
        "latency_ms": details.get("latency_ms"),
        "read_only": details.get("read_only"),
    }
    if details.get("error"):
        check["error"] = details.get("error")
    elif not result.ok:
        check["error"] = result.message or "connection_failed"
    return check, list(warnings)


@router.post("/validate", response_model=ConnectorValidateResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def validate_connector_config(
    payload: ConnectorValidateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectorValidateResponse:
    """
    Validate connector config (best-effort).

    Returns ok/errors/warnings so UIs can surface issues without throwing hard 4xx/5xx on validation.
    """
    connector_id = payload.connector_id.strip()

    dataset_service.ensure_member(db, tenant_id, account_id)
    if connector_id in _DB_CONNECTOR_IDS:
        ensure_tenant_permission(
            db,
            tenant_id,
            account_id,
            TenantPermissions.SETTINGS_WRITE,
            detail=_DB_CONNECTOR_PERMISSION_DETAIL,
        )

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    cfg_obj: ConnectorRunConfig | None = None
    cfg_dict: dict[str, Any] = {}
    try:
        cfg_obj, cfg_dict = _validate_connector_schema(connector_id, dict(payload.config))
        checks["schema"] = {"ok": True}
    except ValidationError as exc:
        errors = _format_validation_error(exc)
        checks["schema"] = {"ok": False}
    except Exception as exc:  # noqa: BLE001
        errors = [{"msg": _safe_error_str(exc)}]
        checks["schema"] = {"ok": False}

    config_out = redact_secrets(dict(cfg_dict or {}))
    config_out = redact_connection_info(config_out, enabled=connector_id in _DB_CONNECTOR_IDS)

    if not errors and cfg_obj is not None:
        _validate_connector_group_references(
            db,
            tenant_id=tenant_id,
            config=cfg_obj,
            errors=errors,
            checks=checks,
        )

    if not errors and connector_id in _DB_CONNECTOR_IDS and cfg_obj is not None:
        try:
            resolved = validate_db_connector_config(cfg_obj)
            checks["egress"] = {"ok": True, "resolved_addresses": resolved}
        except ValueError as exc:
            errors.append({"loc": ("host",), "msg": str(exc), "type": "value_error"})
            checks["egress"] = {"ok": False, "error": str(exc)}

    if not errors and payload.check_connectivity and cfg_obj is not None:
        more_checks, more_warnings = await _best_effort_connectivity_checks(connector_id=connector_id, cfg=cfg_obj)
        checks.update(more_checks)
        warnings.extend(more_warnings)

    return ConnectorValidateResponse(
        ok=not bool(errors),
        connector_id=connector_id,
        config=config_out,
        errors=errors,
        warnings=warnings,
        checks=checks,
    )


def _validate_connector_group_references(
    db: Session,
    *,
    tenant_id: UUID,
    config: ConnectorRunConfig,
    errors: list[dict[str, Any]],
    checks: dict[str, Any],
) -> None:
    if isinstance(config, (MySQLCatalogConnectorConfig, SQLServerCatalogConnectorConfig)):
        return
    access = config.access
    _record_connector_group_check(
        db,
        tenant_id=tenant_id,
        group_ids=list(access.partial_group_list or []) if access is not None else [],
        location=("access", "partial_group_list"),
        check_name="access_groups",
        errors=errors,
        checks=checks,
    )

    source_acl = config.source_acl
    source_group_ids = [rule.group_id for rule in source_acl.group_mappings] if source_acl is not None else []
    _record_connector_group_check(
        db,
        tenant_id=tenant_id,
        group_ids=source_group_ids,
        location=("source_acl", "group_mappings"),
        check_name="source_acl_groups",
        errors=errors,
        checks=checks,
    )


def _record_connector_group_check(
    db: Session,
    *,
    tenant_id: UUID,
    group_ids: list[UUID],
    location: tuple[str, str],
    check_name: str,
    errors: list[dict[str, Any]],
    checks: dict[str, Any],
) -> None:
    if not group_ids:
        return
    missing = _unknown_tenant_groups(db, tenant_id=tenant_id, group_ids=group_ids)
    if missing:
        errors.append(
            {
                "loc": location,
                "msg": f"Unknown tenant groups: {', '.join(missing[:20])}",
                "type": "value_error",
            }
        )
        checks[check_name] = {"ok": False, "missing": missing[:20], "total_missing": len(missing)}
        return
    checks[check_name] = {"ok": True, "count": len(group_ids)}
