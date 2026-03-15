from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLVerifier

from app.core.config import settings
from app.services.saml_service import build_saml_sp_metadata_xml

ACS_URL = "https://app.example.com/api/saml/acs"
AUDIENCE = "https://app.example.com/api/saml/metadata"
ISSUER = "https://idp.example.com"

MD_NS = "urn:oasis:names:tc:SAML:2.0:metadata"
DS_NS = "http://www.w3.org/2000/09/xmldsig#"


def _build_cert_pair(*, common_name: str) -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=30))
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


def _pem_cert_to_b64(cert_pem: bytes) -> str:
    text = cert_pem.decode("utf-8")
    return "".join(
        line.strip()
        for line in text.splitlines()
        if line.strip() and "BEGIN CERTIFICATE" not in line and "END CERTIFICATE" not in line
    )


def _configure_provider(monkeypatch: pytest.MonkeyPatch, *, idp_cert_pem: bytes) -> None:
    provider = {
        "id": "default",
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "acs_url": ACS_URL,
        "idp_cert_pem": idp_cert_pem.decode("utf-8"),
        "email_attribute": "email",
        "groups_attribute": "groups",
    }
    monkeypatch.setattr(settings, "SAML_PROVIDERS_JSON", json.dumps([provider]), raising=False)


def test_build_saml_sp_metadata_includes_key_descriptor_when_sp_cert_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _idp_key_pem, idp_cert_pem = _build_cert_pair(common_name="MimirQ Test IdP")
    _configure_provider(monkeypatch, idp_cert_pem=idp_cert_pem)

    sp_key_pem, sp_cert_pem = _build_cert_pair(common_name="MimirQ Test SP")
    monkeypatch.setattr(settings, "SAML_SP_CERT_PEM", sp_cert_pem.decode("utf-8"), raising=False)
    monkeypatch.setattr(settings, "SAML_SP_PRIVATE_KEY_PEM", sp_key_pem.decode("utf-8"), raising=False)
    monkeypatch.setattr(settings, "SAML_SP_METADATA_SIGNED", False, raising=False)

    xml = build_saml_sp_metadata_xml(provider_id="default")
    root = etree.fromstring(xml.encode("utf-8"))

    assert root.tag == f"{{{MD_NS}}}EntityDescriptor"
    assert root.get("entityID") == AUDIENCE

    acs = root.find(f".//{{{MD_NS}}}AssertionConsumerService")
    assert acs is not None
    assert acs.get("Location") == ACS_URL

    key_descriptor = root.find(f".//{{{MD_NS}}}KeyDescriptor")
    assert key_descriptor is not None
    cert_node = root.find(f".//{{{DS_NS}}}X509Certificate")
    assert cert_node is not None
    assert str(cert_node.text or "").strip() == _pem_cert_to_b64(sp_cert_pem)

    assert root.find(f".//{{{DS_NS}}}Signature") is None


def test_build_saml_sp_metadata_can_be_signed_and_signature_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    _idp_key_pem, idp_cert_pem = _build_cert_pair(common_name="MimirQ Test IdP")
    _configure_provider(monkeypatch, idp_cert_pem=idp_cert_pem)

    sp_key_pem, sp_cert_pem = _build_cert_pair(common_name="MimirQ Test SP")
    monkeypatch.setattr(settings, "SAML_SP_CERT_PEM", sp_cert_pem.decode("utf-8"), raising=False)
    monkeypatch.setattr(settings, "SAML_SP_PRIVATE_KEY_PEM", sp_key_pem.decode("utf-8"), raising=False)
    monkeypatch.setattr(settings, "SAML_SP_METADATA_SIGNED", True, raising=False)

    xml = build_saml_sp_metadata_xml(provider_id="default")
    root = etree.fromstring(xml.encode("utf-8"))
    assert root.find(f".//{{{DS_NS}}}Signature") is not None

    # Signature verification should succeed with the configured SP certificate.
    XMLVerifier().verify(root, x509_cert=sp_cert_pem)

