import pytest
from pydantic import ValidationError

from app.core import jwt_verify
from app.core.config import Settings


def _set_minimal_prod_jwt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("JWT_TENANT_CLAIM", "tid")


def test_production_rejects_non_https_jwks_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_minimal_prod_jwt_env(monkeypatch)

    with pytest.raises(ValidationError, match="JWT_JWKS_URLS must use https"):
        Settings.model_validate(
            {
                "ALGORITHM": "RS256",
                "JWT_JWKS_URLS": "http://issuer.example/.well-known/jwks.json",
            }
        )


def test_production_rejects_non_https_jwt_issuer_for_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_minimal_prod_jwt_env(monkeypatch)

    with pytest.raises(ValidationError, match="JWT_ISSUER must use https"):
        Settings.model_validate(
            {
                "ALGORITHM": "RS256",
                "JWT_JWKS_DISCOVERY_ENABLED": True,
                "JWT_ISSUER": "http://issuer.example",
            }
        )


def test_non_production_allows_localhost_http_jwks_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV", raising=False)

    settings_obj = Settings.model_validate(
        {
            "SECRET_KEY": "x" * 32,
            "ALGORITHM": "RS256",
            "JWT_JWKS_URLS": "http://127.0.0.1:8001/.well-known/jwks.json",
        }
    )

    assert settings_obj.JWT_JWKS_URLS == "http://127.0.0.1:8001/.well-known/jwks.json"


@pytest.mark.asyncio
async def test_fetch_jwks_rejects_https_to_http_redirect_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResponse:
        def __init__(self) -> None:
            self.url = "http://issuer.example/.well-known/jwks.json"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"keys": [{"kid": "k1"}]}

    class _FakeClient:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        async def get(self, url: str):
            return _FakeResponse()

    monkeypatch.setattr(jwt_verify.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(ValueError, match="insecure_jwks_response_url"):
        await jwt_verify._fetch_jwks_keys("https://issuer.example/.well-known/jwks.json")


@pytest.mark.asyncio
async def test_fetch_jwks_rejects_http_hop_even_when_terminal_url_is_https(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Hop:
        url = "http://issuer.example/redirect"

    class _FakeResponse:
        url = "https://issuer.example/.well-known/jwks.json"
        history = [_Hop()]

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"keys": [{"kid": "k1"}]}

    class _FakeClient:
        def __init__(self, **_kwargs) -> None:  # noqa: ANN003
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        async def get(self, _url: str):
            return _FakeResponse()

    monkeypatch.setattr(jwt_verify.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(ValueError, match="insecure_jwks_response_url"):
        await jwt_verify._fetch_jwks_keys("https://issuer.example/.well-known/jwks.json")


@pytest.mark.asyncio
async def test_fetch_oidc_configuration_rejects_https_to_http_redirect_downgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeResponse:
        def __init__(self) -> None:
            self.url = "http://issuer.example/.well-known/openid-configuration"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"jwks_uri": "https://issuer.example/.well-known/jwks.json"}

    class _FakeClient:
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
            return None

        async def get(self, url: str):
            return _FakeResponse()

    monkeypatch.setattr(jwt_verify.httpx, "AsyncClient", _FakeClient)

    with pytest.raises(ValueError, match="insecure_oidc_discovery_url"):
        await jwt_verify._fetch_oidc_configuration("https://issuer.example/.well-known/openid-configuration")


@pytest.mark.asyncio
async def test_oidc_discovery_rejects_non_https_jwks_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setattr(settings := jwt_verify.settings, "JWT_OIDC_DISCOVERY_CACHE_TTL_SEC", 3600, raising=False)
    monkeypatch.setattr(settings, "JWT_OIDC_DISCOVERY_MAX_STALE_SEC", 0, raising=False)
    monkeypatch.setattr(jwt_verify, "_oidc_cache", {}, raising=False)

    async def _fake_fetch(url: str) -> dict:
        return {"jwks_uri": "http://issuer.example/.well-known/jwks.json"}

    monkeypatch.setattr(jwt_verify, "_fetch_oidc_configuration", _fake_fetch)

    with pytest.raises(ValueError, match="invalid_oidc_jwks_uri"):
        await jwt_verify._get_oidc_jwks_uri("https://issuer.example")
