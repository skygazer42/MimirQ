"""
Prometheus metrics endpoint.
"""


from fastapi import APIRouter, Response

from app.core.metrics import render_metrics

router = APIRouter()


@router.get("/metrics")
def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)

