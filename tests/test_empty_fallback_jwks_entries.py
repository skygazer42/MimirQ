import jwt
import pytest

from app.core import jwt_verify


@pytest.mark.asyncio
@pytest.mark.parametrize("key_id", [0, False, [], {}, None, "other"])
async def test_jwks_lookup_keeps_valid_sibling_keys(key_id: object, monkeypatch: pytest.MonkeyPatch) -> None:
    valid_key = {"kid": "wanted", "kty": "oct", "k": "bG9jYWwtdGVzdC1rZXk"}
    calls = []

    async def keys(url: str, *, force_refresh: bool = False):
        calls.append((url, force_refresh))
        return [{"kid": key_id}, valid_key]

    monkeypatch.setattr(jwt_verify.settings, "JWT_JWKS_URLS", "https://issuer.example/keys")
    monkeypatch.setattr(jwt_verify, "_get_jwks_keys", keys)
    token = jwt.encode({"sub": "reader"}, "x" * 32, algorithm="HS256", headers={"kid": "wanted"})

    assert await jwt_verify._jwks_key_for_token(token) is valid_key
    assert calls == [("https://issuer.example/keys", False)]
