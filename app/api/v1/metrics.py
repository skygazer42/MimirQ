"""
Prometheus metrics endpoint.
"""

import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.dependencies.auth import get_current_account_id
from app.api.schemas.auth import AuthHeaders
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
    expected = expected_token.strip()
    provided = provided_token.strip()
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
    headers: Annotated[AuthHeaders, Depends()],
) -> None:
    expected_token = str(settings.METRICS_BEARER_TOKEN).strip()
    if expected_token:
        auth = headers.authorization
        if auth is not None:
            auth = auth.strip()
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
        headers=headers,
    )


@router.get("/metrics", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES, dependencies=[Depends(require_metrics_access)])
def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)
