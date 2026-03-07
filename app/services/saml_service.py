from __future__ import annotations

import json
from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from lxml import etree
from signxml import InvalidSignature, XMLVerifier

from app.api.schemas.auth import SamlExchangeResponse, TokenResponse, UserPublic
from app.core.config import settings
from app.core.jwt_utils import create_access_token
from app.services.saml_replay_service import ensure_saml_assertion_not_replayed
from app.services.user_service import UserService

_NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
}


@dataclass(frozen=True)
class SamlProvider:
    id: str
    issuer: str
    audience: str
    acs_url: str
    idp_cert_pem: str
    email_attribute: str = "email"
    groups_attribute: str = "groups"


def _xml_parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=False)


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_path(raw: str | None) -> str:
    value = str(raw or "").strip()
    if not value:
        return "/"
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or value.startswith("//"):
        return "/"
    if value.startswith("/"):
        return value
    return f"/{value}"


def _load_saml_providers() -> list[SamlProvider]:
    raw = str(getattr(settings, "SAML_PROVIDERS_JSON", "") or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail="SAML providers misconfigured") from exc

    if not isinstance(parsed, list):
        raise HTTPException(status_code=500, detail="SAML providers misconfigured")

    providers: list[SamlProvider] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("id") or "").strip()
        issuer = str(item.get("issuer") or "").strip()
        audience = str(item.get("audience") or "").strip()
        acs_url = str(item.get("acs_url") or "").strip()
        idp_cert_pem = str(item.get("idp_cert_pem") or "").strip()
        if not provider_id or not issuer or not audience or not acs_url or not idp_cert_pem:
            continue
        providers.append(
            SamlProvider(
                id=provider_id,
                issuer=issuer,
                audience=audience,
                acs_url=acs_url,
                idp_cert_pem=idp_cert_pem,
                email_attribute=str(item.get("email_attribute") or "email").strip() or "email",
                groups_attribute=str(item.get("groups_attribute") or "groups").strip() or "groups",
            )
        )
    return providers


def _resolve_provider(provider_id: str | None) -> SamlProvider:
    providers = _load_saml_providers()
    if not providers:
        raise HTTPException(status_code=400, detail="SAML not configured")

    requested = str(provider_id or "").strip()
    if requested:
        for provider in providers:
            if provider.id == requested:
                return provider
        raise HTTPException(status_code=400, detail="Unknown SAML provider")

    if len(providers) == 1:
        return providers[0]
    raise HTTPException(status_code=400, detail="SAML provider required")


def _decode_saml_response(saml_response: str) -> etree._Element:
    raw = str(saml_response or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Missing SAMLResponse")
    max_bytes = max(1, int(getattr(settings, "SAML_MAX_RESPONSE_BYTES", 500_000) or 500_000))
    try:
        xml_bytes = b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid SAMLResponse") from exc
    if not xml_bytes or len(xml_bytes) > max_bytes:
        raise HTTPException(status_code=400, detail="Invalid SAMLResponse")
    try:
        return etree.fromstring(xml_bytes, parser=_xml_parser())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid SAMLResponse") from exc


def _verify_signature(root: etree._Element, provider: SamlProvider) -> etree._Element:
    try:
        verified = XMLVerifier().verify(
            root,
            x509_cert=provider.idp_cert_pem,
            id_attribute="ID",
            parser=_xml_parser(),
        )
    except InvalidSignature as exc:
        raise HTTPException(status_code=401, detail="Invalid SAML signature") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid SAMLResponse") from exc

    signed_xml = verified.signed_xml
    if etree.QName(signed_xml.tag).localname == "Assertion":
        return signed_xml
    assertion = root.find("./saml:Assertion", namespaces=_NS)
    if assertion is None:
        raise HTTPException(status_code=400, detail="Missing SAML assertion")
    return assertion


def _get_text(node: etree._Element | None, xpath: str) -> str:
    if node is None:
        return ""
    found = node.find(xpath, namespaces=_NS)
    if found is None or found.text is None:
        return ""
    return str(found.text or "").strip()


def _collect_attribute_values(assertion: etree._Element, attr_name: str) -> list[str]:
    name = str(attr_name or "").strip()
    if not name:
        return []
    out: list[str] = []
    for attr in assertion.findall(".//saml:Attribute", namespaces=_NS):
        if str(attr.get("Name") or "").strip() != name:
            continue
        for value in attr.findall("./saml:AttributeValue", namespaces=_NS):
            item = str(value.text or "").strip()
            if item:
                out.append(item)
    return out


def _validate_conditions(root: etree._Element, assertion: etree._Element, provider: SamlProvider, acs_url: str | None) -> None:
    expected_acs = str(acs_url or "").strip() or provider.acs_url
    expected_audience = provider.audience
    expected_issuer = provider.issuer
    skew = max(0, int(getattr(settings, "SAML_ALLOWED_CLOCK_SKEW_SEC", 60) or 60))
    now = datetime.now(timezone.utc)

    response_issuer = _get_text(root, "./saml:Issuer")
    assertion_issuer = _get_text(assertion, "./saml:Issuer")
    if response_issuer != expected_issuer or assertion_issuer != expected_issuer:
        raise HTTPException(status_code=401, detail="Invalid SAML issuer")

    destination = str(root.get("Destination") or "").strip()
    if destination != expected_acs:
        raise HTTPException(status_code=401, detail="Invalid SAML destination")

    status_code = root.find("./samlp:Status/samlp:StatusCode", namespaces=_NS)
    if status_code is None or str(status_code.get("Value") or "").strip() != "urn:oasis:names:tc:SAML:2.0:status:Success":
        raise HTTPException(status_code=401, detail="SAML response not successful")

    conditions = assertion.find("./saml:Conditions", namespaces=_NS)
    if conditions is None:
        raise HTTPException(status_code=401, detail="Missing SAML conditions")

    not_before = _parse_iso_datetime(conditions.get("NotBefore"))
    if not_before is not None and now + timedelta(seconds=skew) < not_before:
        raise HTTPException(status_code=401, detail="SAML assertion not yet valid")

    not_on_or_after = _parse_iso_datetime(conditions.get("NotOnOrAfter"))
    if not_on_or_after is not None and now - timedelta(seconds=skew) >= not_on_or_after:
        raise HTTPException(status_code=401, detail="SAML assertion expired")

    audience_values = [
        str(audience.text or "").strip()
        for audience in assertion.findall(".//saml:AudienceRestriction/saml:Audience", namespaces=_NS)
        if str(audience.text or "").strip()
    ]
    if expected_audience not in audience_values:
        raise HTTPException(status_code=401, detail="Invalid SAML audience")

    subject_confirmation = assertion.find("./saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData", namespaces=_NS)
    if subject_confirmation is None:
        raise HTTPException(status_code=401, detail="Missing SAML subject confirmation")

    recipient = str(subject_confirmation.get("Recipient") or "").strip()
    if recipient != expected_acs:
        raise HTTPException(status_code=401, detail="Invalid SAML recipient")

    subject_not_on_or_after = _parse_iso_datetime(subject_confirmation.get("NotOnOrAfter"))
    if subject_not_on_or_after is not None and now - timedelta(seconds=skew) >= subject_not_on_or_after:
        raise HTTPException(status_code=401, detail="SAML assertion expired")


def _resolve_user_identity(db: Any, assertion: etree._Element, provider: SamlProvider):
    name_id = _get_text(assertion, "./saml:Subject/saml:NameID")
    emails = _collect_attribute_values(assertion, provider.email_attribute)
    groups = _collect_attribute_values(assertion, provider.groups_attribute)

    email = str(emails[0] if emails else "").strip().lower()
    name_id_normalized = str(name_id or "").strip()

    user = None
    if email:
        user = UserService.get_by_email(db, email)
    if user is None and name_id_normalized:
        if "@" in name_id_normalized:
            user = UserService.get_by_email(db, name_id_normalized.lower())
        if user is None:
            user = UserService.get_by_username(db, name_id_normalized)

    if user is None:
        raise HTTPException(status_code=403, detail="SAML account not provisioned")
    if not bool(getattr(user, "is_active", False)):
        raise HTTPException(status_code=403, detail="User disabled")

    return user, groups


def exchange_saml_response(
    *,
    db: Any,
    provider_id: str | None,
    saml_response: str,
    relay_state: str | None = None,
    acs_url: str | None = None,
) -> SamlExchangeResponse:
    provider = _resolve_provider(provider_id)
    root = _decode_saml_response(saml_response)
    assertion = _verify_signature(root, provider)
    _validate_conditions(root, assertion, provider, acs_url)

    replay_key = str(assertion.get("ID") or root.get("ID") or "").strip()
    ensure_saml_assertion_not_replayed(replay_key)

    user, groups = _resolve_user_identity(db, assertion, provider)
    UserService.mark_login(db, user)

    tenant_id = UserService.get_current_tenant_id(db, user_id=str(user.id))
    extra_claims: dict[str, Any] = {}
    normalized_groups = [group for group in groups if group]
    if normalized_groups:
        extra_claims[str(getattr(settings, "JWT_GROUPS_CLAIM", "groups") or "groups").strip() or "groups"] = normalized_groups

    token, expires_in = create_access_token(
        str(user.id),
        tenant_id=str(tenant_id) if tenant_id else None,
        extra_claims=extra_claims or None,
    )
    return SamlExchangeResponse(
        user=UserPublic.model_validate(user),
        token=TokenResponse(access_token=token, expires_in=expires_in),
        return_to=_normalize_path(relay_state),
    )


__all__ = ["exchange_saml_response"]
