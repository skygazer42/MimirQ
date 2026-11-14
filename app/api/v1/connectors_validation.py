from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.sources import (
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
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.api.utils.url_ingest import validate_url_for_ingest
from app.connectors.connectivity import check_database_connection
from app.core.async_bridge import run_blocking_in_thread
from app.core.database import SessionLocal
from app.core.secrets import redact_secrets
from app.services import dataset_service
from app.services.connector_document_access import _unknown_tenant_groups
from app.services.connector_egress_policy import validate_db_connector_config
from app.services.connector_execution.shared.common import _safe_error_str
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission
from app.services.security_redaction import redact_connection_info

_DB_CONNECTOR_IDS = frozenset({"mysql_catalog", "sqlserver_catalog"})
_DB_CONFIG_TYPES = (MySQLCatalogConnectorConfig, SQLServerCatalogConnectorConfig)
UNSUPPORTED_CONNECTOR_ID_DETAIL = "Unsupported connector_id"
_DB_CONNECTOR_PERMISSION_DETAIL = "No permission to validate DB connector config"

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _format_validation_error(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
        for error in exc.errors(include_url=False, include_context=False, include_input=False)[:50]
    ]


async def _check_ingest_url_candidates(
    *,
    urls: list[str],
    invalid_code: str,
    check_error_code: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    checked: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for url in urls[:3]:
        try:
            normalized = await validate_url_for_ingest(url)
        except HTTPException as exc:
            code = invalid_code
            error = exc.detail[:200]
        except Exception as exc:  # noqa: BLE001 - optional preflight failures are reported as warnings.
            code = check_error_code
            error = _safe_error_str(exc)
        else:
            checked.append({"url": url, "ok": True, "normalized_url": normalized})
            continue
        checked.append({"url": url, "ok": False, "error": error})
        warnings.append({"code": code, "url": url, "error": error})

    return {"checked": checked, "ok": all(item["ok"] for item in checked)}, warnings


async def _best_effort_connectivity_checks(
    *, config: ConnectorRunConfig
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run the existing bounded preflight supported by each validated config."""
    if isinstance(config, UrlBatchConnectorConfig):
        check, warnings = await _check_ingest_url_candidates(
            urls=config.urls, invalid_code="url_invalid", check_error_code="url_check_error"
        )
        return {"url_ingest": check}, warnings
    if isinstance(config, WebCrawlConnectorConfig):
        check, warnings = await _check_ingest_url_candidates(
            urls=config.start_urls, invalid_code="start_url_invalid", check_error_code="start_url_check_error"
        )
        return {"url_ingest": check}, warnings
    if isinstance(config, JiraProjectConnectorConfig):
        # Jira preflight reports endpoint metadata already checked by its schema.
        return {"jira_project": {"ok": True, "base_url": config.base_url, "project_key": config.project_key}}, []
    if isinstance(config, _DB_CONFIG_TYPES):
        check, warnings = await check_database_connection(config)
        return {"db_connectivity": check}, warnings
    return {}, []


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
        reported_missing = missing[:20]
        errors.append(
            {
                "loc": location,
                "msg": f"Unknown tenant groups: {', '.join(reported_missing)}",
                "type": "value_error",
            }
        )
        checks[check_name] = {"ok": False, "missing": reported_missing, "total_missing": len(missing)}
        return
    checks[check_name] = {"ok": True, "count": len(group_ids)}


def _validate_connector_group_references(
    db: Session,
    *,
    tenant_id: UUID,
    config: ConnectorRunConfig,
    errors: list[dict[str, Any]],
    checks: dict[str, Any],
) -> None:
    if isinstance(config, _DB_CONFIG_TYPES):
        return
    access = config.access
    _record_connector_group_check(
        db,
        tenant_id=tenant_id,
        group_ids=(access.partial_group_list or []) if access is not None else [],
        location=("access", "partial_group_list"),
        check_name="access_groups",
        errors=errors,
        checks=checks,
    )
    source_acl = config.source_acl
    _record_connector_group_check(
        db,
        tenant_id=tenant_id,
        group_ids=[rule.group_id for rule in source_acl.group_mappings] if source_acl is not None else [],
        location=("source_acl", "group_mappings"),
        check_name="source_acl_groups",
        errors=errors,
        checks=checks,
    )


def _validate_connector_config_sync(
    payload: ConnectorValidateRequest,
    *,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> tuple[ConnectorValidateResponse, ConnectorRunConfig | None]:
    """Return expected input errors; hand off a config only when validation succeeds."""
    connector_id = payload.connector_id.strip()
    is_database = connector_id in _DB_CONNECTOR_IDS
    dataset_service.ensure_member(db, tenant_id, account_id)
    if is_database:
        ensure_tenant_permission(
            db,
            tenant_id,
            account_id,
            TenantPermissions.SETTINGS_WRITE,
            detail=_DB_CONNECTOR_PERMISSION_DETAIL,
        )

    config_model = CONNECTOR_CONFIG_MODELS.get(connector_id)
    if config_model is None:
        return ConnectorValidateResponse(
            ok=False,
            connector_id=connector_id,
            errors=[{"msg": UNSUPPORTED_CONNECTOR_ID_DETAIL}],
            checks={"schema": {"ok": False}},
        ), None
    try:
        validated_config = config_model.model_validate(payload.config)
    except ValidationError as exc:
        return ConnectorValidateResponse(
            ok=False,
            connector_id=connector_id,
            errors=_format_validation_error(exc),
            checks={"schema": {"ok": False}},
        ), None

    public_config = redact_secrets(validated_config.model_dump(mode="json", exclude_none=True))
    public_config = redact_connection_info(public_config, enabled=is_database)
    errors: list[dict[str, Any]] = []
    checks: dict[str, Any] = {"schema": {"ok": True}}
    _validate_connector_group_references(db, tenant_id=tenant_id, config=validated_config, errors=errors, checks=checks)
    if is_database and not errors:
        try:
            resolved = validate_db_connector_config(validated_config)
            checks["egress"] = {"ok": True, "resolved_addresses": resolved}
        except ValueError as exc:
            message = str(exc)
            errors.append({"loc": ("host",), "msg": message, "type": "value_error"})
            checks["egress"] = {"ok": False, "error": message}

    response = ConnectorValidateResponse(
        ok=not errors,
        connector_id=connector_id,
        config=public_config,
        errors=errors,
        checks=checks,
    )
    return response, validated_config if response.ok else None


def _prepare_connector_validation(
    payload: ConnectorValidateRequest, *, tenant_id: UUID, account_id: str
) -> tuple[ConnectorValidateResponse, ConnectorRunConfig | None]:
    with SessionLocal() as db:
        return _validate_connector_config_sync(payload, tenant_id=tenant_id, account_id=account_id, db=db)


@router.post("/validate", response_model=ConnectorValidateResponse)
async def validate_connector_config(
    payload: ConnectorValidateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> ConnectorValidateResponse:
    response, config = await run_blocking_in_thread(
        _prepare_connector_validation, payload, tenant_id=tenant_id, account_id=account_id
    )
    if config is None or not payload.check_connectivity:
        return response
    checks, warnings = await _best_effort_connectivity_checks(config=config)
    response.checks.update(checks)
    response.warnings.extend(warnings)
    return response
