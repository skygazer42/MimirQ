import pytest


def test_decrypt_secret_supports_fallback_keys(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.core.secrets import decrypt_secret, encrypt_secret

    old_key = "old-secret-key-" + ("x" * 40)
    new_key = "new-secret-key-" + ("y" * 40)

    monkeypatch.setattr(settings, "SECRET_KEY", old_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)
    encrypted = encrypt_secret("hello")

    monkeypatch.setattr(settings, "SECRET_KEY", new_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", old_key, raising=False)

    assert decrypt_secret(encrypted) == "hello"


def test_decrypt_secret_raises_without_fallback(monkeypatch):  # noqa: ANN001
    from app.core.config import settings
    from app.core.secrets import decrypt_secret, encrypt_secret

    old_key = "old-secret-key-" + ("x" * 40)
    new_key = "new-secret-key-" + ("y" * 40)

    monkeypatch.setattr(settings, "SECRET_KEY", old_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)
    encrypted = encrypt_secret("hello")

    monkeypatch.setattr(settings, "SECRET_KEY", new_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    with pytest.raises(ValueError):
        decrypt_secret(encrypted)

