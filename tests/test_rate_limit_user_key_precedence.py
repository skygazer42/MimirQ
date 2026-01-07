from __future__ import annotations

from starlette.requests import Request


def _make_request(headers: dict[str, str], *, client_ip: str = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
        "client": (client_ip, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_get_client_key_prefers_jwt_subject_over_x_user_id(monkeypatch):
    import app.api.middleware.rate_limit as rl
    from app.core.config import settings
    from jose import jwt

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    token = jwt.encode({"sub": "jwt-user"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    req = _make_request(
        {
            "X-Tenant-ID": "tenant-1",
            "X-User-ID": "spoofed-user",
            "Authorization": f"Bearer {token}",
        }
    )

    assert rl.get_client_key(req) == "tenant:tenant-1:user:jwt-user"


def test_get_client_key_header_mode_uses_x_user_id(monkeypatch):
    import app.api.middleware.rate_limit as rl
    from app.core.config import settings
    from jose import jwt

    monkeypatch.setattr(settings, "AUTH_MODE", "header", raising=False)
    token = jwt.encode({"sub": "jwt-user"}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    req = _make_request(
        {
            "X-User-ID": "header-user",
            "Authorization": f"Bearer {token}",
        }
    )

    assert rl.get_client_key(req) == "user:header-user"


def test_get_client_key_jwt_mode_ignores_x_user_id_without_token(monkeypatch):
    import app.api.middleware.rate_limit as rl
    from app.core.config import settings

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)

    req = _make_request(
        {
            "X-Tenant-ID": "tenant-1",
            "X-User-ID": "spoofed-user",
        },
        client_ip="10.0.0.9",
    )

    assert rl.get_client_key(req) == "tenant:tenant-1:ip:10.0.0.9"

