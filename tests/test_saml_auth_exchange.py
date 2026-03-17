from __future__ import annotations

import importlib
import json
import uuid
from base64 import b64decode, b64encode
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import HTTPException
from jose import jwt as jose_jwt
from lxml import etree
from signxml import XMLSigner, methods

from app.core.config import settings
from app.models.user import User
from app.services.user_service import UserService

NSMAP = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}

ACS_URL = "https://app.example.com/api/saml/acs"
AUDIENCE = "https://app.example.com/api/saml/metadata"
ISSUER = "https://idp.example.com"


def _import_or_fail(module: str):  # noqa: ANN001
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError:
        pytest.fail(f"Expected module to exist: {module}")


def _build_cert_pair() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MimirQ Test IdP")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return (
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        cert.public_bytes(serialization.Encoding.PEM),
    )


def _saml_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_signed_saml_response(
    *,
    private_key_pem: bytes,
    cert_pem: bytes,
    assertion_id: str | None = None,
    response_id: str | None = None,
    destination: str = ACS_URL,
    audience: str = AUDIENCE,
    issuer: str = ISSUER,
    name_id: str = "alice@example.com",
    email: str = "alice@example.com",
    groups: list[str] | None = None,
    not_before: datetime | None = None,
    not_on_or_after: datetime | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    not_before = not_before or (now - timedelta(minutes=1))
    not_on_or_after = not_on_or_after or (now + timedelta(minutes=5))
    response_id = response_id or f"resp-{uuid.uuid4()}"
    assertion_id = assertion_id or f"assert-{uuid.uuid4()}"
    groups = groups or ["eng", "ml"]

    response = etree.Element(
        f"{{{NSMAP['samlp']}}}Response",
        nsmap=NSMAP,
        ID=response_id,
        Version="2.0",
        IssueInstant=_saml_dt(now),
        Destination=destination,
    )
    etree.SubElement(response, f"{{{NSMAP['saml']}}}Issuer").text = issuer
    status = etree.SubElement(response, f"{{{NSMAP['samlp']}}}Status")
    etree.SubElement(
        status,
        f"{{{NSMAP['samlp']}}}StatusCode",
        Value="urn:oasis:names:tc:SAML:2.0:status:Success",
    )

    assertion = etree.SubElement(
        response,
        f"{{{NSMAP['saml']}}}Assertion",
        ID=assertion_id,
        Version="2.0",
        IssueInstant=_saml_dt(now),
    )
    etree.SubElement(assertion, f"{{{NSMAP['saml']}}}Issuer").text = issuer

    subject = etree.SubElement(assertion, f"{{{NSMAP['saml']}}}Subject")
    etree.SubElement(
        subject,
        f"{{{NSMAP['saml']}}}NameID",
        Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
    ).text = name_id
    confirmation = etree.SubElement(
        subject,
        f"{{{NSMAP['saml']}}}SubjectConfirmation",
        Method="urn:oasis:names:tc:SAML:2.0:cm:bearer",
    )
    etree.SubElement(
        confirmation,
        f"{{{NSMAP['saml']}}}SubjectConfirmationData",
        NotOnOrAfter=_saml_dt(not_on_or_after),
        Recipient=destination,
    )

    conditions = etree.SubElement(
        assertion,
        f"{{{NSMAP['saml']}}}Conditions",
        NotBefore=_saml_dt(not_before),
        NotOnOrAfter=_saml_dt(not_on_or_after),
    )
    audience_restriction = etree.SubElement(conditions, f"{{{NSMAP['saml']}}}AudienceRestriction")
    etree.SubElement(audience_restriction, f"{{{NSMAP['saml']}}}Audience").text = audience

    attributes = etree.SubElement(assertion, f"{{{NSMAP['saml']}}}AttributeStatement")
    email_attr = etree.SubElement(attributes, f"{{{NSMAP['saml']}}}Attribute", Name="email")
    etree.SubElement(email_attr, f"{{{NSMAP['saml']}}}AttributeValue").text = email
    groups_attr = etree.SubElement(attributes, f"{{{NSMAP['saml']}}}Attribute", Name="groups")
    for group in groups:
        etree.SubElement(groups_attr, f"{{{NSMAP['saml']}}}AttributeValue").text = group

    signed_assertion = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
    ).sign(
        assertion,
        key=private_key_pem,
        cert=cert_pem,
        reference_uri=f"#{assertion_id}",
        id_attribute="ID",
    )
    response.replace(assertion, signed_assertion)

    return b64encode(etree.tostring(response, encoding="utf-8")).decode("ascii")


def _configure_saml(monkeypatch: pytest.MonkeyPatch, cert_pem: bytes) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "k" * 40, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_GROUPS_CLAIM", "groups", raising=False)
    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)

    provider = {
        "id": "default",
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "acs_url": ACS_URL,
        "idp_cert_pem": cert_pem.decode("utf-8"),
        "email_attribute": "email",
        "groups_attribute": "groups",
    }
    monkeypatch.setattr(settings, "SAML_PROVIDERS_JSON", json.dumps([provider]), raising=False)
    monkeypatch.setattr(settings, "SAML_ALLOWED_CLOCK_SKEW_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "SAML_REPLAY_TTL_SEC", 300, raising=False)


def _patch_user_resolution(monkeypatch: pytest.MonkeyPatch, *, user: User | None, tenant_id: uuid.UUID | None = None) -> None:
    monkeypatch.setattr(UserService, "get_by_email", staticmethod(lambda _db, _email: user), raising=True)
    monkeypatch.setattr(
        UserService,
        "get_by_username",
        staticmethod(lambda _db, _username: user if user and user.username == _username else None),
        raising=True,
    )
    monkeypatch.setattr(UserService, "mark_login", staticmethod(lambda _db, _user: None), raising=True)
    monkeypatch.setattr(UserService, "get_current_tenant_id", staticmethod(lambda _db, _user_id: tenant_id), raising=True)


def test_exchange_saml_response_returns_auth_session_for_valid_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_or_fail("app.services.saml_service")
    if not hasattr(mod, "exchange_saml_response"):
        pytest.fail("Expected exchange_saml_response()")

    private_key_pem, cert_pem = _build_cert_pair()
    _configure_saml(monkeypatch, cert_pem)

    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="alice@example.com",
        username="alice",
        password_hash="not-used",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        last_login_at=None,
    )
    _patch_user_resolution(monkeypatch, user=user, tenant_id=tenant_id)

    saml_response = _build_signed_saml_response(private_key_pem=private_key_pem, cert_pem=cert_pem)
    session = mod.exchange_saml_response(
        db=object(),
        provider_id="default",
        saml_response=saml_response,
        relay_state="/datasets/123",
        acs_url=ACS_URL,
    )

    assert str(session.user.id) == str(user_id)
    assert session.user.email == "alice@example.com"
    assert session.return_to == "/datasets/123"
    claims = jose_jwt.get_unverified_claims(session.token.access_token)
    assert claims["sub"] == str(user_id)
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["groups"] == ["eng", "ml"]


def test_exchange_saml_response_rejects_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_or_fail("app.services.saml_service")
    if not hasattr(mod, "exchange_saml_response"):
        pytest.fail("Expected exchange_saml_response()")

    private_key_pem, cert_pem = _build_cert_pair()
    _configure_saml(monkeypatch, cert_pem)
    _patch_user_resolution(monkeypatch, user=None)

    saml_response = _build_signed_saml_response(private_key_pem=private_key_pem, cert_pem=cert_pem)
    tampered_xml = b64decode(saml_response.encode("ascii")).replace(b"alice@example.com", b"mallory@example.com")
    tampered = b64encode(tampered_xml).decode("ascii")

    with pytest.raises(HTTPException) as exc:
        mod.exchange_saml_response(
            db=object(),
            provider_id="default",
            saml_response=tampered,
            relay_state="/",
            acs_url=ACS_URL,
        )

    assert exc.value.status_code in {400, 401}


def test_exchange_saml_response_rejects_expired_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_or_fail("app.services.saml_service")
    if not hasattr(mod, "exchange_saml_response"):
        pytest.fail("Expected exchange_saml_response()")

    private_key_pem, cert_pem = _build_cert_pair()
    _configure_saml(monkeypatch, cert_pem)

    user = User(
        id=uuid.uuid4(),
        email="alice@example.com",
        username="alice",
        password_hash="not-used",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        last_login_at=None,
    )
    _patch_user_resolution(monkeypatch, user=user, tenant_id=uuid.uuid4())

    now = datetime.now(timezone.utc)
    saml_response = _build_signed_saml_response(
        private_key_pem=private_key_pem,
        cert_pem=cert_pem,
        not_before=now - timedelta(minutes=10),
        not_on_or_after=now - timedelta(minutes=5),
    )

    with pytest.raises(HTTPException) as exc:
        mod.exchange_saml_response(
            db=object(),
            provider_id="default",
            saml_response=saml_response,
            relay_state="/",
            acs_url=ACS_URL,
        )

    assert exc.value.status_code in {400, 401}


def test_exchange_saml_response_rejects_replayed_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_or_fail("app.services.saml_service")
    if not hasattr(mod, "exchange_saml_response"):
        pytest.fail("Expected exchange_saml_response()")

    private_key_pem, cert_pem = _build_cert_pair()
    _configure_saml(monkeypatch, cert_pem)

    user = User(
        id=uuid.uuid4(),
        email="alice@example.com",
        username="alice",
        password_hash="not-used",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        last_login_at=None,
    )
    _patch_user_resolution(monkeypatch, user=user, tenant_id=uuid.uuid4())

    saml_response = _build_signed_saml_response(
        private_key_pem=private_key_pem,
        cert_pem=cert_pem,
        assertion_id="assert-replay",
        response_id="response-replay",
    )

    first = mod.exchange_saml_response(
        db=object(),
        provider_id="default",
        saml_response=saml_response,
        relay_state="/",
        acs_url=ACS_URL,
    )
    assert first.token.access_token

    with pytest.raises(HTTPException) as exc:
        mod.exchange_saml_response(
            db=object(),
            provider_id="default",
            saml_response=saml_response,
            relay_state="/",
            acs_url=ACS_URL,
        )

    assert exc.value.status_code == 409


def test_exchange_saml_response_rejects_unknown_user(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _import_or_fail("app.services.saml_service")
    if not hasattr(mod, "exchange_saml_response"):
        pytest.fail("Expected exchange_saml_response()")

    private_key_pem, cert_pem = _build_cert_pair()
    _configure_saml(monkeypatch, cert_pem)
    _patch_user_resolution(monkeypatch, user=None)

    saml_response = _build_signed_saml_response(private_key_pem=private_key_pem, cert_pem=cert_pem)

    with pytest.raises(HTTPException) as exc:
        mod.exchange_saml_response(
            db=object(),
            provider_id="default",
            saml_response=saml_response,
            relay_state="/",
            acs_url=ACS_URL,
        )

    assert exc.value.status_code in {403, 404}
