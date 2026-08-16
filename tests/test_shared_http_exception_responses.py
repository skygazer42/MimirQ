from fastapi import FastAPI

from app.api.utils.http_exception_responses import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.api.v1 import document_stats, health, ltr, rbac, reports, rtbf

EXPECTED_DESCRIPTIONS = {
    "400": "Bad Request",
    "403": "Forbidden",
    "404": "Not Found",
    "409": "Conflict",
    "416": "Range Not Satisfiable",
}


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(document_stats.router, prefix="/api/v1/documents")
    app.include_router(rtbf.router, prefix="/api/v1/rtbf")
    app.include_router(reports.router, prefix="/api/v1/reports")
    app.include_router(rbac.router, prefix="/api/v1/rbac")
    app.include_router(ltr.router, prefix="/api/v1/ltr")
    return app


def _assert_default_responses(schema: dict, path: str, method: str) -> None:
    responses = schema["paths"][path][method]["responses"]
    assert {code: responses[code]["description"] for code in EXPECTED_DESCRIPTIONS} == EXPECTED_DESCRIPTIONS


def test_shared_http_exception_responses_match_the_common_contract() -> None:
    assert DEFAULT_HTTP_EXCEPTION_RESPONSES == {
        400: {"description": "Bad Request"},
        403: {"description": "Forbidden"},
        404: {"description": "Not Found"},
        409: {"description": "Conflict"},
        416: {"description": "Range Not Satisfiable"},
    }


def test_selected_routes_reuse_one_shared_http_exception_mapping() -> None:
    route_modules = [health, document_stats, rtbf, reports, rbac, ltr]
    for module in route_modules:
        assert module._DEFAULT_HTTP_EXCEPTION_RESPONSES is DEFAULT_HTTP_EXCEPTION_RESPONSES
        assert module.router.responses is DEFAULT_HTTP_EXCEPTION_RESPONSES


def test_selected_routes_keep_openapi_http_exception_contracts() -> None:
    schema = _build_app().openapi()

    _assert_default_responses(schema, "/api/v1/health", "get")
    _assert_default_responses(schema, "/api/v1/health/ready", "get")
    _assert_default_responses(schema, "/api/v1/documents/stats", "get")
    _assert_default_responses(schema, "/api/v1/rtbf/request", "post")
    _assert_default_responses(schema, "/api/v1/rtbf/status/{ticket_id}", "get")
    _assert_default_responses(schema, "/api/v1/reports/datasets/{dataset_id}", "get")
    _assert_default_responses(schema, "/api/v1/rbac/me", "get")
    _assert_default_responses(schema, "/api/v1/ltr/models", "get")
