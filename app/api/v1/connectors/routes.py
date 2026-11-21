"""Assemble connector catalog, validation, configuration, runs, and schedules."""

from fastapi import APIRouter

from app.api.v1.connectors import catalog as connectors_catalog
from app.api.v1.connectors import configs as connectors_configs
from app.api.v1.connectors import runs as connectors_runs
from app.api.v1.connectors import schedules as connectors_schedules
from app.api.v1.connectors import validation as connectors_validation

router = APIRouter()
# The catalog's empty path is mounted as /connectors by the parent router.
router.routes.extend(connectors_catalog.router.routes)
router.routes.extend(connectors_validation.router.routes)
router.routes.extend(connectors_runs.router.routes)
router.routes.extend(connectors_configs.router.routes)
router.routes.extend(connectors_schedules.router.routes)
