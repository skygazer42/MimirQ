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


def test_security_headers_middleware_supports_optional_hardening_headers():
    import inspect

    sig = inspect.signature(SecurityHeadersMiddleware.__init__)
    assert "strict_transport_security" in sig.parameters
    assert "permissions_policy" in sig.parameters
    assert "cross_origin_opener_policy" in sig.parameters
    assert "cross_origin_resource_policy" in sig.parameters

    app = FastAPI()
    app.add_middleware(
        SecurityHeadersMiddleware,
        strict_transport_security="max-age=31536000; includeSubDomains",
        permissions_policy="geolocation=()",
        cross_origin_opener_policy="same-origin",
        cross_origin_resource_policy="same-site",
    )

    @app.get("/ping")
    def ping():  # noqa: ANN201
        return {"ok": True}

    client = TestClient(app)
    res = client.get("/ping")
    assert res.status_code == 200
    assert res.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"
    assert res.headers.get("Permissions-Policy") == "geolocation=()"
    assert res.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
    assert res.headers.get("Cross-Origin-Resource-Policy") == "same-site"
