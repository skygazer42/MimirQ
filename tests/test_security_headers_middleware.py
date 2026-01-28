from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.middleware.security_headers import SecurityHeadersMiddleware


def test_security_headers_middleware_sets_defaults():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():  # noqa: ANN201
        return {"ok": True}

    client = TestClient(app)
    res = client.get("/ping")
    assert res.status_code == 200
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_security_headers_middleware_does_not_override_existing_headers():
    app = FastAPI()
    app.add_middleware(
        SecurityHeadersMiddleware,
        x_content_type_options="nosniff",
        x_frame_options="SAMEORIGIN",
        referrer_policy="no-referrer",
    )

    @app.get("/ping")
    def ping():  # noqa: ANN201
        from fastapi import Response

        resp = Response(content="ok")
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    client = TestClient(app)
    res = client.get("/ping")
    assert res.status_code == 200
    # User-provided response header wins.
    assert res.headers.get("X-Frame-Options") == "DENY"
    # Others are set by middleware.
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("Referrer-Policy") == "no-referrer"

