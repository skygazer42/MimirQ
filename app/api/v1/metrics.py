"""
Prometheus metrics endpoint.
"""


from fastapi import APIRouter, Response

from app.core.metrics import render_metrics

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/metrics", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)

