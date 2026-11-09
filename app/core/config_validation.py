"""Startup validation and input normalization for application settings."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import warnings
from collections.abc import Mapping
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import UUID

from email_validator import EmailNotValidError, validate_email

from app.core.env import is_production_env
from app.core.model_execution import reject_retired_model_provider
from app.rag.retrieval.contract import (
    VALID_RETRIEVAL_CONTRACT_MODES,
    normalize_retrieval_contract_mode,
)
from app.rag.retrieval.sparse import (
    VALID_SPARSE_PROVIDERS,
    normalize_sparse_provider_name,
)

if TYPE_CHECKING:
    from app.core.config import Settings

_DEFAULT_RAG_EVAL_SUMMARY_PATH = "tests/rag/evaluation/fixtures/rag_eval_summary.sample.json"
_COMMA_OR_WHITESPACE_RE = r"[,\\s]+"
_LEGACY_DEV_SECRET_KEY = "".join(("your-secret-key", "-change-in-production"))
_LOCAL_MINIO_DEFAULT_CREDENTIAL = "".join(("minio", "admin"))
_ALL_INTERFACES_HOST = str(ipaddress.IPv4Address(0))
_JWT_LOCAL_HOSTS = frozenset({"localhost", "localhost.localdomain", "127.0.0.1", "::1"})
_OBJECT_STORAGE_PROVIDER_ALIASES = {
    "": "minio",
    "minio": "minio",
    "s3": "s3",
    "aws_s3": "s3",
    "s3_compatible": "s3_compatible",
    "s3compat": "s3_compatible",
    "oss": "oss",
    "aliyun_oss": "oss",
    "cos": "cos",
    "tencent_cos": "cos",
}

DEFAULT_RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS = "high,medium"


def normalize_object_storage_provider_name(raw: object) -> str:
    requested = str(raw or "minio").strip().lower()
    try:
        return _OBJECT_STORAGE_PROVIDER_ALIASES[requested]
    except KeyError as exc:
        raise ValueError(f"unsupported object storage provider: {requested}") from exc


def parse_object_storage_region_profiles(raw: object) -> dict[str, dict[str, object]]:
    if isinstance(raw, Mapping):
        source = dict(raw)
    else:
        text = str(raw or "").strip()
        if not text:
            return {}
        try:
            source = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ValueError("OBJECT_STORAGE_REGION_PROFILES must be a valid JSON object") from exc
        if not isinstance(source, dict):
            raise ValueError("OBJECT_STORAGE_REGION_PROFILES must be a valid JSON object")

    profiles: dict[str, dict[str, object]] = {}
    for raw_region, raw_profile in source.items():
        region = str(raw_region or "").strip().lower()
        if not region or not isinstance(raw_profile, Mapping):
            raise ValueError("OBJECT_STORAGE_REGION_PROFILES entries must map a non-empty region to an object")
        profiles[region] = dict(raw_profile)
    return profiles


def _is_local_jwt_http_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if not normalized:
        return False
    if normalized in _JWT_LOCAL_HOSTS or normalized.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return bool(ip.is_loopback)


def validate_jwt_remote_url(raw_url: str, *, field_name: str) -> None:
    url = str(raw_url or "").strip()
    if not url:
        return

    parsed = urlparse(url)
    scheme = str(parsed.scheme or "").strip().lower()
    host = str(parsed.hostname or "").strip().lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError(f"{field_name} must be a http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name} must not include userinfo")
    if scheme == "https":
        return
    if not is_production_env() and _is_local_jwt_http_host(host):
        return
    raise ValueError(f"{field_name} must use https")


def _set_if_changed(settings: Settings, field_name: str, value: object) -> None:
    if getattr(settings, field_name) != value:
        setattr(settings, field_name, value)


def _raise_if(condition: object, message: str) -> None:
    if condition:
        raise ValueError(message)


def _require_int_min(value: int, minimum: int, message: str) -> None:
    _raise_if(value < minimum, message)


def _require_int_between(value: int, minimum: int, maximum: int, message: str) -> None:
    _raise_if(value < minimum or value > maximum, message)


def _require_float_min(value: float, minimum: float, message: str) -> None:
    _raise_if(value < minimum, message)


def _require_float_positive(value: float, message: str) -> None:
    _raise_if(value <= 0.0, message)


def _require_float_between(value: float, minimum: float, maximum: float, message: str) -> None:
    _raise_if(value < minimum or value > maximum, message)


def _require_nonempty(value: str | list[str], message: str) -> None:
    _raise_if(not value, message)


def _require_no_whitespace(value: str, message: str) -> None:
    _raise_if(any(ch.isspace() for ch in value), message)


def _normalize_lower_choice(value: str, default: str) -> str:
    return (value or default).strip().lower()


def _normalize_choice_setting(
    settings: Settings, field_name: str, default: str, valid_values: set[str], message: str
) -> str:
    normalized = _normalize_lower_choice(getattr(settings, field_name, default), default)
    _raise_if(normalized not in valid_values, message)
    _set_if_changed(settings, field_name, normalized)
    return normalized


def _validate_sha256_digest(value: str, message: str) -> None:
    if value.lower().startswith("sha256:"):
        digest = value.split(":", 1)[1].strip()
        _raise_if(not re.fullmatch(r"[0-9a-fA-F]{64}", digest or ""), message)


def _split_token_values(raw_value: str) -> list[str]:
    return [part.strip() for part in re.split(_COMMA_OR_WHITESPACE_RE, raw_value) if part.strip()]


def _validate_uuid_value(value: str, message: str) -> None:
    try:
        UUID(value)
    except ValueError as exc:
        raise ValueError(message) from exc


def _validate_tokenized_sha256_digests(token_raw: str, field_name: str, required_message: str) -> list[str]:
    tokens = _split_token_values(token_raw)
    _require_nonempty(tokens, required_message)
    for token in tokens:
        _validate_sha256_digest(token, f"{field_name} sha256 digest must be 64 hex chars")
    return tokens


def _validate_initial_registration_token(settings: Settings) -> None:
    initial_registration_token = (settings.INITIAL_REGISTRATION_TOKEN or "").strip()
    _validate_sha256_digest(
        initial_registration_token,
        "INITIAL_REGISTRATION_TOKEN sha256 digest must be 64 hex chars",
    )


def _validate_jwt_tenant_source(settings: Settings, auth_mode: str, is_production: bool) -> None:
    if auth_mode != "jwt" or not is_production:
        return
    tenant_claim = (settings.JWT_TENANT_CLAIM or "").strip()
    if not tenant_claim and not settings.TENANT_HEADER_TRUSTED:
        raise ValueError(
            "AUTH_MODE=jwt in production requires a trusted tenant source: "
            "set JWT_TENANT_CLAIM (recommended) or set TENANT_HEADER_TRUSTED=true "
            "to explicitly trust the client/gateway-supplied tenant header"
        )


def _validate_jwt_member_auto_provision(settings: Settings, auth_mode: str) -> None:
    if not settings.JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED:
        return
    _raise_if(auth_mode != "jwt", "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED requires AUTH_MODE=jwt")
    claim = (settings.JWT_TENANT_CLAIM or "").strip()
    _require_nonempty(
        claim,
        "JWT_TENANT_CLAIM required when JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED=true",
    )


def _validate_jwt_remote_settings(settings: Settings) -> None:
    issuer = (settings.JWT_ISSUER or "").strip()
    if issuer:
        validate_jwt_remote_url(issuer, field_name="JWT_ISSUER")

    jwks_urls_raw = (settings.JWT_JWKS_URLS or "").strip()
    if jwks_urls_raw:
        for raw_url in [item.strip() for item in jwks_urls_raw.split(",") if item.strip()]:
            validate_jwt_remote_url(raw_url, field_name="JWT_JWKS_URLS")


def _validate_initial_admin_identity(email: str, username: str, password: str, password_file: str) -> bool:
    if not any((email, username, password, password_file)):
        return False
    if not email or not username:
        raise ValueError(
            "INITIAL_ADMIN bootstrap requires "
            "INITIAL_ADMIN_EMAIL, INITIAL_ADMIN_USERNAME, and exactly one password source"
        )
    return True


def _validate_initial_admin_password_sources(password: str, password_file: str) -> None:
    password_sources = int(bool(password)) + int(bool(password_file))
    if password_sources == 1:
        return
    if password and password_file:
        raise ValueError("INITIAL_ADMIN_PASSWORD and INITIAL_ADMIN_PASSWORD_FILE are mutually exclusive")
    raise ValueError(
        "INITIAL_ADMIN bootstrap requires INITIAL_ADMIN_EMAIL, INITIAL_ADMIN_USERNAME, and exactly one password source"
    )


def _validate_initial_admin_email(email: str) -> str:
    try:
        normalized_email = validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError("INITIAL_ADMIN_EMAIL must be a valid email address") from exc
    _raise_if(len(normalized_email) > 255, "INITIAL_ADMIN_EMAIL must be a valid email address")
    return normalized_email


def _validate_initial_admin_password(settings: Settings, password: str) -> None:
    if not password:
        return
    min_len = settings.PASSWORD_MIN_LENGTH or 8
    _raise_if(len(password) < min_len, f"INITIAL_ADMIN_PASSWORD must be at least {min_len} characters")
    _raise_if(
        len(password.encode("utf-8")) > 72,
        "INITIAL_ADMIN_PASSWORD cannot be longer than 72 bytes for bcrypt",
    )


def _validate_scim_allowlist(settings: Settings) -> None:
    allow_raw = (settings.SCIM_IP_ALLOWLIST_CIDRS or "").strip()
    if not allow_raw:
        return
    cidrs = _split_token_values(allow_raw)
    _require_nonempty(cidrs, "SCIM_IP_ALLOWLIST_CIDRS must be a comma/space-separated list of CIDRs")
    for cidr in cidrs:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid SCIM_IP_ALLOWLIST_CIDRS entry: {cidr}") from exc


def _validate_object_storage_profile(label: str, profile: Mapping[str, object]) -> None:
    enabled = bool(profile.get("enabled", False))
    documents_enabled = bool(profile.get("documents_enabled", False))
    _raise_if(documents_enabled and not enabled, f"{label}.documents_enabled requires {label}.enabled=true")
    if not enabled:
        return
    for field_name in ("endpoint", "access_key", "secret_key", "bucket_name"):
        _require_nonempty(
            str(profile.get(field_name) or "").strip(),
            f"{label}.{field_name} is required when {label}.enabled=true",
        )


def _validate_object_storage_region_profile(
    region: str,
    raw_profile: Mapping[str, object],
    base_object_storage: Mapping[str, object],
    object_storage_provider: str,
) -> None:
    for boolean_field in ("enabled", "use_ssl", "documents_enabled"):
        if boolean_field in raw_profile and not isinstance(raw_profile[boolean_field], bool):
            raise ValueError(f"OBJECT_STORAGE_REGION_PROFILES[{region!r}].{boolean_field} must be a JSON boolean")
    merged_profile = dict(base_object_storage)
    merged_profile.update(
        {key: value for key, value in raw_profile.items() if key in merged_profile and value not in (None, "")}
    )
    merged_profile["provider"] = normalize_object_storage_provider_name(
        raw_profile.get("provider") or object_storage_provider
    )
    _validate_object_storage_profile(f"OBJECT_STORAGE_REGION_PROFILES[{region!r}]", merged_profile)


def validate_uvicorn_workers_and_distributed_limits(settings: Settings) -> None:
    is_production = is_production_env()

    workers_raw = str(os.getenv("UVICORN_WORKERS", "1") or "1").strip()
    try:
        uvicorn_workers = int(workers_raw)
    except ValueError as exc:
        raise ValueError("UVICORN_WORKERS must be a positive integer") from exc
    if uvicorn_workers < 1:
        raise ValueError("UVICORN_WORKERS must be a positive integer")

    if is_production and uvicorn_workers > 1:
        distributed_limiter = settings.RATE_LIMIT_REDIS_ENABLED and bool((settings.REDIS_URL or "").strip())
        if settings.RATE_LIMIT_ENABLED and not distributed_limiter:
            raise ValueError("RATE_LIMIT_REDIS_ENABLED=true with REDIS_URL is required when UVICORN_WORKERS > 1")
        if settings.TENANT_QPS_QUOTA_ENABLED and not distributed_limiter:
            raise ValueError(
                "TENANT_QPS_QUOTA_ENABLED with UVICORN_WORKERS > 1 requires RATE_LIMIT_REDIS_ENABLED=true and REDIS_URL"
            )


def validate_saml_replay(settings: Settings) -> None:
    is_production = is_production_env()
    if is_production and (settings.SAML_PROVIDERS_JSON or "").strip():
        if not settings.SAML_REPLAY_REDIS_ENABLED:
            raise ValueError("SAML_REPLAY_REDIS_ENABLED=true is required for SAML in production")
        if not (settings.REDIS_URL or "").strip():
            raise ValueError("REDIS_URL is required for SAML replay protection in production")


def validate_trusted_hosts(settings: Settings) -> None:
    is_production = is_production_env()
    # Security: Host header hardening (production-only by default).
    if is_production and settings.TRUSTED_HOSTS_ENABLED:
        raw_allowed = (settings.ALLOWED_HOSTS or "").strip()
        allowed = [p.strip() for p in raw_allowed.split(",") if p.strip()]
        if not allowed:
            raise ValueError("ALLOWED_HOSTS required in production (comma-separated)")
        if "*" in allowed:
            raise ValueError("ALLOWED_HOSTS must not include '*' in production")


def validate_production_api_surface(settings: Settings) -> None:
    is_production = is_production_env()
    # Security: Reduce public API surface in production by default.
    if is_production:
        fields_set = settings.model_fields_set or set()
        for field_name in ("DB_CREATE_ALL_ON_STARTUP", "DB_RUNTIME_MIGRATIONS_ENABLED"):
            if field_name not in fields_set:
                setattr(settings, field_name, False)
            elif bool(getattr(settings, field_name, False)):
                raise ValueError(f"{field_name} must be false in production; run `make db-upgrade` before startup")
        if "API_DOCS_ENABLED" not in fields_set:
            settings.API_DOCS_ENABLED = False
        if "API_OPENAPI_ENABLED" not in fields_set:
            settings.API_OPENAPI_ENABLED = False
        if "SETTINGS_ENV_WRITE_ENABLED" not in fields_set:
            settings.SETTINGS_ENV_WRITE_ENABLED = False
        # Docs require OpenAPI; if a deploy explicitly enables docs, keep the schema endpoint available.
        if settings.API_DOCS_ENABLED and not settings.API_OPENAPI_ENABLED:
            settings.API_OPENAPI_ENABLED = True


def validate_cors(settings: Settings) -> None:
    is_production = is_production_env()
    # Security: CORS hardening (production guardrails).
    if is_production:
        # Production default: do not allow credentialed cross-origin calls unless explicitly enabled.
        # This avoids accidentally running a cookie-bearing API with permissive CORS defaults.
        if "CORS_ALLOW_CREDENTIALS" not in (settings.model_fields_set or set()):
            settings.CORS_ALLOW_CREDENTIALS = False

        cors_raw = settings.CORS_ORIGINS or ""
        cors_origins = [p.strip() for p in cors_raw.split(",") if p.strip()]
        if not cors_origins:
            raise ValueError("CORS_ORIGINS required in production")
        if "*" in cors_origins:
            # Note: FastAPI/Starlette forbids credentials with wildcard origins; keep signal high in prod.
            raise ValueError("CORS_ORIGINS must not include '*' in production")

        for origin in cors_origins:
            if origin.lower().strip() == "null":
                raise ValueError("CORS_ORIGINS must not include 'null' in production")
            parsed = urlparse(origin)
            scheme = (parsed.scheme or "").lower().strip()
            host = (parsed.hostname or "").lower().strip()
            if scheme not in {"http", "https"} or not host:
                raise ValueError("CORS_ORIGINS must be a comma-separated list of http(s) origins in production")
            if host in {"localhost", "127.0.0.1", _ALL_INTERFACES_HOST} or host.endswith(".localhost"):
                raise ValueError("CORS_ORIGINS must not include localhost origins in production")


def validate_auth_mode_and_jwt_claims(settings: Settings) -> None:
    is_production = is_production_env()
    # Security: Auth mode guard
    auth_mode = _normalize_lower_choice(settings.AUTH_MODE, "jwt")
    _raise_if(auth_mode not in ("jwt", "header"), f"Unsupported AUTH_MODE: {auth_mode}")
    _raise_if(auth_mode == "header" and is_production, "AUTH_MODE=header is not allowed in production")
    if settings.LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED:
        _raise_if(is_production, "LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED is not allowed in production")
        _raise_if(auth_mode != "header", "LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED requires AUTH_MODE=header")

    _validate_initial_registration_token(settings)
    _validate_jwt_tenant_source(settings, auth_mode, is_production)
    _validate_jwt_member_auto_provision(settings, auth_mode)
    _validate_jwt_remote_settings(settings)


def validate_initial_admin_bootstrap(settings: Settings) -> None:
    email = (settings.INITIAL_ADMIN_EMAIL or "").strip()
    username = (settings.INITIAL_ADMIN_USERNAME or "").strip()
    password = settings.INITIAL_ADMIN_PASSWORD or ""
    password_file = (settings.INITIAL_ADMIN_PASSWORD_FILE or "").strip()

    if not _validate_initial_admin_identity(email, username, password, password_file):
        return
    _validate_initial_admin_password_sources(password, password_file)
    normalized_email = _validate_initial_admin_email(email)
    _require_int_between(len(username), 3, 64, "INITIAL_ADMIN_USERNAME must be between 3 and 64 characters")
    _validate_initial_admin_password(settings, password)
    settings.INITIAL_ADMIN_EMAIL = normalized_email
    settings.INITIAL_ADMIN_USERNAME = username
    settings.INITIAL_ADMIN_PASSWORD_FILE = password_file


def validate_scim(settings: Settings) -> None:
    # Security: SCIM provisioning auth guard (enterprise).
    if not settings.SCIM_ENABLED:
        return
    token_raw = (settings.SCIM_BEARER_TOKEN or "").strip()
    _validate_tokenized_sha256_digests(
        token_raw,
        "SCIM_BEARER_TOKEN",
        "SCIM_BEARER_TOKEN required when SCIM_ENABLED=true",
    )
    tenant_raw = (settings.SCIM_TENANT_ID or "").strip()
    _require_nonempty(tenant_raw, "SCIM_TENANT_ID required when SCIM_ENABLED=true")
    _validate_uuid_value(tenant_raw, "SCIM_TENANT_ID must be a UUID")
    _validate_scim_allowlist(settings)


def validate_dify_resolution_mode(settings: Settings) -> None:
    is_production = is_production_env()
    dify_resolution_mode = (settings.DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE or "mapped_only").strip().lower()
    valid_dify_resolution_modes = {"mapped_only", "allow_dataset_uuid"}
    if dify_resolution_mode not in valid_dify_resolution_modes:
        raise ValueError(
            "DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE must be one of: " + ", ".join(sorted(valid_dify_resolution_modes))
        )
    if is_production and dify_resolution_mode == "allow_dataset_uuid":
        raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE=allow_dataset_uuid is not allowed in production")
    if settings.DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE != dify_resolution_mode:
        settings.DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE = dify_resolution_mode


def validate_rag_runtime_warmup(settings: Settings) -> None:
    if settings.RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY and not settings.RAG_RUNTIME_WARMUP_ENABLED:
        raise ValueError("RAG_RUNTIME_WARMUP_ENABLED must be true when RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY=true")


def validate_dify_external_knowledge(settings: Settings) -> None:
    is_production = is_production_env()
    # Security: Dify external knowledge adapter auth guard.
    if not settings.DIFY_EXTERNAL_KNOWLEDGE_ENABLED:
        return
    token_raw = (settings.DIFY_EXTERNAL_KNOWLEDGE_API_KEYS or "").strip()
    _validate_tokenized_sha256_digests(
        token_raw,
        "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS",
        "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS required when DIFY_EXTERNAL_KNOWLEDGE_ENABLED=true",
    )

    tenant_raw = (settings.DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID or "").strip()
    _raise_if(
        is_production and not tenant_raw,
        "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID is required when DIFY_EXTERNAL_KNOWLEDGE_ENABLED=true in production",
    )
    if tenant_raw:
        _validate_uuid_value(tenant_raw, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID must be a UUID")

    top_k_max = settings.DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX or 0
    _require_int_between(top_k_max, 1, 200, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX must be between 1 and 200")
    internal_top_k_min = settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN or 0
    _require_int_between(
        internal_top_k_min,
        1,
        200,
        "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN must be between 1 and 200",
    )
    internal_top_k_multiplier = settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER or 0
    _require_int_between(
        internal_top_k_multiplier,
        1,
        20,
        "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER must be between 1 and 20",
    )
    internal_top_k_max = settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX or 0
    _require_int_between(
        internal_top_k_max,
        1,
        200,
        "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX must be between 1 and 200",
    )
    _raise_if(
        internal_top_k_max < top_k_max,
        "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX must be >= DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX",
    )
    _raise_if(
        internal_top_k_max < internal_top_k_min,
        "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX must be >= DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN",
    )
    warmup_top_k = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K or 0
    _require_int_between(
        warmup_top_k,
        1,
        200,
        "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K must be between 1 and 200",
    )
    warmup_max_ids = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS or 0
    _require_int_between(
        warmup_max_ids,
        0,
        500,
        "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS must be between 0 and 500",
    )
    warmup_timeout_sec = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC or 0.0
    _require_float_between(
        warmup_timeout_sec,
        1.0,
        600.0,
        "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC must be between 1 and 600",
    )
    warmup_start_delay_sec = settings.DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC or 0.0
    _require_float_between(
        warmup_start_delay_sec,
        0.0,
        60.0,
        "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC must be between 0 and 60",
    )
    dify_overfetch_multiplier = settings.DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER or 0
    _require_int_between(
        dify_overfetch_multiplier,
        1,
        20,
        "DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER must be between 1 and 20",
    )
    dify_overfetch_max_k = settings.DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K or 0
    _require_int_between(
        dify_overfetch_max_k,
        0,
        500,
        "DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K must be between 0 and 500",
    )
    primary_min_records = settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS or 0
    _require_int_between(
        primary_min_records,
        1,
        top_k_max,
        "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS must be between 1 and TOP_K_MAX",
    )
    primary_min_top_score = settings.DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE or 0.0
    _require_float_between(
        primary_min_top_score,
        0.0,
        2.0,
        "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE must be between 0 and 2",
    )
    response_cache_ttl_sec = settings.DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC or 0
    _require_int_min(response_cache_ttl_sec, 0, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC must be >= 0")
    response_cache_max_entries = settings.DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES or 0
    _require_int_min(
        response_cache_max_entries,
        0,
        "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES must be >= 0",
    )
    compact_min_top_score = settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE or 0.0
    _require_float_between(
        compact_min_top_score,
        0.0,
        2.0,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE must be between 0 and 2",
    )
    compact_relative_floor = settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR or 0.0
    _require_float_between(
        compact_relative_floor,
        0.0,
        1.0,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR must be between 0 and 1",
    )
    compact_min_records = settings.DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS or 0
    _require_int_between(
        compact_min_records,
        1,
        top_k_max,
        "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS must be between 1 and TOP_K_MAX",
    )
    fast_candidate_top_k_max = settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX or 0
    _require_int_between(
        fast_candidate_top_k_max,
        1,
        top_k_max,
        "DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX must be between 1 and TOP_K_MAX",
    )
    fast_response_top_k_max = settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX or 0
    _require_int_between(
        fast_response_top_k_max,
        1,
        top_k_max,
        "DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX must be between 1 and TOP_K_MAX",
    )
    fast_content_max_chars = settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS or 0
    _require_int_between(
        fast_content_max_chars,
        200,
        10000,
        "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS must be between 200 and 10000",
    )
    fast_total_content_max_chars = settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS or 0
    _require_int_between(
        fast_total_content_max_chars,
        200,
        50000,
        "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS must be between 200 and 50000",
    )
    fast_metadata_preflight_statement_timeout_ms = (
        settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS or 0
    )
    _require_int_between(
        fast_metadata_preflight_statement_timeout_ms,
        0,
        30000,
        "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS must be between 0 and 30000",
    )
    fast_metadata_preflight_max_elapsed_ms = (
        settings.DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS or 0
    )
    _require_int_between(
        fast_metadata_preflight_max_elapsed_ms,
        0,
        30000,
        "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS must be between 0 and 30000",
    )
    metadata_anchor_total_budget_ms = settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS or 0
    _require_int_between(
        metadata_anchor_total_budget_ms,
        0,
        30000,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS must be between 0 and 30000",
    )
    kg_injection_max_chunks = settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS or 0
    _require_int_between(
        kg_injection_max_chunks,
        0,
        50,
        "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS must be between 0 and 50",
    )
    kg_boost_weight = settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT or 0.0
    _require_float_between(
        kg_boost_weight,
        0.0,
        1.0,
        "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT must be between 0 and 1",
    )
    kg_boost_max_promoted = settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED or 0
    _require_int_between(
        kg_boost_max_promoted,
        0,
        20,
        "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED must be between 0 and 20",
    )


def validate_secret_key_and_jwt_key_source(settings: Settings) -> None:
    auth_mode = (settings.AUTH_MODE or "jwt").lower()
    issuer = (settings.JWT_ISSUER or "").strip()
    jwks_urls_raw = (settings.JWT_JWKS_URLS or "").strip()
    # Security: Validate SECRET_KEY (required for JWT verification)
    if auth_mode == "jwt":
        if not settings.SECRET_KEY or settings.SECRET_KEY == _LEGACY_DEV_SECRET_KEY or len(settings.SECRET_KEY) < 32:
            raise ValueError("SECRET_KEY required for JWT auth (min 32 chars)")

        algorithm = (settings.ALGORITHM or "HS256").strip() or "HS256"
        if algorithm.upper().startswith("HS"):
            # HS* uses SECRET_KEY.
            pass
        else:
            # RS*/ES* require a key source (JWKS) for verification.
            if not jwks_urls_raw:
                discovery_enabled = settings.JWT_JWKS_DISCOVERY_ENABLED
                if not discovery_enabled:
                    raise ValueError(f"JWT_JWKS_URLS required for ALGORITHM={algorithm}")
                if not issuer:
                    raise ValueError("JWT_ISSUER required when JWT_JWKS_DISCOVERY_ENABLED=true")
    else:
        # Best-effort warning for other uses (sessions, future JWT issuance, etc.)
        if not settings.SECRET_KEY or settings.SECRET_KEY == _LEGACY_DEV_SECRET_KEY:
            warnings.warn(
                "SECRET_KEY is not configured. Set a strong value before enabling JWT auth "
                "or stored secret encryption.",
                UserWarning,
                stacklevel=2,
            )


def validate_minio(settings: Settings) -> None:
    is_production = is_production_env()
    # Security: Warn about default MinIO credentials
    if settings.MINIO_ENABLED:
        access_key = (settings.MINIO_ACCESS_KEY or "").strip()
        secret_key = (settings.MINIO_SECRET_KEY or "").strip()
        missing_access_key = not access_key
        missing_secret_key = not secret_key

        used_default_minio_credentials = False
        if missing_access_key or missing_secret_key:
            if is_production:
                raise ValueError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY are required when MINIO_ENABLED=true")
            if missing_access_key and missing_secret_key:
                settings.MINIO_ACCESS_KEY = _LOCAL_MINIO_DEFAULT_CREDENTIAL
                settings.MINIO_SECRET_KEY = _LOCAL_MINIO_DEFAULT_CREDENTIAL
                used_default_minio_credentials = True
                warnings.warn(
                    "MINIO_ACCESS_KEY/MINIO_SECRET_KEY are empty; using local/dev MinIO defaults.",
                    UserWarning,
                    stacklevel=2,
                )
            else:
                raise ValueError("MINIO_ACCESS_KEY and MINIO_SECRET_KEY must both be set when MINIO_ENABLED=true")
        else:
            if settings.MINIO_ACCESS_KEY != access_key:
                settings.MINIO_ACCESS_KEY = access_key
            if settings.MINIO_SECRET_KEY != secret_key:
                settings.MINIO_SECRET_KEY = secret_key

        if (
            settings.MINIO_ACCESS_KEY == _LOCAL_MINIO_DEFAULT_CREDENTIAL
            or settings.MINIO_SECRET_KEY == _LOCAL_MINIO_DEFAULT_CREDENTIAL
        ):
            if is_production:
                raise ValueError("Default MinIO credentials are not allowed in production when MINIO_ENABLED=true")
            if not used_default_minio_credentials:
                warnings.warn(
                    "Using default MinIO credentials. Change in production!",
                    UserWarning,
                    stacklevel=2,
                )


def validate_object_storage(settings: Settings) -> None:
    object_storage_provider = normalize_object_storage_provider_name(settings.OBJECT_STORAGE_PROVIDER)
    settings.OBJECT_STORAGE_PROVIDER = object_storage_provider
    object_storage_profiles = parse_object_storage_region_profiles(settings.OBJECT_STORAGE_REGION_PROFILES)
    data_region = (settings.DATA_REGION or "").strip().lower()
    settings.DATA_REGION = data_region

    base_object_storage: dict[str, object] = {
        "provider": object_storage_provider,
        "enabled": settings.OBJECT_STORAGE_ENABLED,
        "endpoint": (settings.OBJECT_STORAGE_ENDPOINT or "").strip(),
        "access_key": (settings.OBJECT_STORAGE_ACCESS_KEY or "").strip(),
        "secret_key": (settings.OBJECT_STORAGE_SECRET_KEY or "").strip(),
        "bucket_name": (settings.OBJECT_STORAGE_BUCKET_NAME or "").strip(),
        "documents_enabled": settings.OBJECT_STORAGE_DOCUMENTS_ENABLED,
    }

    _validate_object_storage_profile("OBJECT_STORAGE", base_object_storage)
    if (
        data_region
        and bool(base_object_storage["enabled"])
        and bool(base_object_storage["documents_enabled"])
        and data_region not in object_storage_profiles
    ):
        raise ValueError(
            "DATA_REGION must have a matching OBJECT_STORAGE_REGION_PROFILES entry "
            "when generic document object storage is enabled"
        )
    for region, raw_profile in object_storage_profiles.items():
        _validate_object_storage_region_profile(region, raw_profile, base_object_storage, object_storage_provider)


def validate_chunk_llm_and_retrieval(settings: Settings) -> None:
    is_production = is_production_env()
    # Validate chunk settings
    _raise_if(
        settings.CHUNK_OVERLAP >= settings.CHUNK_SIZE,
        f"CHUNK_OVERLAP ({settings.CHUNK_OVERLAP}) must be less than CHUNK_SIZE ({settings.CHUNK_SIZE})",
    )

    # Validate LLM temperature
    _raise_if(
        not 0 <= settings.LLM_TEMPERATURE <= 2,
        f"LLM_TEMPERATURE ({settings.LLM_TEMPERATURE}) must be between 0 and 2",
    )

    # Validate retrieval settings
    _raise_if(
        settings.SIMILARITY_THRESHOLD < 0 or settings.SIMILARITY_THRESHOLD > 1,
        f"SIMILARITY_THRESHOLD ({settings.SIMILARITY_THRESHOLD}) must be between 0 and 1",
    )

    _require_int_min(settings.RETRIEVAL_TOP_K or 0, 1, f"RETRIEVAL_TOP_K ({settings.RETRIEVAL_TOP_K}) must be >= 1")
    _raise_if(
        settings.RETRIEVAL_MMR_LAMBDA < 0 or settings.RETRIEVAL_MMR_LAMBDA > 1,
        f"RETRIEVAL_MMR_LAMBDA ({settings.RETRIEVAL_MMR_LAMBDA}) must be between 0 and 1",
    )
    _raise_if(
        settings.RETRIEVAL_DEFAULT_ALPHA < 0 or settings.RETRIEVAL_DEFAULT_ALPHA > 1,
        f"RETRIEVAL_DEFAULT_ALPHA ({settings.RETRIEVAL_DEFAULT_ALPHA}) must be between 0 and 1",
    )
    _require_int_min(settings.RETRIEVAL_RRF_K or 0, 1, f"RETRIEVAL_RRF_K ({settings.RETRIEVAL_RRF_K}) must be >= 1")
    dedup_thr = settings.RETRIEVAL_DEDUP_JACCARD_THRESHOLD or 0.0
    _require_float_between(
        dedup_thr,
        0.0,
        1.0,
        f"RETRIEVAL_DEDUP_JACCARD_THRESHOLD ({dedup_thr}) must be between 0 and 1",
    )
    _require_int_min(settings.RETRIEVAL_DEDUP_MAX_COMPARE or 0, 0, "RETRIEVAL_DEDUP_MAX_COMPARE must be >= 0")
    _require_int_min(
        settings.RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD or 0, 0, "RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD must be >= 0"
    )
    _require_int_min(settings.RETRIEVAL_NEAR_DEDUP_MAX_COMPARE or 0, 0, "RETRIEVAL_NEAR_DEDUP_MAX_COMPARE must be >= 0")
    _require_int_min(settings.RETRIEVAL_MAX_CHUNKS_PER_DOC or 0, 0, "RETRIEVAL_MAX_CHUNKS_PER_DOC must be >= 0")
    _require_int_min(
        settings.RETRIEVAL_MAX_CHUNKS_PER_RECORD_IDENTITY or 0,
        0,
        "RETRIEVAL_MAX_CHUNKS_PER_RECORD_IDENTITY must be >= 0",
    )
    compact_min_top_score = settings.RETRIEVAL_COMPACT_MIN_TOP_SCORE or 0.8
    _require_float_between(
        compact_min_top_score,
        0.0,
        2.0,
        "RETRIEVAL_COMPACT_MIN_TOP_SCORE must be between 0 and 2",
    )
    compact_relative_floor = settings.RETRIEVAL_COMPACT_RELATIVE_SCORE_FLOOR or 0.65
    _require_float_between(
        compact_relative_floor,
        0.0,
        1.0,
        "RETRIEVAL_COMPACT_RELATIVE_SCORE_FLOOR must be between 0 and 1",
    )
    _require_int_min(settings.RETRIEVAL_COMPACT_MIN_RECORDS or 1, 1, "RETRIEVAL_COMPACT_MIN_RECORDS must be >= 1")
    _require_int_min(settings.RETRIEVAL_MAX_CHUNKS_PER_PAGE or 0, 0, "RETRIEVAL_MAX_CHUNKS_PER_PAGE must be >= 0")
    _require_int_min(settings.RETRIEVAL_MIN_DISTINCT_DOCS or 0, 0, "RETRIEVAL_MIN_DISTINCT_DOCS must be >= 0")
    field_title_boost = settings.RETRIEVAL_FIELD_AWARE_TITLE_BOOST or 0.0
    field_heading_boost = settings.RETRIEVAL_FIELD_AWARE_HEADING_BOOST or 0.0
    field_max_boost = settings.RETRIEVAL_FIELD_AWARE_MAX_BOOST or 0.0
    _require_float_min(field_title_boost, 0.0, "RETRIEVAL_FIELD_AWARE_TITLE_BOOST must be >= 0")
    _require_float_min(field_heading_boost, 0.0, "RETRIEVAL_FIELD_AWARE_HEADING_BOOST must be >= 0")
    _require_float_min(field_max_boost, 0.0, "RETRIEVAL_FIELD_AWARE_MAX_BOOST must be >= 0")
    _raise_if(
        field_title_boost > field_max_boost,
        "RETRIEVAL_FIELD_AWARE_TITLE_BOOST must be <= RETRIEVAL_FIELD_AWARE_MAX_BOOST",
    )
    _raise_if(
        field_heading_boost > field_max_boost,
        "RETRIEVAL_FIELD_AWARE_HEADING_BOOST must be <= RETRIEVAL_FIELD_AWARE_MAX_BOOST",
    )
    chunk_type_match_boost = settings.RETRIEVAL_CHUNK_TYPE_MATCH_BOOST or 0.0
    _require_float_min(chunk_type_match_boost, 0.0, "RETRIEVAL_CHUNK_TYPE_MATCH_BOOST must be >= 0")
    _require_int_min(
        settings.RETRIEVAL_QUERY_PARALLELISM or 0,
        1,
        f"RETRIEVAL_QUERY_PARALLELISM ({settings.RETRIEVAL_QUERY_PARALLELISM}) must be >= 1",
    )
    _require_int_min(settings.RETRIEVAL_OVERFETCH_MULTIPLIER or 1, 1, "RETRIEVAL_OVERFETCH_MULTIPLIER must be >= 1")
    hierarchy_family_aggregation = (settings.HIERARCHY_RECALL_FAMILY_AGGREGATION or "combined").strip().lower()
    valid_hierarchy_family_aggregation = {"frequency", "score", "combined"}
    _raise_if(
        hierarchy_family_aggregation not in valid_hierarchy_family_aggregation,
        "HIERARCHY_RECALL_FAMILY_AGGREGATION must be one of: " + ", ".join(sorted(valid_hierarchy_family_aggregation)),
    )
    _set_if_changed(settings, "HIERARCHY_RECALL_FAMILY_AGGREGATION", hierarchy_family_aggregation)
    _require_int_between(
        settings.HIERARCHY_RECALL_PARENT_DEPTH or 0, 0, 8, "HIERARCHY_RECALL_PARENT_DEPTH must be between 0 and 8"
    )
    _require_int_between(
        settings.HIERARCHY_RECALL_SIBLING_WINDOW or 0, 0, 16, "HIERARCHY_RECALL_SIBLING_WINDOW must be between 0 and 16"
    )
    _require_int_between(
        settings.HIERARCHY_RECALL_OVERFETCH_FACTOR or 4,
        1,
        32,
        "HIERARCHY_RECALL_OVERFETCH_FACTOR must be between 1 and 32",
    )
    _require_int_min(settings.RETRIEVAL_OVERFETCH_MAX_K or 0, 0, "RETRIEVAL_OVERFETCH_MAX_K must be >= 0")
    auth_boost = settings.RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX or 0.0
    _require_float_between(
        auth_boost,
        0.0,
        1.0,
        "RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX must be between 0 and 1",
    )
    latest_boost = settings.RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX or 0.0
    _require_float_between(
        latest_boost,
        0.0,
        1.0,
        "RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX must be between 0 and 1",
    )
    _require_int_min(
        settings.RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS or 0, 1, "RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS must be >= 1"
    )
    _require_int_min(settings.MILVUS_EXPR_MAX_DOC_IDS or 0, 0, "MILVUS_EXPR_MAX_DOC_IDS must be >= 0")

    rebuild_max_chunks = settings.RETRIEVAL_REBUILD_MAX_CHUNKS or 0
    _require_int_min(rebuild_max_chunks, 0, "RETRIEVAL_REBUILD_MAX_CHUNKS must be >= 0")
    _raise_if(is_production and rebuild_max_chunks <= 0, "RETRIEVAL_REBUILD_MAX_CHUNKS must be > 0 in production")
    _require_int_min(
        settings.BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS or 0, 2, "BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS must be >= 2"
    )
    _require_int_min(
        settings.BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS or 0, 0, "BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS must be >= 0"
    )


def validate_embedding_and_migration(settings: Settings) -> None:
    reject_retired_model_provider(settings.EMBEDDING_PROVIDER, capability="embedding")
    if settings.EMBEDDING_SHADOW_ENABLED:
        reject_retired_model_provider(settings.EMBEDDING_SHADOW_PROVIDER, capability="embedding")
    if settings.IMAGE_EMBEDDING_ENABLED:
        raise ValueError(
            "IMAGE_EMBEDDING_ENABLED has been retired; image uploads, OCR and vision APIs remain supported"
        )
    reject_retired_model_provider(settings.KG_EXTRACTION_BACKEND, capability="kg_extraction")
    reject_retired_model_provider(settings.KG_EXTRACT_LONG_DOC_BACKEND, capability="kg_extraction")
    if settings.KG_GLINER_ENABLED:
        raise ValueError("KG_GLINER_ENABLED has been retired; use llm or heuristic extraction")
    _require_int_min(settings.EMBEDDING_CACHE_TTL_SEC or 0, 0, "EMBEDDING_CACHE_TTL_SEC must be >= 0")

    emb_prefix = (settings.EMBEDDING_CACHE_PREFIX or "").strip()
    _require_nonempty(emb_prefix, "EMBEDDING_CACHE_PREFIX must be non-empty")
    _require_no_whitespace(emb_prefix, "EMBEDDING_CACHE_PREFIX must not contain whitespace")
    _set_if_changed(settings, "EMBEDDING_CACHE_PREFIX", emb_prefix)

    _require_float_positive(settings.EMBEDDING_API_TIMEOUT_SEC or 0.0, "EMBEDDING_API_TIMEOUT_SEC must be > 0")
    _require_int_min(settings.EMBEDDING_API_BATCH_SIZE or 0, 1, "EMBEDDING_API_BATCH_SIZE must be >= 1")
    _require_int_min(settings.EMBEDDING_API_MAX_CONCURRENCY or 0, 1, "EMBEDDING_API_MAX_CONCURRENCY must be >= 1")
    _require_int_min(settings.EMBEDDING_API_MAX_RETRIES or 0, 0, "EMBEDDING_API_MAX_RETRIES must be >= 0")
    _require_float_min(
        settings.EMBEDDING_API_RETRY_BACKOFF_SEC or 0.0, 0.0, "EMBEDDING_API_RETRY_BACKOFF_SEC must be >= 0"
    )
    _require_float_min(
        settings.EMBEDDING_API_RETRY_JITTER_SEC or 0.0, 0.0, "EMBEDDING_API_RETRY_JITTER_SEC must be >= 0"
    )

    # Gap5: embedding blue-green migration / dual-write config validation.
    shadow_enabled = settings.EMBEDDING_SHADOW_ENABLED
    if shadow_enabled:
        _raise_if(
            str(settings.VECTOR_BACKEND or "milvus").strip().lower() != "milvus",
            "EMBEDDING_SHADOW_ENABLED requires VECTOR_BACKEND=milvus",
        )

        shadow_model = (settings.EMBEDDING_SHADOW_MODEL or "").strip()
        _require_nonempty(
            shadow_model,
            "EMBEDDING_SHADOW_MODEL must be non-empty when EMBEDDING_SHADOW_ENABLED=true",
        )
        _set_if_changed(settings, "EMBEDDING_SHADOW_MODEL", shadow_model)

        shadow_collection = (settings.MILVUS_SHADOW_COLLECTION_NAME or "").strip()
        _require_nonempty(
            shadow_collection,
            "MILVUS_SHADOW_COLLECTION_NAME must be non-empty when EMBEDDING_SHADOW_ENABLED=true",
        )
        _require_no_whitespace(shadow_collection, "MILVUS_SHADOW_COLLECTION_NAME must not contain whitespace")
        primary_collection = (settings.MILVUS_COLLECTION_NAME or "").strip()
        _raise_if(
            primary_collection and primary_collection == shadow_collection,
            "MILVUS_SHADOW_COLLECTION_NAME must differ from MILVUS_COLLECTION_NAME",
        )
        _set_if_changed(settings, "MILVUS_SHADOW_COLLECTION_NAME", shadow_collection)

        shadow_provider = (settings.EMBEDDING_SHADOW_PROVIDER or "").strip()
        if shadow_provider:
            _require_no_whitespace(shadow_provider, "EMBEDDING_SHADOW_PROVIDER must not contain whitespace")
        _set_if_changed(settings, "EMBEDDING_SHADOW_PROVIDER", shadow_provider)

        shadow_api_base = (settings.EMBEDDING_SHADOW_API_BASE or "").strip()
        if shadow_api_base:
            _require_no_whitespace(shadow_api_base, "EMBEDDING_SHADOW_API_BASE must not contain whitespace")
        _set_if_changed(settings, "EMBEDDING_SHADOW_API_BASE", shadow_api_base)

        shadow_api_key = (settings.EMBEDDING_SHADOW_API_KEY or "").strip()
        _set_if_changed(settings, "EMBEDDING_SHADOW_API_KEY", shadow_api_key)

    prog_prefix = (settings.EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX or "").strip()
    _require_nonempty(prog_prefix, "EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX must be non-empty")
    _require_no_whitespace(prog_prefix, "EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX must not contain whitespace")
    _set_if_changed(settings, "EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX", prog_prefix)
    _require_int_min(
        settings.EMBEDDING_MIGRATION_PROGRESS_TTL_SEC or 0, 0, "EMBEDDING_MIGRATION_PROGRESS_TTL_SEC must be >= 0"
    )


def validate_chat_and_retrieval_caches(settings: Settings) -> None:
    _require_int_min(settings.CHAT_RESPONSE_CACHE_TTL_SEC or 0, 0, "CHAT_RESPONSE_CACHE_TTL_SEC must be >= 0")
    _require_int_min(
        settings.CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES or 0, 0, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES must be >= 0"
    )
    _require_float_positive(
        settings.CHAT_RESPONSE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC or 0.0,
        "CHAT_RESPONSE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC must be > 0",
    )

    _require_int_min(
        settings.RETRIEVAL_CANDIDATE_CACHE_TTL_SEC or 0, 0, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC must be >= 0"
    )
    _require_float_positive(
        settings.RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC or 0.0,
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC must be > 0",
    )
    _require_int_min(
        settings.RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES or 0,
        0,
        "RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES must be >= 0",
    )

    cand_prefix = (settings.RETRIEVAL_CANDIDATE_CACHE_PREFIX or "").strip()
    _require_nonempty(cand_prefix, "RETRIEVAL_CANDIDATE_CACHE_PREFIX must be non-empty")
    _require_no_whitespace(cand_prefix, "RETRIEVAL_CANDIDATE_CACHE_PREFIX must not contain whitespace")
    _set_if_changed(settings, "RETRIEVAL_CANDIDATE_CACHE_PREFIX", cand_prefix)

    _require_int_min(settings.SEMANTIC_CACHE_TTL_SEC or 0, 0, "SEMANTIC_CACHE_TTL_SEC must be >= 0")
    _require_int_min(settings.SEMANTIC_CACHE_MAX_VALUE_BYTES or 0, 0, "SEMANTIC_CACHE_MAX_VALUE_BYTES must be >= 0")
    sem_threshold = settings.SEMANTIC_CACHE_SCORE_THRESHOLD or 0.0
    _require_float_between(sem_threshold, 0.0, 1.0, "SEMANTIC_CACHE_SCORE_THRESHOLD must be between 0 and 1")
    _require_float_positive(
        settings.DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC or 0.0,
        "DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC must be > 0",
    )
    _require_int_min(
        settings.RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY or 0, 0, "RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY must be >= 0"
    )
    _set_if_changed(settings, "SEMANTIC_CACHE_SCORE_THRESHOLD", sem_threshold)
    _require_int_min(settings.SEMANTIC_CACHE_SEARCH_TOP_K or 0, 1, "SEMANTIC_CACHE_SEARCH_TOP_K must be >= 1")

    sem_prefix = (settings.SEMANTIC_CACHE_REDIS_PREFIX or "").strip()
    _require_nonempty(sem_prefix, "SEMANTIC_CACHE_REDIS_PREFIX must be non-empty")
    _require_no_whitespace(sem_prefix, "SEMANTIC_CACHE_REDIS_PREFIX must not contain whitespace")
    _set_if_changed(settings, "SEMANTIC_CACHE_REDIS_PREFIX", sem_prefix)

    sem_collection = (settings.SEMANTIC_CACHE_COLLECTION_NAME or "").strip()
    _require_nonempty(sem_collection, "SEMANTIC_CACHE_COLLECTION_NAME must be non-empty")
    _require_no_whitespace(sem_collection, "SEMANTIC_CACHE_COLLECTION_NAME must not contain whitespace")
    _set_if_changed(settings, "SEMANTIC_CACHE_COLLECTION_NAME", sem_collection)

    _require_int_min(
        settings.EVIDENCE_POST_RERANK_CACHE_TTL_SEC or 0, 0, "EVIDENCE_POST_RERANK_CACHE_TTL_SEC must be >= 0"
    )
    _require_int_min(
        settings.EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES or 0, 0, "EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES must be >= 0"
    )
    post_rerank_score_calibration_alpha = settings.EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA or 0.0
    _require_float_between(
        post_rerank_score_calibration_alpha,
        0.0,
        1.0,
        "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA must be between 0 and 1",
    )
    _normalize_choice_setting(
        settings,
        "EVIDENCE_POST_RERANK_CACHE_BACKEND",
        "memory",
        {"memory", "redis"},
        "EVIDENCE_POST_RERANK_CACHE_BACKEND must be one of: memory, redis",
    )
    post_rerank_cache_prefix = (settings.EVIDENCE_POST_RERANK_CACHE_PREFIX or "").strip()
    _require_nonempty(post_rerank_cache_prefix, "EVIDENCE_POST_RERANK_CACHE_PREFIX must be non-empty")
    _require_no_whitespace(post_rerank_cache_prefix, "EVIDENCE_POST_RERANK_CACHE_PREFIX must not contain whitespace")
    _set_if_changed(settings, "EVIDENCE_POST_RERANK_CACHE_PREFIX", post_rerank_cache_prefix)

    _require_int_min(
        settings.RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY or 0, 0, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY must be >= 0"
    )
    _require_float_min(
        settings.RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC or 0.0, 0.0, "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC must be >= 0"
    )
    _require_int_min(
        settings.RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY or 0,
        0,
        "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY must be >= 0",
    )
    adm_prefix = (settings.RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX or "").strip()
    _require_nonempty(adm_prefix, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX must be non-empty")
    _require_no_whitespace(adm_prefix, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX must not contain whitespace")
    _set_if_changed(settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX", adm_prefix)
    _require_int_min(
        settings.RAG_KG_CHUNK_INJECTION_MAX_CHUNKS or 0, 0, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS must be >= 0"
    )
    kg_chunk_boost_weight = settings.RAG_KG_CHUNK_BOOST_WEIGHT or 0.15
    _require_float_between(kg_chunk_boost_weight, 0.0, 1.0, "RAG_KG_CHUNK_BOOST_WEIGHT must be between 0 and 1")
    _set_if_changed(settings, "RAG_KG_CHUNK_BOOST_WEIGHT", kg_chunk_boost_weight)
    _require_int_min(settings.RAG_KG_CHUNK_BOOST_MAX_PROMOTED or 0, 0, "RAG_KG_CHUNK_BOOST_MAX_PROMOTED must be >= 0")


def validate_kg_search(settings: Settings) -> None:
    _require_int_min(settings.KG_SEARCH_CACHE_TTL_SEC or 0, 0, "KG_SEARCH_CACHE_TTL_SEC must be >= 0")
    _require_int_min(settings.KG_SEARCH_CACHE_MAX_ENTRIES or 0, 0, "KG_SEARCH_CACHE_MAX_ENTRIES must be >= 0")
    _require_int_between(
        settings.KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS or 0,
        1,
        10000,
        "KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS must be between 1 and 10000",
    )
    kg_expand_budget_sec = settings.KG_SEARCH_EXPAND_BUDGET_SEC or 0.0
    _require_float_min(kg_expand_budget_sec, 0.0, "KG_SEARCH_EXPAND_BUDGET_SEC must be >= 0")
    _set_if_changed(settings, "KG_SEARCH_EXPAND_BUDGET_SEC", kg_expand_budget_sec)
    _require_int_min(settings.KG_SEARCH_LATENCY_SLO_MS or 0, 0, "KG_SEARCH_LATENCY_SLO_MS must be >= 0")
    kg_quality_low = settings.KG_QUALITY_LOW_CONFIDENCE_THRESHOLD or 0.3
    _require_float_between(kg_quality_low, 0.0, 1.0, "KG_QUALITY_LOW_CONFIDENCE_THRESHOLD must be between 0 and 1")
    _set_if_changed(settings, "KG_QUALITY_LOW_CONFIDENCE_THRESHOLD", kg_quality_low)
    _require_int_min(settings.KG_QUALITY_RELATION_EDGES_LIMIT or 0, 0, "KG_QUALITY_RELATION_EDGES_LIMIT must be >= 0")
    kg_query_mode_default = (settings.KG_SEARCH_QUERY_MODE_DEFAULT or "auto").strip().lower()
    _raise_if(
        kg_query_mode_default not in {"auto", "local", "global", "drift"},
        "KG_SEARCH_QUERY_MODE_DEFAULT must be one of: auto, local, global, drift",
    )
    _set_if_changed(settings, "KG_SEARCH_QUERY_MODE_DEFAULT", kg_query_mode_default)
    _require_int_min(
        settings.KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS or 0, 1, "KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS must be >= 1"
    )
    _require_int_min(
        settings.KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS or 0, 1, "KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS must be >= 1"
    )
    _require_int_min(
        settings.KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS or 0,
        1,
        "KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS must be >= 1",
    )
    _require_int_min(
        settings.KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS or 0, 1, "KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS must be >= 1"
    )
    local_entity_weight_bonus = settings.KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS or 0.05
    _require_float_between(
        local_entity_weight_bonus,
        0.0,
        1.0,
        "KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS must be between 0 and 1",
    )
    _set_if_changed(settings, "KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS", local_entity_weight_bonus)
    _require_int_min(
        settings.KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK or 0, 0, "KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK must be >= 0"
    )
    _require_int_min(
        settings.KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT or 0,
        0,
        "KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT must be >= 0",
    )
    _require_int_min(
        settings.KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT or 0, 0, "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT must be >= 0"
    )
    _raise_if(
        (settings.KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY or "uniform").strip().lower() not in {"head", "uniform"},
        "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY must be one of: head, uniform",
    )
    _require_int_min(settings.KG_EXTRACT_LONG_DOC_MIN_CHUNKS or 0, 0, "KG_EXTRACT_LONG_DOC_MIN_CHUNKS must be >= 0")
    kg_serving_min_score = settings.KG_SEARCH_SERVING_MIN_SCORE or 0.0
    _require_float_between(kg_serving_min_score, 0.0, 1.0, "KG_SEARCH_SERVING_MIN_SCORE must be between 0 and 1")
    _set_if_changed(settings, "KG_SEARCH_SERVING_MIN_SCORE", kg_serving_min_score)
    _require_int_min(
        settings.KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER or 0, 1, "KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER must be >= 1"
    )


def validate_vector_write_and_table_catalog(settings: Settings) -> None:
    _require_int_min(settings.VECTOR_WRITE_BATCH_SIZE or 0, 1, "VECTOR_WRITE_BATCH_SIZE must be >= 1")
    _require_int_min(settings.VECTOR_WRITE_BATCH_MAX_CHARS or 0, 0, "VECTOR_WRITE_BATCH_MAX_CHARS must be >= 0")

    _require_int_min(settings.DB_CATALOG_ROW_SYNC_MAX_TABLES or 0, 1, "DB_CATALOG_ROW_SYNC_MAX_TABLES must be >= 1")
    _require_int_min(
        settings.DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE or 0, 1, "DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE must be >= 1"
    )
    _require_int_min(settings.DB_CATALOG_ROW_SYNC_MAX_COLS or 0, 1, "DB_CATALOG_ROW_SYNC_MAX_COLS must be >= 1")
    _require_int_min(settings.TABLE_QUERY_MAX_JOIN_TABLES or 0, 1, "TABLE_QUERY_MAX_JOIN_TABLES must be >= 1")
    _require_int_min(settings.TABLE_TAG_PLAN_CANDIDATES_TOP_N or 0, 1, "TABLE_TAG_PLAN_CANDIDATES_TOP_N must be >= 1")
    tag_ambiguity_gap = settings.TABLE_TAG_AMBIGUITY_SCORE_GAP or 0.03
    _require_float_between(tag_ambiguity_gap, 0.0, 1.0, "TABLE_TAG_AMBIGUITY_SCORE_GAP must be between 0 and 1")
    _set_if_changed(settings, "TABLE_TAG_AMBIGUITY_SCORE_GAP", tag_ambiguity_gap)
    tag_cost_fanout_weight = settings.TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT or 0.08
    _require_float_between(
        tag_cost_fanout_weight,
        0.0,
        1.0,
        "TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT must be between 0 and 1",
    )
    _set_if_changed(settings, "TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT", tag_cost_fanout_weight)
    tag_cost_selectivity_weight = settings.TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT or 0.12
    _require_float_between(
        tag_cost_selectivity_weight,
        0.0,
        1.0,
        "TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT must be between 0 and 1",
    )
    _set_if_changed(settings, "TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT", tag_cost_selectivity_weight)
    tag_fanout_ratio_alert = settings.TABLE_TAG_COST_FANOUT_RATIO_ALERT or 20.0
    _require_float_min(tag_fanout_ratio_alert, 1.0, "TABLE_TAG_COST_FANOUT_RATIO_ALERT must be >= 1")
    _set_if_changed(settings, "TABLE_TAG_COST_FANOUT_RATIO_ALERT", tag_fanout_ratio_alert)
    tag_selectivity_min = settings.TABLE_TAG_COST_SELECTIVITY_MIN or 0.2
    _require_float_between(tag_selectivity_min, 0.0, 1.0, "TABLE_TAG_COST_SELECTIVITY_MIN must be between 0 and 1")
    _set_if_changed(settings, "TABLE_TAG_COST_SELECTIVITY_MIN", tag_selectivity_min)
    tag_low_conf = settings.TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD or 0.55
    _require_float_between(tag_low_conf, 0.0, 1.0, "TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD must be between 0 and 1")
    _set_if_changed(settings, "TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD", tag_low_conf)
    _require_int_min(
        settings.RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX or 0,
        1,
        "RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX must be >= 1",
    )


def validate_evidence_governance_and_quotas(settings: Settings) -> None:
    signing_key_id = (settings.EVIDENCE_CAPSULE_SIGNING_KEY_ID or "default").strip()
    _require_nonempty(signing_key_id, "EVIDENCE_CAPSULE_SIGNING_KEY_ID must be non-empty")
    _require_no_whitespace(signing_key_id, "EVIDENCE_CAPSULE_SIGNING_KEY_ID must not contain whitespace")
    _set_if_changed(settings, "EVIDENCE_CAPSULE_SIGNING_KEY_ID", signing_key_id)

    if settings.EVIDENCE_CAPSULE_SIGNING_ENABLED:
        signing_secret = (settings.EVIDENCE_CAPSULE_SIGNING_SECRET or "").strip()
        _require_nonempty(signing_secret, "EVIDENCE_CAPSULE_SIGNING_SECRET must be non-empty when signing is enabled")

    index_strictness = _normalize_choice_setting(
        settings,
        "INDEX_CONSISTENCY_STRICTNESS",
        "off",
        {"off", "warn", "strict"},
        "INDEX_CONSISTENCY_STRICTNESS must be one of: off, strict, warn",
    )
    if index_strictness == "warn":
        _set_if_changed(settings, "INDEX_CONSISTENCY_STRICTNESS", index_strictness)

    _require_int_min(settings.CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT or 0, 0, "CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT must be >= 0")
    _require_int_min(
        settings.CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS or 0, 1, "CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS must be > 0"
    )
    _normalize_choice_setting(
        settings,
        "CHAT_ASSISTANT_TOKEN_QUOTA_MODE",
        "block",
        {"block", "warn"},
        "CHAT_ASSISTANT_TOKEN_QUOTA_MODE must be one of: block, warn",
    )

    _require_int_min(settings.TENANT_DOC_QUOTA_LIMIT or 0, 0, "TENANT_DOC_QUOTA_LIMIT must be >= 0")
    _require_int_min(settings.TENANT_STORAGE_QUOTA_LIMIT_BYTES or 0, 0, "TENANT_STORAGE_QUOTA_LIMIT_BYTES must be >= 0")
    _require_int_min(settings.TENANT_EMBED_CHAR_QUOTA_LIMIT or 0, 0, "TENANT_EMBED_CHAR_QUOTA_LIMIT must be >= 0")
    _require_int_min(
        settings.TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS or 0, 1, "TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS must be > 0"
    )
    _normalize_choice_setting(
        settings,
        "TENANT_EMBED_CHAR_QUOTA_MODE",
        "block",
        {"block", "warn"},
        "TENANT_EMBED_CHAR_QUOTA_MODE must be one of: block, warn",
    )

    _require_int_min(
        settings.PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES or 0,
        1,
        "PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES must be > 0",
    )
    _require_int_min(
        settings.PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS or 0,
        1,
        "PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS must be > 0",
    )


def validate_workflow_and_retrieval_profiles(settings: Settings) -> None:
    # Validate workflow mode
    valid_workflow_modes = {"chain", "routing", "parallel", "react", "planner", "evaluator"}
    if settings.WORKFLOW_MODE not in valid_workflow_modes:
        raise ValueError(f"WORKFLOW_MODE ({settings.WORKFLOW_MODE}) must be one of {valid_workflow_modes}")

    # Validate default retrieval profile used by chat when request-side knobs are omitted.
    valid_retrieval_profiles = {
        "",
        "fast",
        "balanced",
        "quality",
        "recall20",
        "recall50",
        "coverage80",
        "hybrid_ce",
        "grounded_strict",
        "hierarchy_recall20",
        "hierarchy_hybrid_ce",
        "hierarchy_grounded_strict",
    }
    chat_default_profile = (settings.CHAT_DEFAULT_RETRIEVAL_PROFILE or "").strip().lower()
    if chat_default_profile not in valid_retrieval_profiles:
        raise ValueError(
            "CHAT_DEFAULT_RETRIEVAL_PROFILE must be one of: " + ", ".join(sorted(valid_retrieval_profiles))
        )
    if settings.CHAT_DEFAULT_RETRIEVAL_PROFILE != chat_default_profile:
        settings.CHAT_DEFAULT_RETRIEVAL_PROFILE = chat_default_profile

    retrieval_contract_mode = normalize_retrieval_contract_mode(settings.RETRIEVAL_CONTRACT_MODE or "")
    if retrieval_contract_mode not in VALID_RETRIEVAL_CONTRACT_MODES:
        raise ValueError("RETRIEVAL_CONTRACT_MODE must be one of: " + ", ".join(sorted(VALID_RETRIEVAL_CONTRACT_MODES)))
    if settings.RETRIEVAL_CONTRACT_MODE != retrieval_contract_mode:
        settings.RETRIEVAL_CONTRACT_MODE = retrieval_contract_mode


def validate_claim_verifier(settings: Settings) -> None:
    claim_verifier_mode = (settings.RAG_CLAIM_VERIFIER_MODE or "token_overlap").strip().lower()
    valid_claim_verifier_modes = {"token_overlap", "semantic_heuristic", "strict"}
    if claim_verifier_mode not in valid_claim_verifier_modes:
        raise ValueError("RAG_CLAIM_VERIFIER_MODE must be one of: " + ", ".join(sorted(valid_claim_verifier_modes)))
    if settings.RAG_CLAIM_VERIFIER_MODE != claim_verifier_mode:
        settings.RAG_CLAIM_VERIFIER_MODE = claim_verifier_mode

    claim_nli_provider = (settings.RAG_CLAIM_NLI_VERIFIER_PROVIDER or "none").strip().lower()
    claim_nli_aliases = {
        "": "none",
        "off": "none",
        "false": "none",
        "0": "none",
        "disabled": "none",
        "none": "none",
        "openai": "openai_compatible",
        "openai-compatible": "openai_compatible",
        "openai_compatible": "openai_compatible",
    }
    claim_nli_provider = claim_nli_aliases.get(claim_nli_provider, claim_nli_provider)
    valid_claim_nli_providers = {"none", "openai_compatible"}
    if claim_nli_provider not in valid_claim_nli_providers:
        raise ValueError(
            "RAG_CLAIM_NLI_VERIFIER_PROVIDER must be one of: " + ", ".join(sorted(valid_claim_nli_providers))
        )
    if settings.RAG_CLAIM_NLI_VERIFIER_PROVIDER != claim_nli_provider:
        settings.RAG_CLAIM_NLI_VERIFIER_PROVIDER = claim_nli_provider
    if (settings.RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC or 0) < 1:
        raise ValueError("RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC must be >= 1")
    if settings.RAG_CLAIM_NLI_VERIFIER_ENABLED and claim_nli_provider == "openai_compatible":
        claim_nli_model = (settings.RAG_CLAIM_NLI_VERIFIER_MODEL or "").strip()
        if not claim_nli_model:
            raise ValueError("RAG_CLAIM_NLI_VERIFIER_MODEL is required when NLI verifier is enabled")
        if settings.RAG_CLAIM_NLI_VERIFIER_MODEL != claim_nli_model:
            settings.RAG_CLAIM_NLI_VERIFIER_MODEL = claim_nli_model


def validate_retrieval_fallback_modes(settings: Settings) -> None:
    valid_retrieval_modes = {"hybrid", "vector", "keyword", "mmr"}
    fallback_mode = _normalize_lower_choice(settings.RETRIEVAL_HARD_FALLBACK_MODE, "keyword")
    _raise_if(
        fallback_mode not in valid_retrieval_modes,
        f"RETRIEVAL_HARD_FALLBACK_MODE ({fallback_mode}) must be one of {valid_retrieval_modes}",
    )
    _set_if_changed(settings, "RETRIEVAL_HARD_FALLBACK_MODE", fallback_mode)
    _require_int_min(settings.RETRIEVAL_HARD_FALLBACK_TOP_K or 0, 1, "RETRIEVAL_HARD_FALLBACK_TOP_K must be >= 1")

    must_recall_second_pass_mode = _normalize_lower_choice(settings.RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE, "keyword")
    _raise_if(
        must_recall_second_pass_mode not in valid_retrieval_modes,
        "RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE "
        f"({must_recall_second_pass_mode}) must be one of {valid_retrieval_modes}",
    )
    _set_if_changed(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE", must_recall_second_pass_mode)
    _require_int_min(
        settings.RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K or 0, 1, "RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K must be >= 1"
    )
    contextual_followup_mode = _normalize_lower_choice(settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE, "keyword")
    _raise_if(
        contextual_followup_mode not in valid_retrieval_modes,
        f"RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE ({contextual_followup_mode}) must be one of {valid_retrieval_modes}",
    )
    _set_if_changed(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE", contextual_followup_mode)
    _require_int_min(
        settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K or 0, 1, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K must be >= 1"
    )
    _require_int_min(
        settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS or 0, 1, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS must be >= 1"
    )
    _require_int_min(
        settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS or 0, 0, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS must be >= 0"
    )
    _require_int_min(
        settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS or 0,
        2,
        "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS must be >= 2",
    )
    _require_int_min(
        settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS or 0,
        32,
        "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS must be >= 32",
    )
    _require_int_min(
        settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS or 0, 1, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS must be >= 1"
    )
    contextual_followup_latency_budget_ms = settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS or 500.0
    _require_float_min(
        contextual_followup_latency_budget_ms,
        0.0,
        "RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS must be >= 0",
    )
    _set_if_changed(
        settings,
        "RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS",
        contextual_followup_latency_budget_ms,
    )
    _require_int_min(
        settings.RAG_CONTEXT_DENOISE_MAX_TOTAL_TOKENS or 0, 0, "RAG_CONTEXT_DENOISE_MAX_TOTAL_TOKENS must be >= 0"
    )
    _require_int_min(
        settings.CONTEXTUAL_RETRIEVAL_LLM_MAX_INPUT_CHARS or 0,
        0,
        "CONTEXTUAL_RETRIEVAL_LLM_MAX_INPUT_CHARS must be >= 0",
    )
    _require_int_min(
        settings.CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS or 0,
        0,
        "CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS must be >= 0",
    )
    intent_router_model_confidence_min = settings.RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN or 0.7
    _require_float_between(
        intent_router_model_confidence_min,
        0.0,
        1.0,
        "RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN must be between 0 and 1",
    )
    _set_if_changed(settings, "RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN", intent_router_model_confidence_min)
    intent_router_model_path = (settings.RAG_INTENT_ROUTER_MODEL_PATH or "").strip()
    _set_if_changed(settings, "RAG_INTENT_ROUTER_MODEL_PATH", intent_router_model_path)


def validate_parse_quality(settings: Settings) -> None:
    low_quality = settings.RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD or 0.35
    _require_float_between(low_quality, 0.0, 1.0, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD must be between 0 and 1")
    alert_ratio = settings.RETRIEVAL_PARSE_QUALITY_ALERT_RATIO or 0.5
    _require_float_between(alert_ratio, 0.0, 1.0, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO must be between 0 and 1")
    _normalize_choice_setting(
        settings,
        "RETRIEVAL_PARSE_QUALITY_GATE_PROFILE",
        "warn",
        {"off", "warn", "strict"},
        "RETRIEVAL_PARSE_QUALITY_GATE_PROFILE must be one of: off, warn, strict",
    )
    parse_risk_min_low_ratio = settings.RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO or 0.5
    _require_float_between(
        parse_risk_min_low_ratio,
        0.0,
        1.0,
        "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO must be between 0 and 1",
    )
    raw_parse_risk_min_considered = settings.RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED
    parse_risk_min_considered = int(3 if raw_parse_risk_min_considered is None else raw_parse_risk_min_considered)
    _require_int_min(
        parse_risk_min_considered,
        1,
        "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED must be >= 1",
    )
    parse_risk_auto_enqueue_levels = [
        p.strip()
        for p in str(
            settings.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS or DEFAULT_RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS
        ).split(",")
    ]
    allowed_levels = {str(x).strip().lower() for x in parse_risk_auto_enqueue_levels if str(x).strip()}
    if not allowed_levels:
        allowed_levels = {"high", "medium"}
    _raise_if(
        not allowed_levels.issubset({"high", "medium", "low", "unknown"}),
        "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS must be a CSV subset of: high, medium, low, unknown",
    )
    settings.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS = ",".join(sorted(allowed_levels))
    parse_risk_auto_enqueue_min_score = settings.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE or 0.0
    _require_float_between(
        parse_risk_auto_enqueue_min_score,
        0.0,
        1.0,
        "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE must be between 0 and 1",
    )
    _set_if_changed(
        settings,
        "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE",
        parse_risk_auto_enqueue_min_score,
    )
    raw_parse_risk_reparse_max_docs = settings.RETRIEVAL_PARSE_RISK_REPARSE_MAX_DOCS
    parse_risk_reparse_max_docs = int(
        100 if raw_parse_risk_reparse_max_docs is None else raw_parse_risk_reparse_max_docs
    )
    _require_int_min(parse_risk_reparse_max_docs, 1, "RETRIEVAL_PARSE_RISK_REPARSE_MAX_DOCS must be >= 1")


def validate_sparse_and_colbert_providers(settings: Settings) -> None:
    sparse_provider = normalize_sparse_provider_name(settings.SPARSE_RETRIEVAL_PROVIDER or "deterministic")
    if sparse_provider not in VALID_SPARSE_PROVIDERS:
        raise ValueError("SPARSE_RETRIEVAL_PROVIDER must be deterministic")
    settings.SPARSE_RETRIEVAL_PROVIDER = sparse_provider
    for field in ("COLBERT_RERANK_PROVIDER", "COLBERT_RETRIEVAL_PROVIDER"):
        provider = str(getattr(settings, field) or "deterministic").strip().lower()
        reject_retired_model_provider(provider, capability="colbert")
        if provider != "deterministic":
            raise ValueError(f"{field} must be deterministic")
        setattr(settings, field, provider)
    reject_retired_model_provider(settings.GOVERNANCE_KEYWORDS_PROVIDER, capability="keyword")


def validate_checkpoint_memory_reranker(settings: Settings) -> None:
    # Validate checkpoint backend
    valid_checkpoint_backends = {"memory", "sqlite"}
    if settings.CHECKPOINT_BACKEND not in valid_checkpoint_backends:
        raise ValueError(
            f"CHECKPOINT_BACKEND ({settings.CHECKPOINT_BACKEND}) must be one of {valid_checkpoint_backends}"
        )

    # Validate memory store type
    valid_memory_stores = {"memory", "sqlite"}
    if settings.MEMORY_STORE_TYPE not in valid_memory_stores:
        raise ValueError(f"MEMORY_STORE_TYPE ({settings.MEMORY_STORE_TYPE}) must be one of {valid_memory_stores}")

    reject_retired_model_provider(settings.RERANKER_PROVIDER, capability="reranker")
    # Validate reranker provider
    # Keep this aligned with app.rag.reranker.factory.get_reranker().
    valid_reranker_providers = {
        "llm",
        "pc",
        "parent_child",
        "weighted",
        "openai",
        "dashscope",
        "aliyun",
        "colbert",
        "late_interaction",
        "ltr",
        "long_context",
        "mmr",
        "kg_pagerank",
        "kg_rrf",
        "none",
    }
    if settings.RERANKER_PROVIDER not in valid_reranker_providers:
        raise ValueError(f"RERANKER_PROVIDER ({settings.RERANKER_PROVIDER}) must be one of {valid_reranker_providers}")


def validate_rag_eval_gate(settings: Settings) -> None:
    rag_eval_faithfulness_min = settings.RAG_EVAL_GATE_FAITHFULNESS_MIN or 0.8
    if rag_eval_faithfulness_min < 0.0 or rag_eval_faithfulness_min > 1.0:
        raise ValueError("RAG_EVAL_GATE_FAITHFULNESS_MIN must be between 0 and 1")
    if settings.RAG_EVAL_GATE_FAITHFULNESS_MIN != rag_eval_faithfulness_min:
        settings.RAG_EVAL_GATE_FAITHFULNESS_MIN = rag_eval_faithfulness_min

    rag_eval_answer_relevancy_min = settings.RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN or 0.75
    if rag_eval_answer_relevancy_min < 0.0 or rag_eval_answer_relevancy_min > 1.0:
        raise ValueError("RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN must be between 0 and 1")
    if settings.RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN != rag_eval_answer_relevancy_min:
        settings.RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN = rag_eval_answer_relevancy_min

    rag_eval_context_precision_min = settings.RAG_EVAL_GATE_CONTEXT_PRECISION_MIN or 0.7
    if rag_eval_context_precision_min < 0.0 or rag_eval_context_precision_min > 1.0:
        raise ValueError("RAG_EVAL_GATE_CONTEXT_PRECISION_MIN must be between 0 and 1")
    if settings.RAG_EVAL_GATE_CONTEXT_PRECISION_MIN != rag_eval_context_precision_min:
        settings.RAG_EVAL_GATE_CONTEXT_PRECISION_MIN = rag_eval_context_precision_min

    rag_eval_summary_path = str(settings.RAG_EVAL_GATE_SUMMARY_PATH or _DEFAULT_RAG_EVAL_SUMMARY_PATH).strip()
    if not rag_eval_summary_path:
        raise ValueError("RAG_EVAL_GATE_SUMMARY_PATH must be non-empty")
    if settings.RAG_EVAL_GATE_SUMMARY_PATH != rag_eval_summary_path:
        settings.RAG_EVAL_GATE_SUMMARY_PATH = rag_eval_summary_path
