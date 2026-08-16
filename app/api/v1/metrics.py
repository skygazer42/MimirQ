"""
Prometheus metrics endpoint.
"""


import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from app.api.dependencies.auth import get_current_account_id
from app.core.config import settings
from app.core.metrics import render_metrics

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _token_matches(*, provided_token: str, expected_token: str) -> bool:
    expected = str(expected_token or "").strip()
    provided = str(provided_token or "").strip()
    if not expected or not provided:
        return False
    if expected.lower().startswith("sha256:"):
        digest = expected.split(":", 1)[1].strip().lower()
        if not digest:
            return False
        provided_digest = hashlib.sha256(provided.encode("utf-8", "ignore")).hexdigest()
        return hmac.compare_digest(provided_digest, digest)
    return hmac.compare_digest(provided, expected)


async def require_metrics_access(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> None:
    expected_token = str(getattr(settings, "METRICS_BEARER_TOKEN", "") or "").strip()
    if expected_token:
        auth = str(authorization or "").strip()
        if not auth:
            raise HTTPException(status_code=401, detail="Authorization header required")
        if not auth.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        token = auth[7:].strip()
        if not _token_matches(provided_token=token, expected_token=expected_token):
            raise HTTPException(status_code=401, detail="Unauthorized")
        request.state.user_id = "system:metrics"
        return

    await get_current_account_id(
        request=request,
        authorization=authorization,
        x_user_id=x_user_id,
        x_tenant_id=x_tenant_id,
    )


@router.get("/metrics", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES, dependencies=[Depends(require_metrics_access)])
def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
