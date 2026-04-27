from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field


class OpenFileRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


def create_pre_poc_dashboard_app(
    *,
    render_dashboard_html: Callable[[], str],
    list_events: Callable[[], Iterable[dict[str, Any]]],
    open_file: Callable[[Path], Any] | None = None,
) -> FastAPI:
    app = FastAPI(title="MimirQ Pre-POC Dashboard")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "service": "pre_poc_dashboard"}

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> str:
        return str(render_dashboard_html() or "")

    @app.get("/events")
    def events() -> StreamingResponse:
        def gen():  # noqa: ANN202
            for event in list_events() or []:
                payload = json.dumps(dict(event or {}), ensure_ascii=False)
                yield f"data: {payload}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/open-file")
    def open_file_endpoint(body: OpenFileRequest) -> dict[str, Any]:
        if open_file is None:
            raise HTTPException(status_code=501, detail="open_file_not_configured")
        path = Path(body.path)
        open_file(path)
        return {"ok": True, "path": str(path)}

    return app


__all__ = ["OpenFileRequest", "create_pre_poc_dashboard_app"]
