from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from lxml import etree

from app.core.config import Settings
from app.services import saml_replay_service, saml_service


def _set_valid_production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("JWT_TENANT_CLAIM", "tenant_id")
    monkeypatch.setenv(
        "SAML_PROVIDERS_JSON",
        '[{"id":"default","issuer":"https://idp.example.com","audience":"https://app.example.com/api/saml/metadata",'
        '"acs_url":"https://app.example.com/api/saml/acs","idp_cert_pem":"certificate"}]',
    )


def test_production_saml_requires_redis_replay_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("SAML_REPLAY_REDIS_ENABLED", "false")

    with pytest.raises(ValueError, match="SAML_REPLAY_REDIS_ENABLED"):
        Settings()


def test_production_saml_requires_redis_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("SAML_REPLAY_REDIS_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "")

    with pytest.raises(ValueError, match="REDIS_URL"):
        Settings()


def test_production_saml_accepts_redis_replay_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("SAML_REPLAY_REDIS_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")

    assert Settings().SAML_REPLAY_REDIS_ENABLED is True


def test_redis_replay_cache_failure_rejects_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenRedis:
        def set(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise ConnectionError("redis unavailable")

    invalidated = False

    def _invalidate() -> None:
        nonlocal invalidated
        invalidated = True

    monkeypatch.setattr(saml_replay_service.settings, "SAML_REPLAY_REDIS_ENABLED", True)
    monkeypatch.setattr(saml_replay_service, "_get_redis_client", lambda: BrokenRedis())
    monkeypatch.setattr(saml_replay_service, "_invalidate_redis_client", _invalidate)
    saml_replay_service._memory_seen_until.clear()

    with pytest.raises(HTTPException) as excinfo:
        saml_replay_service.ensure_saml_assertion_not_replayed("assertion-1")

    assert excinfo.value.status_code == 503
    assert invalidated is True
    assert "saml:assertion:assertion-1" not in saml_replay_service._memory_seen_until


def test_in_process_replay_cache_remains_available_when_redis_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(saml_replay_service.settings, "SAML_REPLAY_REDIS_ENABLED", False)
    saml_replay_service._memory_seen_until.clear()

    saml_replay_service.ensure_saml_assertion_not_replayed("assertion-2")

    with pytest.raises(HTTPException) as excinfo:
        saml_replay_service.ensure_saml_assertion_not_replayed("assertion-2")

    assert excinfo.value.status_code == 409


def test_replay_cache_rejects_missing_identifier() -> None:
    with pytest.raises(HTTPException) as excinfo:
        saml_replay_service.ensure_saml_assertion_not_replayed("")

    assert excinfo.value.status_code == 401


@pytest.mark.parametrize(("minimum_ttl_sec", "expected_ttl_sec"), [(60, 300), (420, 420)])
def test_replay_cache_uses_configured_ttl_as_minimum(
    monkeypatch: pytest.MonkeyPatch,
    minimum_ttl_sec: int,
    expected_ttl_sec: int,
) -> None:
    seen_ttls: list[int] = []

    class Redis:
        def set(self, _key, _value, *, ex, nx):  # noqa: ANN001, ANN202
            assert nx is True
            seen_ttls.append(ex)
            return True

    monkeypatch.setattr(saml_replay_service.settings, "SAML_REPLAY_REDIS_ENABLED", True)
    monkeypatch.setattr(saml_replay_service.settings, "SAML_REPLAY_TTL_SEC", 300)
    monkeypatch.setattr(saml_replay_service, "_get_redis_client", lambda: Redis())

    saml_replay_service.ensure_saml_assertion_not_replayed(
        f"assertion-{minimum_ttl_sec}",
        minimum_ttl_sec=minimum_ttl_sec,
    )

    assert seen_ttls == [expected_ttl_sec]


def _saml_condition_nodes(
    *,
    conditions_expires_at: datetime | None,
    subject_expires_at: datetime | None,
) -> tuple[etree._Element, etree._Element, saml_service.SamlProvider]:
    samlp = "urn:oasis:names:tc:SAML:2.0:protocol"
    saml = "urn:oasis:names:tc:SAML:2.0:assertion"
    issuer = "https://idp.example.com"
    audience = "https://app.example.com/api/saml/metadata"
    acs_url = "https://app.example.com/api/saml/acs"

    root = etree.Element(f"{{{samlp}}}Response", Destination=acs_url)
    etree.SubElement(root, f"{{{saml}}}Issuer").text = issuer
    status = etree.SubElement(root, f"{{{samlp}}}Status")
    etree.SubElement(
        status,
        f"{{{samlp}}}StatusCode",
        Value="urn:oasis:names:tc:SAML:2.0:status:Success",
    )
    assertion = etree.SubElement(root, f"{{{saml}}}Assertion", ID="assertion-1")
    etree.SubElement(assertion, f"{{{saml}}}Issuer").text = issuer
    conditions_attrs = {}
    if conditions_expires_at is not None:
        conditions_attrs["NotOnOrAfter"] = conditions_expires_at.isoformat()
    conditions = etree.SubElement(assertion, f"{{{saml}}}Conditions", **conditions_attrs)
    restriction = etree.SubElement(conditions, f"{{{saml}}}AudienceRestriction")
    etree.SubElement(restriction, f"{{{saml}}}Audience").text = audience
    subject = etree.SubElement(assertion, f"{{{saml}}}Subject")
    confirmation = etree.SubElement(subject, f"{{{saml}}}SubjectConfirmation")
    confirmation_attrs = {"Recipient": acs_url}
    if subject_expires_at is not None:
        confirmation_attrs["NotOnOrAfter"] = subject_expires_at.isoformat()
    etree.SubElement(confirmation, f"{{{saml}}}SubjectConfirmationData", **confirmation_attrs)

    provider = saml_service.SamlProvider(
        id="default",
        issuer=issuer,
        audience=audience,
        acs_url=acs_url,
        idp_cert_pem="certificate",
    )
    return root, assertion, provider


def test_saml_conditions_require_expiration() -> None:
    root, assertion, provider = _saml_condition_nodes(
        conditions_expires_at=None,
        subject_expires_at=None,
    )

    with pytest.raises(HTTPException, match="expiration") as excinfo:
        saml_service._validate_conditions(root, assertion, provider, None)

    assert excinfo.value.status_code == 401


def test_saml_replay_ttl_covers_effective_expiration_and_clock_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    root, assertion, provider = _saml_condition_nodes(
        conditions_expires_at=now + timedelta(seconds=120),
        subject_expires_at=now + timedelta(seconds=90),
    )
    monkeypatch.setattr(saml_service.settings, "SAML_ALLOWED_CLOCK_SKEW_SEC", 60)

    replay_ttl_sec = saml_service._validate_conditions(root, assertion, provider, None)

    assert 148 <= replay_ttl_sec <= 151


def test_saml_conditions_reject_assertion_for_caller_supplied_acs_url() -> None:
    root, assertion, provider = _saml_condition_nodes(
        conditions_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        subject_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    caller_acs_url = "https://evil.example.com/api/saml/acs"
    root.set("Destination", caller_acs_url)
    subject_confirmation = assertion.find(
        "./saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData",
        namespaces=saml_service._NS,
    )
    assert subject_confirmation is not None
    subject_confirmation.set("Recipient", caller_acs_url)

    with pytest.raises(HTTPException, match="destination") as excinfo:
        saml_service._validate_conditions(root, assertion, provider, caller_acs_url)

    assert excinfo.value.status_code == 401


def test_saml_exchange_requires_assertion_replay_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    root, assertion, provider = _saml_condition_nodes(
        conditions_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        subject_expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assertion.attrib.pop("ID")
    root.set("ID", "unsigned-response-fallback")
    monkeypatch.setattr(saml_service, "_resolve_provider", lambda _provider_id: provider)
    monkeypatch.setattr(saml_service, "_decode_saml_response", lambda _response: root)
    monkeypatch.setattr(saml_service, "_verify_signature", lambda _root, _provider: assertion)
    monkeypatch.setattr(saml_service, "_validate_conditions", lambda *_args, **_kwargs: 360)
    monkeypatch.setattr(saml_replay_service.settings, "SAML_REPLAY_REDIS_ENABLED", False)
    saml_replay_service._memory_seen_until.clear()

    with pytest.raises(HTTPException, match="replay identifier") as excinfo:
        saml_service.exchange_saml_response(
            db=object(),
            provider_id="default",
            saml_response="response",
        )

    assert excinfo.value.status_code == 401
