"""Assemble connector catalog, validation, configuration, runs, and schedules."""

from fastapi import APIRouter

from app.api.v1 import (
    connectors_catalog,
    connectors_configs,
    connectors_runs,
    connectors_schedules,
    connectors_validation,
)

router = APIRouter()
# The catalog's empty path is mounted as /connectors by the parent router.
router.routes.extend(connectors_catalog.router.routes)
router.routes.extend(connectors_validation.router.routes)
router.routes.extend(connectors_runs.router.routes)
router.routes.extend(connectors_configs.router.routes)
router.routes.extend(connectors_schedules.router.routes)
