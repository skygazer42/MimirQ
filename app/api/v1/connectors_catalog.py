from fastapi import APIRouter

from app.api.schemas.connector import ConnectorInfo
from app.services.connector_registry import list_connector_definitions

router = APIRouter()


@router.get("")
def list_connectors() -> list[ConnectorInfo]:
    """List available connectors from the shared registry."""
    return [
        ConnectorInfo(
            id=definition.connector_id,
            name=definition.name,
            description=definition.description,
            supports_incremental=definition.supports_incremental,
            supports_resume=definition.supports_resume,
            supports_full_reconcile=definition.supports_full_reconcile,
            sync_cursor_kind=definition.sync_cursor_kind,
        )
        for definition in list_connector_definitions()
    ]
