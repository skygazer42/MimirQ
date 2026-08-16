"""
Split-out sections of ``Settings.validate_settings`` (see ``app.core.config``).

Each function below is one logical segment of the original monolithic validator,
kept byte-for-byte identical (with ``self`` renamed to ``settings``) and called
by ``Settings.validate_settings`` in the original order. Segments that need
values computed in an earlier segment (``is_production``, ``auth_mode``,
``issuer``, ``jwks_urls_raw``) recompute them with the exact original
expressions, which are pure derivations of unmutated fields/environment.
"""
import ipaddress
import os
import re
import warnings
from collections.abc import Mapping
from urllib.parse import urlparse
from uuid import UUID

from email_validator import EmailNotValidError, validate_email

# The names below are injected by ``app.core.config`` at import time. This module
# must not import any app-internal module (``app.core.config`` and its imports
# form the dependency-tree leaf), so the shared helpers/constants defined or
# imported there are bound onto this module by ``app.core.config`` instead.
is_production_env = None
validate_jwt_remote_url = None
normalize_object_storage_provider_name = None
parse_object_storage_region_profiles = None
normalize_retrieval_contract_mode = None
VALID_RETRIEVAL_CONTRACT_MODES = None
normalize_sparse_provider_name = None
VALID_SPARSE_PROVIDERS = None
DEFAULT_RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS = None
_ALL_INTERFACES_HOST = None
_COMMA_OR_WHITESPACE_RE = None
_LEGACY_DEV_SECRET_KEY = None
_LOCAL_MINIO_DEFAULT_CREDENTIAL = None
_DEFAULT_RAG_EVAL_SUMMARY_PATH = None

def validate_uvicorn_workers_and_distributed_limits(settings):
    is_production = is_production_env()

    workers_raw = str(os.getenv("UVICORN_WORKERS", "1") or "1").strip()
    try:
        uvicorn_workers = int(workers_raw)
    except ValueError as exc:
        raise ValueError("UVICORN_WORKERS must be a positive integer") from exc
    if uvicorn_workers < 1:
        raise ValueError("UVICORN_WORKERS must be a positive integer")

    if is_production and uvicorn_workers > 1:
        distributed_limiter = bool(getattr(settings, "RATE_LIMIT_REDIS_ENABLED", False)) and bool(
            str(getattr(settings, "REDIS_URL", "") or "").strip()
        )
        if bool(getattr(settings, "RATE_LIMIT_ENABLED", False)) and not distributed_limiter:
            raise ValueError(
                "RATE_LIMIT_REDIS_ENABLED=true with REDIS_URL is required when UVICORN_WORKERS > 1"
            )
        if bool(getattr(settings, "TENANT_QPS_QUOTA_ENABLED", False)) and not distributed_limiter:
            raise ValueError(
                "TENANT_QPS_QUOTA_ENABLED with UVICORN_WORKERS > 1 requires "
                "RATE_LIMIT_REDIS_ENABLED=true and REDIS_URL"
            )
        if bool(getattr(settings, "BM25_INDEX_ENABLED", False)) and not bool(
            getattr(settings, "BM25_LAZY_BUILD_ENABLED", False)
        ):
            raise ValueError("BM25_LAZY_BUILD_ENABLED must be true when UVICORN_WORKERS > 1")


def validate_saml_replay(settings):
    is_production = is_production_env()
    if is_production and str(getattr(settings, "SAML_PROVIDERS_JSON", "") or "").strip():
        if not bool(getattr(settings, "SAML_REPLAY_REDIS_ENABLED", False)):
            raise ValueError("SAML_REPLAY_REDIS_ENABLED=true is required for SAML in production")
        if not str(getattr(settings, "REDIS_URL", "") or "").strip():
            raise ValueError("REDIS_URL is required for SAML replay protection in production")


def validate_trusted_hosts(settings):
    is_production = is_production_env()
    # Security: Host header hardening (production-only by default).
    if is_production and bool(getattr(settings, "TRUSTED_HOSTS_ENABLED", True)):
        raw_allowed = str(getattr(settings, "ALLOWED_HOSTS", "") or "").strip()
        allowed = [p.strip() for p in raw_allowed.split(",") if p.strip()]
        if not allowed:
            raise ValueError("ALLOWED_HOSTS required in production (comma-separated)")
        if "*" in allowed:
            raise ValueError("ALLOWED_HOSTS must not include '*' in production")


def validate_production_api_surface(settings):
    is_production = is_production_env()
    # Security: Reduce public API surface in production by default.
    if is_production:
        fields_set = getattr(settings, "model_fields_set", set()) or set()
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
        if bool(getattr(settings, "API_DOCS_ENABLED", False)) and not bool(getattr(settings, "API_OPENAPI_ENABLED", False)):
            settings.API_OPENAPI_ENABLED = True


def validate_cors(settings):
    is_production = is_production_env()
    # Security: CORS hardening (production guardrails).
    if is_production:
        # Production default: do not allow credentialed cross-origin calls unless explicitly enabled.
        # This avoids accidentally running a cookie-bearing API with permissive CORS defaults.
        if "CORS_ALLOW_CREDENTIALS" not in (getattr(settings, "model_fields_set", set()) or set()):
            settings.CORS_ALLOW_CREDENTIALS = False

        cors_raw = str(getattr(settings, "CORS_ORIGINS", "") or "")
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


def validate_auth_mode_and_jwt_claims(settings):
    is_production = is_production_env()
    # Security: Auth mode guard
    auth_mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()
    if auth_mode not in ("jwt", "header"):
        raise ValueError(f"Unsupported AUTH_MODE: {auth_mode}")
    if auth_mode == "header" and is_production:
        raise ValueError("AUTH_MODE=header is not allowed in production")
    if bool(getattr(settings, "LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED", False)):
        if is_production:
            raise ValueError("LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED is not allowed in production")
        if auth_mode != "header":
            raise ValueError("LOCAL_DEV_TENANT_BOOTSTRAP_ENABLED requires AUTH_MODE=header")

    initial_registration_token = str(getattr(settings, "INITIAL_REGISTRATION_TOKEN", "") or "").strip()
    if initial_registration_token.lower().startswith("sha256:"):
        digest = initial_registration_token.split(":", 1)[1].strip()
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest or ""):
            raise ValueError("INITIAL_REGISTRATION_TOKEN sha256 digest must be 64 hex chars")

    # Security: tenant-source guard. Without a verified JWT tenant claim the tenant id comes
    # from the client-controlled tenant header (cross-tenant spoofing of team-shared
    # resources); fail closed in production unless the deployment explicitly trusts the header.
    if auth_mode == "jwt" and is_production:
        tenant_claim = str(getattr(settings, "JWT_TENANT_CLAIM", "") or "").strip()
        if not tenant_claim and not bool(getattr(settings, "TENANT_HEADER_TRUSTED", False)):
            raise ValueError(
                "AUTH_MODE=jwt in production requires a trusted tenant source: "
                "set JWT_TENANT_CLAIM (recommended) or set TENANT_HEADER_TRUSTED=true "
                "to explicitly trust the client/gateway-supplied tenant header"
            )

    # Security: JWT tenant member auto-provision guard (enterprise).
    if bool(getattr(settings, "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED", False)):
        if auth_mode != "jwt":
            raise ValueError("JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED requires AUTH_MODE=jwt")
        claim = str(getattr(settings, "JWT_TENANT_CLAIM", "") or "").strip()
        if not claim:
            raise ValueError("JWT_TENANT_CLAIM required when JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED=true")

    issuer = str(getattr(settings, "JWT_ISSUER", "") or "").strip()
    if issuer:
        validate_jwt_remote_url(issuer, field_name="JWT_ISSUER")

    jwks_urls_raw = str(getattr(settings, "JWT_JWKS_URLS", "") or "").strip()
    if jwks_urls_raw:
        for raw_url in [item.strip() for item in jwks_urls_raw.split(",") if item.strip()]:
            validate_jwt_remote_url(raw_url, field_name="JWT_JWKS_URLS")


def validate_initial_admin_bootstrap(settings):
    email = str(getattr(settings, "INITIAL_ADMIN_EMAIL", "") or "").strip()
    username = str(getattr(settings, "INITIAL_ADMIN_USERNAME", "") or "").strip()
    password = str(getattr(settings, "INITIAL_ADMIN_PASSWORD", "") or "")
    password_file = str(getattr(settings, "INITIAL_ADMIN_PASSWORD_FILE", "") or "").strip()

    if not any((email, username, password, password_file)):
        return

    if not email or not username:
        raise ValueError(
            "INITIAL_ADMIN bootstrap requires "
            "INITIAL_ADMIN_EMAIL, INITIAL_ADMIN_USERNAME, and exactly one password source"
        )

    password_sources = int(bool(password)) + int(bool(password_file))
    if password_sources != 1:
        if password and password_file:
            raise ValueError("INITIAL_ADMIN_PASSWORD and INITIAL_ADMIN_PASSWORD_FILE are mutually exclusive")
        raise ValueError(
            "INITIAL_ADMIN bootstrap requires "
            "INITIAL_ADMIN_EMAIL, INITIAL_ADMIN_USERNAME, and exactly one password source"
        )

    try:
        normalized_email = validate_email(email, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError("INITIAL_ADMIN_EMAIL must be a valid email address") from exc
    if len(normalized_email) > 255:
        raise ValueError("INITIAL_ADMIN_EMAIL must be a valid email address")
    if len(username) < 3 or len(username) > 64:
        raise ValueError("INITIAL_ADMIN_USERNAME must be between 3 and 64 characters")
    if password:
        min_len = int(getattr(settings, "PASSWORD_MIN_LENGTH", 8) or 8)
        if len(password) < min_len:
            raise ValueError(f"INITIAL_ADMIN_PASSWORD must be at least {min_len} characters")
        if len(password.encode("utf-8")) > 72:
            raise ValueError("INITIAL_ADMIN_PASSWORD cannot be longer than 72 bytes for bcrypt")

    settings.INITIAL_ADMIN_EMAIL = normalized_email
    settings.INITIAL_ADMIN_USERNAME = username
    settings.INITIAL_ADMIN_PASSWORD_FILE = password_file


def validate_scim(settings):
    # Security: SCIM provisioning auth guard (enterprise).
    if bool(getattr(settings, "SCIM_ENABLED", False)):
        token_raw = str(getattr(settings, "SCIM_BEARER_TOKEN", "") or "").strip()
        tokens = [p.strip() for p in re.split(_COMMA_OR_WHITESPACE_RE, token_raw) if p.strip()]
        if not tokens:
            raise ValueError("SCIM_BEARER_TOKEN required when SCIM_ENABLED=true")
        for tok in tokens:
            if tok.lower().startswith("sha256:"):
                digest = tok.split(":", 1)[1].strip()
                if not re.fullmatch(r"[0-9a-fA-F]{64}", digest or ""):
                    raise ValueError("SCIM_BEARER_TOKEN sha256 digest must be 64 hex chars")

        tenant_raw = str(getattr(settings, "SCIM_TENANT_ID", "") or "").strip()
        if not tenant_raw:
            raise ValueError("SCIM_TENANT_ID required when SCIM_ENABLED=true")
        try:
            UUID(tenant_raw)
        except ValueError as exc:
            raise ValueError("SCIM_TENANT_ID must be a UUID") from exc

        allow_raw = str(getattr(settings, "SCIM_IP_ALLOWLIST_CIDRS", "") or "").strip()
        if allow_raw:
            cidrs = [p.strip() for p in re.split(_COMMA_OR_WHITESPACE_RE, allow_raw) if p.strip()]
            if not cidrs:
                raise ValueError("SCIM_IP_ALLOWLIST_CIDRS must be a comma/space-separated list of CIDRs")
            for cidr in cidrs:
                try:
                    ipaddress.ip_network(cidr, strict=False)
                except ValueError as exc:
                    raise ValueError(f"Invalid SCIM_IP_ALLOWLIST_CIDRS entry: {cidr}") from exc


def validate_dify_resolution_mode(settings):
    is_production = is_production_env()
    dify_resolution_mode = str(
        getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE", "mapped_only") or "mapped_only"
    ).strip().lower()
    valid_dify_resolution_modes = {"mapped_only", "allow_dataset_uuid"}
    if dify_resolution_mode not in valid_dify_resolution_modes:
        raise ValueError(
            "DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE must be one of: "
            + ", ".join(sorted(valid_dify_resolution_modes))
        )
    if is_production and dify_resolution_mode == "allow_dataset_uuid":
        raise ValueError(
            "DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE=allow_dataset_uuid is not allowed in production"
        )
    if settings.DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE != dify_resolution_mode:
        settings.DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE = dify_resolution_mode


def validate_rag_runtime_warmup(settings):
    if bool(getattr(settings, "RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY", False)) and not bool(
        getattr(settings, "RAG_RUNTIME_WARMUP_ENABLED", False)
    ):
        raise ValueError(
            "RAG_RUNTIME_WARMUP_ENABLED must be true when RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY=true"
        )


def validate_dify_external_knowledge(settings):
    is_production = is_production_env()
    # Security: Dify external knowledge adapter auth guard.
    if bool(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False)):
        token_raw = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", "") or "").strip()
        tokens = [p.strip() for p in re.split(_COMMA_OR_WHITESPACE_RE, token_raw) if p.strip()]
        if not tokens:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS required when DIFY_EXTERNAL_KNOWLEDGE_ENABLED=true")
        for tok in tokens:
            if tok.lower().startswith("sha256:"):
                digest = tok.split(":", 1)[1].strip()
                if not re.fullmatch(r"[0-9a-fA-F]{64}", digest or ""):
                    raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_API_KEYS sha256 digest must be 64 hex chars")

        tenant_raw = str(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", "") or "").strip()
        if is_production and not tenant_raw:
            raise ValueError(
                "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID is required when DIFY_EXTERNAL_KNOWLEDGE_ENABLED=true in production"
            )
        if tenant_raw:
            try:
                UUID(tenant_raw)
            except ValueError as exc:
                raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID must be a UUID") from exc

        top_k_max = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX", 5) or 0)
        if top_k_max < 1 or top_k_max > 200:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX must be between 1 and 200")
        internal_top_k_min = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN", 20) or 0)
        if internal_top_k_min < 1 or internal_top_k_min > 200:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN must be between 1 and 200")
        internal_top_k_multiplier = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER", 4) or 0
        )
        if internal_top_k_multiplier < 1 or internal_top_k_multiplier > 20:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER must be between 1 and 20")
        internal_top_k_max = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX", 50) or 0)
        if internal_top_k_max < 1 or internal_top_k_max > 200:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX must be between 1 and 200")
        if internal_top_k_max < top_k_max:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX must be >= DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX")
        if internal_top_k_max < internal_top_k_min:
            raise ValueError(
                "DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX must be >= DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN"
            )
        warmup_top_k = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K", 1) or 0)
        if warmup_top_k < 1 or warmup_top_k > 200:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TOP_K must be between 1 and 200")
        warmup_max_ids = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS", 8) or 0)
        if warmup_max_ids < 0 or warmup_max_ids > 500:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_WARMUP_MAX_KNOWLEDGE_IDS must be between 0 and 500")
        warmup_timeout_sec = float(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC", 60.0) or 0.0)
        if warmup_timeout_sec < 1.0 or warmup_timeout_sec > 600.0:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_WARMUP_TIMEOUT_SEC must be between 1 and 600")
        warmup_start_delay_sec = float(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC", 1.0) or 0.0
        )
        if warmup_start_delay_sec < 0.0 or warmup_start_delay_sec > 60.0:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_WARMUP_START_DELAY_SEC must be between 0 and 60")
        dify_overfetch_multiplier = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER", 1) or 0
        )
        if dify_overfetch_multiplier < 1 or dify_overfetch_multiplier > 20:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER must be between 1 and 20")
        dify_overfetch_max_k = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K", 0) or 0
        )
        if dify_overfetch_max_k < 0 or dify_overfetch_max_k > 500:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K must be between 0 and 500")
        primary_min_records = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS", 1) or 0)
        if primary_min_records < 1 or primary_min_records > top_k_max:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_RECORDS must be between 1 and TOP_K_MAX")
        primary_min_top_score = float(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE", 0.45) or 0.0
        )
        if primary_min_top_score < 0.0 or primary_min_top_score > 2.0:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_PRIMARY_MIN_TOP_SCORE must be between 0 and 2")
        response_cache_ttl_sec = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC", 30) or 0
        )
        if response_cache_ttl_sec < 0:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_TTL_SEC must be >= 0")
        response_cache_max_entries = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES", 512) or 0
        )
        if response_cache_max_entries < 0:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_MAX_ENTRIES must be >= 0")
        compact_min_top_score = float(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE", 0.7) or 0.0
        )
        if compact_min_top_score < 0.0 or compact_min_top_score > 2.0:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_TOP_SCORE must be between 0 and 2")
        compact_relative_floor = float(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR", 0.65) or 0.0
        )
        if compact_relative_floor < 0.0 or compact_relative_floor > 1.0:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_COMPACT_RELATIVE_SCORE_FLOOR must be between 0 and 1")
        compact_min_records = int(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS", 1) or 0)
        if compact_min_records < 1 or compact_min_records > top_k_max:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_COMPACT_MIN_RECORDS must be between 1 and TOP_K_MAX")
        fast_candidate_top_k_max = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX", 3) or 0
        )
        if fast_candidate_top_k_max < 1 or fast_candidate_top_k_max > top_k_max:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_FAST_CANDIDATE_TOP_K_MAX must be between 1 and TOP_K_MAX")
        fast_response_top_k_max = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX", 2) or 0
        )
        if fast_response_top_k_max < 1 or fast_response_top_k_max > top_k_max:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_FAST_RESPONSE_TOP_K_MAX must be between 1 and TOP_K_MAX")
        fast_content_max_chars = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS", 1400) or 0
        )
        if fast_content_max_chars < 200 or fast_content_max_chars > 10000:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_FAST_CONTENT_MAX_CHARS must be between 200 and 10000")
        fast_total_content_max_chars = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS", 2200) or 0
        )
        if fast_total_content_max_chars < 200 or fast_total_content_max_chars > 50000:
            raise ValueError(
                "DIFY_EXTERNAL_KNOWLEDGE_FAST_TOTAL_CONTENT_MAX_CHARS must be between 200 and 50000"
            )
        fast_metadata_preflight_statement_timeout_ms = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS", 600) or 0
        )
        if fast_metadata_preflight_statement_timeout_ms < 0 or fast_metadata_preflight_statement_timeout_ms > 30000:
            raise ValueError(
                "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_STATEMENT_TIMEOUT_MS must be between 0 and 30000"
            )
        fast_metadata_preflight_max_elapsed_ms = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS", 900) or 0
        )
        if fast_metadata_preflight_max_elapsed_ms < 0 or fast_metadata_preflight_max_elapsed_ms > 30000:
            raise ValueError(
                "DIFY_EXTERNAL_KNOWLEDGE_FAST_METADATA_PREFLIGHT_MAX_ELAPSED_MS must be between 0 and 30000"
            )
        metadata_anchor_total_budget_ms = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS", 1500) or 0
        )
        if metadata_anchor_total_budget_ms < 0 or metadata_anchor_total_budget_ms > 30000:
            raise ValueError(
                "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_TOTAL_BUDGET_MS must be between 0 and 30000"
            )
        kg_injection_max_chunks = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS", 3) or 0
        )
        if kg_injection_max_chunks < 0 or kg_injection_max_chunks > 50:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS must be between 0 and 50")
        kg_boost_weight = float(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT", 0.25) or 0.0)
        if kg_boost_weight < 0.0 or kg_boost_weight > 1.0:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT must be between 0 and 1")
        kg_boost_max_promoted = int(
            getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 2) or 0
        )
        if kg_boost_max_promoted < 0 or kg_boost_max_promoted > 20:
            raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED must be between 0 and 20")


def validate_secret_key_and_jwt_key_source(settings):
    auth_mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()
    issuer = str(getattr(settings, "JWT_ISSUER", "") or "").strip()
    jwks_urls_raw = str(getattr(settings, "JWT_JWKS_URLS", "") or "").strip()
    # Security: Validate SECRET_KEY (required for JWT verification)
    if auth_mode == "jwt":
        if (
            not settings.SECRET_KEY
            or settings.SECRET_KEY == _LEGACY_DEV_SECRET_KEY
            or len(settings.SECRET_KEY) < 32
        ):
            raise ValueError("SECRET_KEY required for JWT auth (min 32 chars)")

        algorithm = str(getattr(settings, "ALGORITHM", "HS256") or "HS256").strip() or "HS256"
        if algorithm.upper().startswith("HS"):
            # HS* uses SECRET_KEY.
            pass
        else:
            # RS*/ES* require a key source (JWKS) for verification.
            if not jwks_urls_raw:
                discovery_enabled = bool(getattr(settings, "JWT_JWKS_DISCOVERY_ENABLED", False))
                if not discovery_enabled:
                    raise ValueError(f"JWT_JWKS_URLS required for ALGORITHM={algorithm}")
                if not issuer:
                    raise ValueError("JWT_ISSUER required when JWT_JWKS_DISCOVERY_ENABLED=true")
    else:
        # Best-effort warning for other uses (sessions, future JWT issuance, etc.)
        if not settings.SECRET_KEY or settings.SECRET_KEY == _LEGACY_DEV_SECRET_KEY:
            warnings.warn(
                "SECRET_KEY is not configured. Set a strong value before enabling JWT auth or stored secret encryption.",
                UserWarning,
                stacklevel=2,
            )


def validate_minio(settings):
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


def validate_object_storage(settings):
    is_production = is_production_env()
    object_storage_provider = normalize_object_storage_provider_name(settings.OBJECT_STORAGE_PROVIDER)
    settings.OBJECT_STORAGE_PROVIDER = object_storage_provider
    object_storage_profiles = parse_object_storage_region_profiles(settings.OBJECT_STORAGE_REGION_PROFILES)
    data_region = str(settings.DATA_REGION or "").strip().lower()
    settings.DATA_REGION = data_region

    base_object_storage: dict[str, object] = {
        "provider": object_storage_provider,
        "enabled": bool(settings.OBJECT_STORAGE_ENABLED),
        "endpoint": str(settings.OBJECT_STORAGE_ENDPOINT or "").strip(),
        "access_key": str(settings.OBJECT_STORAGE_ACCESS_KEY or "").strip(),
        "secret_key": str(settings.OBJECT_STORAGE_SECRET_KEY or "").strip(),
        "bucket_name": str(settings.OBJECT_STORAGE_BUCKET_NAME or "").strip(),
        "documents_enabled": bool(settings.OBJECT_STORAGE_DOCUMENTS_ENABLED),
    }

    def validate_object_storage_profile(label: str, profile: Mapping[str, object]) -> None:
        enabled = bool(profile.get("enabled", False))
        documents_enabled = bool(profile.get("documents_enabled", False))
        if documents_enabled and not enabled:
            raise ValueError(f"{label}.documents_enabled requires {label}.enabled=true")
        if not enabled:
            return
        for field_name in ("endpoint", "access_key", "secret_key", "bucket_name"):
            if not str(profile.get(field_name) or "").strip():
                raise ValueError(f"{label}.{field_name} is required when {label}.enabled=true")

    validate_object_storage_profile("OBJECT_STORAGE", base_object_storage)
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
        for boolean_field in ("enabled", "use_ssl", "documents_enabled"):
            if boolean_field in raw_profile and not isinstance(raw_profile[boolean_field], bool):
                raise ValueError(
                    f"OBJECT_STORAGE_REGION_PROFILES[{region!r}].{boolean_field} must be a JSON boolean"
                )
        merged_profile = dict(base_object_storage)
        merged_profile.update(
            {
                key: value
                for key, value in raw_profile.items()
                if key in merged_profile and value not in (None, "")
            }
        )
        merged_profile["provider"] = normalize_object_storage_provider_name(
            raw_profile.get("provider") or object_storage_provider
        )
        validate_object_storage_profile(f"OBJECT_STORAGE_REGION_PROFILES[{region!r}]", merged_profile)

    if is_production and bool(getattr(settings, "FAISS_ALLOW_DANGEROUS_DESERIALIZATION", False)):
        raise ValueError("FAISS_ALLOW_DANGEROUS_DESERIALIZATION is not allowed in production")


def validate_chunk_llm_and_retrieval(settings):
    is_production = is_production_env()
    # Validate chunk settings
    if settings.CHUNK_OVERLAP >= settings.CHUNK_SIZE:
        raise ValueError(
            f"CHUNK_OVERLAP ({settings.CHUNK_OVERLAP}) must be less than "
            f"CHUNK_SIZE ({settings.CHUNK_SIZE})"
        )

    # Validate LLM temperature
    if not 0 <= settings.LLM_TEMPERATURE <= 2:
        raise ValueError(
            f"LLM_TEMPERATURE ({settings.LLM_TEMPERATURE}) must be between 0 and 2"
        )

    # Validate retrieval settings
    if settings.SIMILARITY_THRESHOLD < 0 or settings.SIMILARITY_THRESHOLD > 1:
        raise ValueError(
            f"SIMILARITY_THRESHOLD ({settings.SIMILARITY_THRESHOLD}) must be between 0 and 1"
        )

    if int(getattr(settings, "RETRIEVAL_TOP_K", 0) or 0) < 1:
        raise ValueError(f"RETRIEVAL_TOP_K ({getattr(settings, 'RETRIEVAL_TOP_K', None)}) must be >= 1")

    if settings.RETRIEVAL_MMR_LAMBDA < 0 or settings.RETRIEVAL_MMR_LAMBDA > 1:
        raise ValueError(
            f"RETRIEVAL_MMR_LAMBDA ({settings.RETRIEVAL_MMR_LAMBDA}) must be between 0 and 1"
        )
    if settings.RETRIEVAL_DEFAULT_ALPHA < 0 or settings.RETRIEVAL_DEFAULT_ALPHA > 1:
        raise ValueError(
            f"RETRIEVAL_DEFAULT_ALPHA ({settings.RETRIEVAL_DEFAULT_ALPHA}) must be between 0 and 1"
        )
    if int(getattr(settings, "RETRIEVAL_RRF_K", 0) or 0) < 1:
        raise ValueError(f"RETRIEVAL_RRF_K ({getattr(settings, 'RETRIEVAL_RRF_K', None)}) must be >= 1")
    dedup_thr = float(getattr(settings, "RETRIEVAL_DEDUP_JACCARD_THRESHOLD", 0.0) or 0.0)
    if dedup_thr < 0.0 or dedup_thr > 1.0:
        raise ValueError(f"RETRIEVAL_DEDUP_JACCARD_THRESHOLD ({dedup_thr}) must be between 0 and 1")
    if int(getattr(settings, "RETRIEVAL_DEDUP_MAX_COMPARE", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_DEDUP_MAX_COMPARE must be >= 0")
    if int(getattr(settings, "RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD must be >= 0")
    if int(getattr(settings, "RETRIEVAL_NEAR_DEDUP_MAX_COMPARE", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_NEAR_DEDUP_MAX_COMPARE must be >= 0")
    if int(getattr(settings, "RETRIEVAL_MAX_CHUNKS_PER_DOC", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_MAX_CHUNKS_PER_DOC must be >= 0")
    if int(getattr(settings, "RETRIEVAL_MAX_CHUNKS_PER_RECORD_IDENTITY", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_MAX_CHUNKS_PER_RECORD_IDENTITY must be >= 0")
    compact_min_top_score = float(getattr(settings, "RETRIEVAL_COMPACT_MIN_TOP_SCORE", 0.8) or 0.8)
    if compact_min_top_score < 0.0 or compact_min_top_score > 2.0:
        raise ValueError("RETRIEVAL_COMPACT_MIN_TOP_SCORE must be between 0 and 2")
    compact_relative_floor = float(getattr(settings, "RETRIEVAL_COMPACT_RELATIVE_SCORE_FLOOR", 0.65) or 0.65)
    if compact_relative_floor < 0.0 or compact_relative_floor > 1.0:
        raise ValueError("RETRIEVAL_COMPACT_RELATIVE_SCORE_FLOOR must be between 0 and 1")
    if int(getattr(settings, "RETRIEVAL_COMPACT_MIN_RECORDS", 1) or 1) < 1:
        raise ValueError("RETRIEVAL_COMPACT_MIN_RECORDS must be >= 1")
    if int(getattr(settings, "RETRIEVAL_MAX_CHUNKS_PER_PAGE", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_MAX_CHUNKS_PER_PAGE must be >= 0")
    if int(getattr(settings, "RETRIEVAL_MIN_DISTINCT_DOCS", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_MIN_DISTINCT_DOCS must be >= 0")
    field_title_boost = float(getattr(settings, "RETRIEVAL_FIELD_AWARE_TITLE_BOOST", 0.0) or 0.0)
    field_heading_boost = float(getattr(settings, "RETRIEVAL_FIELD_AWARE_HEADING_BOOST", 0.0) or 0.0)
    field_max_boost = float(getattr(settings, "RETRIEVAL_FIELD_AWARE_MAX_BOOST", 0.0) or 0.0)
    if field_title_boost < 0.0:
        raise ValueError("RETRIEVAL_FIELD_AWARE_TITLE_BOOST must be >= 0")
    if field_heading_boost < 0.0:
        raise ValueError("RETRIEVAL_FIELD_AWARE_HEADING_BOOST must be >= 0")
    if field_max_boost < 0.0:
        raise ValueError("RETRIEVAL_FIELD_AWARE_MAX_BOOST must be >= 0")
    if field_title_boost > field_max_boost:
        raise ValueError("RETRIEVAL_FIELD_AWARE_TITLE_BOOST must be <= RETRIEVAL_FIELD_AWARE_MAX_BOOST")
    if field_heading_boost > field_max_boost:
        raise ValueError("RETRIEVAL_FIELD_AWARE_HEADING_BOOST must be <= RETRIEVAL_FIELD_AWARE_MAX_BOOST")
    chunk_type_match_boost = float(getattr(settings, "RETRIEVAL_CHUNK_TYPE_MATCH_BOOST", 0.0) or 0.0)
    if chunk_type_match_boost < 0.0:
        raise ValueError("RETRIEVAL_CHUNK_TYPE_MATCH_BOOST must be >= 0")
    if int(settings.RETRIEVAL_QUERY_PARALLELISM or 0) < 1:
        raise ValueError(
            f"RETRIEVAL_QUERY_PARALLELISM ({settings.RETRIEVAL_QUERY_PARALLELISM}) must be >= 1"
        )
    if int(getattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 1) or 1) < 1:
        raise ValueError("RETRIEVAL_OVERFETCH_MULTIPLIER must be >= 1")
    hierarchy_family_aggregation = str(
        getattr(settings, "HIERARCHY_RECALL_FAMILY_AGGREGATION", "combined") or "combined"
    ).strip().lower()
    valid_hierarchy_family_aggregation = {"frequency", "score", "combined"}
    if hierarchy_family_aggregation not in valid_hierarchy_family_aggregation:
        raise ValueError(
            "HIERARCHY_RECALL_FAMILY_AGGREGATION must be one of: "
            + ", ".join(sorted(valid_hierarchy_family_aggregation))
        )
    if settings.HIERARCHY_RECALL_FAMILY_AGGREGATION != hierarchy_family_aggregation:
        settings.HIERARCHY_RECALL_FAMILY_AGGREGATION = hierarchy_family_aggregation
    hierarchy_parent_depth = int(getattr(settings, "HIERARCHY_RECALL_PARENT_DEPTH", 0) or 0)
    if hierarchy_parent_depth < 0 or hierarchy_parent_depth > 8:
        raise ValueError("HIERARCHY_RECALL_PARENT_DEPTH must be between 0 and 8")
    hierarchy_sibling_window = int(getattr(settings, "HIERARCHY_RECALL_SIBLING_WINDOW", 0) or 0)
    if hierarchy_sibling_window < 0 or hierarchy_sibling_window > 16:
        raise ValueError("HIERARCHY_RECALL_SIBLING_WINDOW must be between 0 and 16")
    hierarchy_overfetch_factor = int(getattr(settings, "HIERARCHY_RECALL_OVERFETCH_FACTOR", 4) or 0)
    if hierarchy_overfetch_factor < 1 or hierarchy_overfetch_factor > 32:
        raise ValueError("HIERARCHY_RECALL_OVERFETCH_FACTOR must be between 1 and 32")
    if int(getattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_OVERFETCH_MAX_K must be >= 0")
    auth_boost = float(getattr(settings, "RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX", 0.0) or 0.0)
    if auth_boost < 0.0 or auth_boost > 1.0:
        raise ValueError("RETRIEVAL_GOVERNANCE_AUTHORITY_BOOST_MAX must be between 0 and 1")
    latest_boost = float(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX", 0.0) or 0.0)
    if latest_boost < 0.0 or latest_boost > 1.0:
        raise ValueError("RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX must be between 0 and 1")
    if int(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS", 0) or 0) < 1:
        raise ValueError("RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS must be >= 1")
    if int(getattr(settings, "MILVUS_EXPR_MAX_DOC_IDS", 0) or 0) < 0:
        raise ValueError("MILVUS_EXPR_MAX_DOC_IDS must be >= 0")

    if int(getattr(settings, "BM25_CACHE_MAX_TENANTS", 0) or 0) < 0:
        raise ValueError("BM25_CACHE_MAX_TENANTS must be >= 0")
    if int(getattr(settings, "BM25_EAGER_UPSERT_MAX_CHUNKS", 0) or 0) < 0:
        raise ValueError("BM25_EAGER_UPSERT_MAX_CHUNKS must be >= 0")
    if int(getattr(settings, "RETRIEVAL_REBUILD_MAX_CHUNKS", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_REBUILD_MAX_CHUNKS must be >= 0")
    if is_production and int(getattr(settings, "RETRIEVAL_REBUILD_MAX_CHUNKS", 0) or 0) <= 0:
        raise ValueError("RETRIEVAL_REBUILD_MAX_CHUNKS must be > 0 in production")
    if int(getattr(settings, "BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS", 0) or 0) < 2:
        raise ValueError("BM25_TOKENIZE_CJK_OOV_MAX_TERM_CHARS must be >= 2")
    if int(getattr(settings, "BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS", 0) or 0) < 0:
        raise ValueError("BM25_TOKENIZE_CJK_OOV_MAX_EXTRA_TOKENS must be >= 0")


def validate_embedding_and_migration(settings):
    if int(getattr(settings, "EMBEDDING_CACHE_TTL_SEC", 0) or 0) < 0:
        raise ValueError("EMBEDDING_CACHE_TTL_SEC must be >= 0")

    emb_prefix = (getattr(settings, "EMBEDDING_CACHE_PREFIX", "") or "").strip()
    if not emb_prefix:
        raise ValueError("EMBEDDING_CACHE_PREFIX must be non-empty")
    if any(ch.isspace() for ch in emb_prefix):
        raise ValueError("EMBEDDING_CACHE_PREFIX must not contain whitespace")
    if settings.EMBEDDING_CACHE_PREFIX != emb_prefix:
        settings.EMBEDDING_CACHE_PREFIX = emb_prefix

    if float(getattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 0.0) or 0.0) <= 0:
        raise ValueError("EMBEDDING_API_TIMEOUT_SEC must be > 0")
    if int(getattr(settings, "EMBEDDING_API_BATCH_SIZE", 0) or 0) < 1:
        raise ValueError("EMBEDDING_API_BATCH_SIZE must be >= 1")
    if int(getattr(settings, "EMBEDDING_API_MAX_CONCURRENCY", 0) or 0) < 1:
        raise ValueError("EMBEDDING_API_MAX_CONCURRENCY must be >= 1")
    if int(getattr(settings, "EMBEDDING_API_MAX_RETRIES", 0) or 0) < 0:
        raise ValueError("EMBEDDING_API_MAX_RETRIES must be >= 0")
    if float(getattr(settings, "EMBEDDING_API_RETRY_BACKOFF_SEC", 0.0) or 0.0) < 0:
        raise ValueError("EMBEDDING_API_RETRY_BACKOFF_SEC must be >= 0")
    if float(getattr(settings, "EMBEDDING_API_RETRY_JITTER_SEC", 0.0) or 0.0) < 0:
        raise ValueError("EMBEDDING_API_RETRY_JITTER_SEC must be >= 0")

    # Gap5: embedding blue-green migration / dual-write config validation.
    shadow_enabled = bool(getattr(settings, "EMBEDDING_SHADOW_ENABLED", False))
    if shadow_enabled:
        if str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus").strip().lower() != "milvus":
            raise ValueError("EMBEDDING_SHADOW_ENABLED requires VECTOR_BACKEND=milvus")

        shadow_model = str(getattr(settings, "EMBEDDING_SHADOW_MODEL", "") or "").strip()
        if not shadow_model:
            raise ValueError("EMBEDDING_SHADOW_MODEL must be non-empty when EMBEDDING_SHADOW_ENABLED=true")
        if settings.EMBEDDING_SHADOW_MODEL != shadow_model:
            settings.EMBEDDING_SHADOW_MODEL = shadow_model

        shadow_collection = str(getattr(settings, "MILVUS_SHADOW_COLLECTION_NAME", "") or "").strip()
        if not shadow_collection:
            raise ValueError(
                "MILVUS_SHADOW_COLLECTION_NAME must be non-empty when EMBEDDING_SHADOW_ENABLED=true"
            )
        if any(ch.isspace() for ch in shadow_collection):
            raise ValueError("MILVUS_SHADOW_COLLECTION_NAME must not contain whitespace")
        primary_collection = str(getattr(settings, "MILVUS_COLLECTION_NAME", "") or "").strip()
        if primary_collection and primary_collection == shadow_collection:
            raise ValueError("MILVUS_SHADOW_COLLECTION_NAME must differ from MILVUS_COLLECTION_NAME")
        if settings.MILVUS_SHADOW_COLLECTION_NAME != shadow_collection:
            settings.MILVUS_SHADOW_COLLECTION_NAME = shadow_collection

        shadow_provider = str(getattr(settings, "EMBEDDING_SHADOW_PROVIDER", "") or "").strip()
        if shadow_provider and any(ch.isspace() for ch in shadow_provider):
            raise ValueError("EMBEDDING_SHADOW_PROVIDER must not contain whitespace")
        if settings.EMBEDDING_SHADOW_PROVIDER != shadow_provider:
            settings.EMBEDDING_SHADOW_PROVIDER = shadow_provider

        shadow_api_base = str(getattr(settings, "EMBEDDING_SHADOW_API_BASE", "") or "").strip()
        if shadow_api_base and any(ch.isspace() for ch in shadow_api_base):
            raise ValueError("EMBEDDING_SHADOW_API_BASE must not contain whitespace")
        if settings.EMBEDDING_SHADOW_API_BASE != shadow_api_base:
            settings.EMBEDDING_SHADOW_API_BASE = shadow_api_base

        shadow_api_key = str(getattr(settings, "EMBEDDING_SHADOW_API_KEY", "") or "").strip()
        if settings.EMBEDDING_SHADOW_API_KEY != shadow_api_key:
            settings.EMBEDDING_SHADOW_API_KEY = shadow_api_key

    prog_prefix = (getattr(settings, "EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX", "") or "").strip()
    if not prog_prefix:
        raise ValueError("EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX must be non-empty")
    if any(ch.isspace() for ch in prog_prefix):
        raise ValueError("EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX must not contain whitespace")
    if settings.EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX != prog_prefix:
        settings.EMBEDDING_MIGRATION_PROGRESS_REDIS_PREFIX = prog_prefix
    if int(getattr(settings, "EMBEDDING_MIGRATION_PROGRESS_TTL_SEC", 0) or 0) < 0:
        raise ValueError("EMBEDDING_MIGRATION_PROGRESS_TTL_SEC must be >= 0")


def validate_chat_and_retrieval_caches(settings):
    if int(getattr(settings, "CHAT_RESPONSE_CACHE_TTL_SEC", 0) or 0) < 0:
        raise ValueError("CHAT_RESPONSE_CACHE_TTL_SEC must be >= 0")
    if int(getattr(settings, "CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES", 0) or 0) < 0:
        raise ValueError("CHAT_RESPONSE_CACHE_MAX_VALUE_BYTES must be >= 0")
    if float(getattr(settings, "CHAT_RESPONSE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC", 0.0) or 0.0) <= 0.0:
        raise ValueError("CHAT_RESPONSE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC must be > 0")

    if int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_CANDIDATE_CACHE_TTL_SEC must be >= 0")
    if float(getattr(settings, "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC", 0.0) or 0.0) <= 0.0:
        raise ValueError("RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC must be > 0")
    if int(getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_CANDIDATE_CACHE_MAX_VALUE_BYTES must be >= 0")

    cand_prefix = (getattr(settings, "RETRIEVAL_CANDIDATE_CACHE_PREFIX", "") or "").strip()
    if not cand_prefix:
        raise ValueError("RETRIEVAL_CANDIDATE_CACHE_PREFIX must be non-empty")
    if any(ch.isspace() for ch in cand_prefix):
        raise ValueError("RETRIEVAL_CANDIDATE_CACHE_PREFIX must not contain whitespace")
    if settings.RETRIEVAL_CANDIDATE_CACHE_PREFIX != cand_prefix:
        settings.RETRIEVAL_CANDIDATE_CACHE_PREFIX = cand_prefix

    if int(getattr(settings, "SEMANTIC_CACHE_TTL_SEC", 0) or 0) < 0:
        raise ValueError("SEMANTIC_CACHE_TTL_SEC must be >= 0")
    if int(getattr(settings, "SEMANTIC_CACHE_MAX_VALUE_BYTES", 0) or 0) < 0:
        raise ValueError("SEMANTIC_CACHE_MAX_VALUE_BYTES must be >= 0")
    sem_threshold = float(getattr(settings, "SEMANTIC_CACHE_SCORE_THRESHOLD", 0.0) or 0.0)
    if sem_threshold < 0.0 or sem_threshold > 1.0:
        raise ValueError("SEMANTIC_CACHE_SCORE_THRESHOLD must be between 0 and 1")
    if float(getattr(settings, "DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC", 0.0) or 0.0) <= 0.0:
        raise ValueError("DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC must be > 0")
    if int(getattr(settings, "RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY", 0) or 0) < 0:
        raise ValueError("RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY must be >= 0")
    if settings.SEMANTIC_CACHE_SCORE_THRESHOLD != sem_threshold:
        settings.SEMANTIC_CACHE_SCORE_THRESHOLD = sem_threshold
    if int(getattr(settings, "SEMANTIC_CACHE_SEARCH_TOP_K", 0) or 0) < 1:
        raise ValueError("SEMANTIC_CACHE_SEARCH_TOP_K must be >= 1")

    sem_prefix = (getattr(settings, "SEMANTIC_CACHE_REDIS_PREFIX", "") or "").strip()
    if not sem_prefix:
        raise ValueError("SEMANTIC_CACHE_REDIS_PREFIX must be non-empty")
    if any(ch.isspace() for ch in sem_prefix):
        raise ValueError("SEMANTIC_CACHE_REDIS_PREFIX must not contain whitespace")
    if settings.SEMANTIC_CACHE_REDIS_PREFIX != sem_prefix:
        settings.SEMANTIC_CACHE_REDIS_PREFIX = sem_prefix

    sem_collection = (getattr(settings, "SEMANTIC_CACHE_COLLECTION_NAME", "") or "").strip()
    if not sem_collection:
        raise ValueError("SEMANTIC_CACHE_COLLECTION_NAME must be non-empty")
    if any(ch.isspace() for ch in sem_collection):
        raise ValueError("SEMANTIC_CACHE_COLLECTION_NAME must not contain whitespace")
    if settings.SEMANTIC_CACHE_COLLECTION_NAME != sem_collection:
        settings.SEMANTIC_CACHE_COLLECTION_NAME = sem_collection

    if int(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_TTL_SEC", 0) or 0) < 0:
        raise ValueError("EVIDENCE_POST_RERANK_CACHE_TTL_SEC must be >= 0")
    if int(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES", 0) or 0) < 0:
        raise ValueError("EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES must be >= 0")
    post_rerank_score_calibration_alpha = float(
        getattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA", 0.0) or 0.0
    )
    if post_rerank_score_calibration_alpha < 0.0 or post_rerank_score_calibration_alpha > 1.0:
        raise ValueError("EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA must be between 0 and 1")
    post_rerank_cache_backend = (
        str(getattr(settings, "EVIDENCE_POST_RERANK_CACHE_BACKEND", "memory") or "memory").strip().lower()
    )
    if post_rerank_cache_backend not in {"memory", "redis"}:
        raise ValueError("EVIDENCE_POST_RERANK_CACHE_BACKEND must be one of: memory, redis")
    if settings.EVIDENCE_POST_RERANK_CACHE_BACKEND != post_rerank_cache_backend:
        settings.EVIDENCE_POST_RERANK_CACHE_BACKEND = post_rerank_cache_backend
    post_rerank_cache_prefix = (getattr(settings, "EVIDENCE_POST_RERANK_CACHE_PREFIX", "") or "").strip()
    if not post_rerank_cache_prefix:
        raise ValueError("EVIDENCE_POST_RERANK_CACHE_PREFIX must be non-empty")
    if any(ch.isspace() for ch in post_rerank_cache_prefix):
        raise ValueError("EVIDENCE_POST_RERANK_CACHE_PREFIX must not contain whitespace")
    if settings.EVIDENCE_POST_RERANK_CACHE_PREFIX != post_rerank_cache_prefix:
        settings.EVIDENCE_POST_RERANK_CACHE_PREFIX = post_rerank_cache_prefix

    if int(getattr(settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 0) or 0) < 0:
        raise ValueError("RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY must be >= 0")
    if float(getattr(settings, "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC", 0.0) or 0.0) < 0.0:
        raise ValueError("RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC must be >= 0")
    if int(getattr(settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY", 0) or 0) < 0:
        raise ValueError("RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY must be >= 0")
    adm_prefix = (getattr(settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX", "") or "").strip()
    if not adm_prefix:
        raise ValueError("RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX must be non-empty")
    if any(ch.isspace() for ch in adm_prefix):
        raise ValueError("RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX must not contain whitespace")
    if settings.RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX != adm_prefix:
        settings.RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX = adm_prefix
    if int(getattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 0) or 0) < 0:
        raise ValueError("RAG_KG_CHUNK_INJECTION_MAX_CHUNKS must be >= 0")
    kg_chunk_boost_weight = float(getattr(settings, "RAG_KG_CHUNK_BOOST_WEIGHT", 0.15) or 0.0)
    if kg_chunk_boost_weight < 0.0 or kg_chunk_boost_weight > 1.0:
        raise ValueError("RAG_KG_CHUNK_BOOST_WEIGHT must be between 0 and 1")
    if settings.RAG_KG_CHUNK_BOOST_WEIGHT != kg_chunk_boost_weight:
        settings.RAG_KG_CHUNK_BOOST_WEIGHT = kg_chunk_boost_weight
    if int(getattr(settings, "RAG_KG_CHUNK_BOOST_MAX_PROMOTED", 0) or 0) < 0:
        raise ValueError("RAG_KG_CHUNK_BOOST_MAX_PROMOTED must be >= 0")


def validate_kg_search(settings):
    if int(getattr(settings, "KG_SEARCH_CACHE_TTL_SEC", 0) or 0) < 0:
        raise ValueError("KG_SEARCH_CACHE_TTL_SEC must be >= 0")
    if int(getattr(settings, "KG_SEARCH_CACHE_MAX_ENTRIES", 0) or 0) < 0:
        raise ValueError("KG_SEARCH_CACHE_MAX_ENTRIES must be >= 0")
    kg_dataset_scope_max_enum_docs = int(getattr(settings, "KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS", 0) or 0)
    if kg_dataset_scope_max_enum_docs < 1 or kg_dataset_scope_max_enum_docs > 10_000:
        raise ValueError("KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS must be between 1 and 10000")
    kg_expand_budget_sec = float(getattr(settings, "KG_SEARCH_EXPAND_BUDGET_SEC", 0.0) or 0.0)
    if kg_expand_budget_sec < 0.0:
        raise ValueError("KG_SEARCH_EXPAND_BUDGET_SEC must be >= 0")
    if settings.KG_SEARCH_EXPAND_BUDGET_SEC != kg_expand_budget_sec:
        settings.KG_SEARCH_EXPAND_BUDGET_SEC = kg_expand_budget_sec
    if int(getattr(settings, "KG_SEARCH_LATENCY_SLO_MS", 0) or 0) < 0:
        raise ValueError("KG_SEARCH_LATENCY_SLO_MS must be >= 0")
    kg_quality_low = float(getattr(settings, "KG_QUALITY_LOW_CONFIDENCE_THRESHOLD", 0.30) or 0.30)
    if not (0.0 <= kg_quality_low <= 1.0):
        raise ValueError("KG_QUALITY_LOW_CONFIDENCE_THRESHOLD must be between 0 and 1")
    if settings.KG_QUALITY_LOW_CONFIDENCE_THRESHOLD != kg_quality_low:
        settings.KG_QUALITY_LOW_CONFIDENCE_THRESHOLD = kg_quality_low
    if int(getattr(settings, "KG_QUALITY_RELATION_EDGES_LIMIT", 0) or 0) < 0:
        raise ValueError("KG_QUALITY_RELATION_EDGES_LIMIT must be >= 0")
    kg_query_mode_default = str(getattr(settings, "KG_SEARCH_QUERY_MODE_DEFAULT", "auto") or "auto").strip().lower()
    if kg_query_mode_default not in {"auto", "local", "global", "drift"}:
        raise ValueError("KG_SEARCH_QUERY_MODE_DEFAULT must be one of: auto, local, global, drift")
    if settings.KG_SEARCH_QUERY_MODE_DEFAULT != kg_query_mode_default:
        settings.KG_SEARCH_QUERY_MODE_DEFAULT = kg_query_mode_default
    if int(getattr(settings, "KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS", 0) or 0) < 1:
        raise ValueError("KG_SEARCH_QUERY_MODE_LOCAL_MAX_EVENTS must be >= 1")
    if int(getattr(settings, "KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS", 0) or 0) < 1:
        raise ValueError("KG_SEARCH_QUERY_MODE_GLOBAL_MIN_EVENTS must be >= 1")
    if int(getattr(settings, "KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS", 0) or 0) < 1:
        raise ValueError("KG_SEARCH_QUERY_MODE_LOW_CONFIDENCE_GLOBAL_MAX_EVENTS must be >= 1")
    if int(getattr(settings, "KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS", 0) or 0) < 1:
        raise ValueError("KG_SEARCH_QUERY_MODE_DRIFT_MIN_EVENTS must be >= 1")
    local_entity_weight_bonus = float(getattr(settings, "KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS", 0.05) or 0.05)
    if not (0.0 <= local_entity_weight_bonus <= 1.0):
        raise ValueError("KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS must be between 0 and 1")
    if settings.KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS != local_entity_weight_bonus:
        settings.KG_SEARCH_QUERY_MODE_LOCAL_ENTITY_WEIGHT_BONUS = local_entity_weight_bonus
    if int(getattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK", 0) or 0) < 0:
        raise ValueError("KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK must be >= 0")
    if int(getattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT", 0) or 0) < 0:
        raise ValueError("KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT must be >= 0")
    if int(getattr(settings, "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT", 0) or 0) < 0:
        raise ValueError("KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT must be >= 0")
    if str(getattr(settings, "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY", "uniform") or "uniform").strip().lower() not in {"head", "uniform"}:
        raise ValueError("KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY must be one of: head, uniform")
    if int(getattr(settings, "KG_EXTRACT_LONG_DOC_MIN_CHUNKS", 0) or 0) < 0:
        raise ValueError("KG_EXTRACT_LONG_DOC_MIN_CHUNKS must be >= 0")
    kg_serving_min_score = float(getattr(settings, "KG_SEARCH_SERVING_MIN_SCORE", 0.0) or 0.0)
    if not (0.0 <= kg_serving_min_score <= 1.0):
        raise ValueError("KG_SEARCH_SERVING_MIN_SCORE must be between 0 and 1")
    if settings.KG_SEARCH_SERVING_MIN_SCORE != kg_serving_min_score:
        settings.KG_SEARCH_SERVING_MIN_SCORE = kg_serving_min_score
    if int(getattr(settings, "KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER", 0) or 0) < 1:
        raise ValueError("KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER must be >= 1")


def validate_vector_write_and_table_catalog(settings):
    if int(getattr(settings, "VECTOR_WRITE_BATCH_SIZE", 0) or 0) < 1:
        raise ValueError("VECTOR_WRITE_BATCH_SIZE must be >= 1")
    if int(getattr(settings, "VECTOR_WRITE_BATCH_MAX_CHARS", 0) or 0) < 0:
        raise ValueError("VECTOR_WRITE_BATCH_MAX_CHARS must be >= 0")

    if int(getattr(settings, "DB_CATALOG_ROW_SYNC_MAX_TABLES", 0) or 0) < 1:
        raise ValueError("DB_CATALOG_ROW_SYNC_MAX_TABLES must be >= 1")
    if int(getattr(settings, "DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE", 0) or 0) < 1:
        raise ValueError("DB_CATALOG_ROW_SYNC_MAX_ROWS_PER_TABLE must be >= 1")
    if int(getattr(settings, "DB_CATALOG_ROW_SYNC_MAX_COLS", 0) or 0) < 1:
        raise ValueError("DB_CATALOG_ROW_SYNC_MAX_COLS must be >= 1")
    if int(getattr(settings, "TABLE_QUERY_MAX_JOIN_TABLES", 0) or 0) < 1:
        raise ValueError("TABLE_QUERY_MAX_JOIN_TABLES must be >= 1")
    if int(getattr(settings, "TABLE_TAG_PLAN_CANDIDATES_TOP_N", 0) or 0) < 1:
        raise ValueError("TABLE_TAG_PLAN_CANDIDATES_TOP_N must be >= 1")
    tag_ambiguity_gap = float(getattr(settings, "TABLE_TAG_AMBIGUITY_SCORE_GAP", 0.03) or 0.03)
    if not (0.0 <= tag_ambiguity_gap <= 1.0):
        raise ValueError("TABLE_TAG_AMBIGUITY_SCORE_GAP must be between 0 and 1")
    if settings.TABLE_TAG_AMBIGUITY_SCORE_GAP != tag_ambiguity_gap:
        settings.TABLE_TAG_AMBIGUITY_SCORE_GAP = tag_ambiguity_gap
    tag_cost_fanout_weight = float(getattr(settings, "TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT", 0.08) or 0.08)
    if not (0.0 <= tag_cost_fanout_weight <= 1.0):
        raise ValueError("TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT must be between 0 and 1")
    if settings.TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT != tag_cost_fanout_weight:
        settings.TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT = tag_cost_fanout_weight
    tag_cost_selectivity_weight = float(
        getattr(settings, "TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT", 0.12) or 0.12
    )
    if not (0.0 <= tag_cost_selectivity_weight <= 1.0):
        raise ValueError("TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT must be between 0 and 1")
    if settings.TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT != tag_cost_selectivity_weight:
        settings.TABLE_TAG_COST_SELECTIVITY_PENALTY_WEIGHT = tag_cost_selectivity_weight
    tag_fanout_ratio_alert = float(getattr(settings, "TABLE_TAG_COST_FANOUT_RATIO_ALERT", 20.0) or 20.0)
    if tag_fanout_ratio_alert < 1.0:
        raise ValueError("TABLE_TAG_COST_FANOUT_RATIO_ALERT must be >= 1")
    if settings.TABLE_TAG_COST_FANOUT_RATIO_ALERT != tag_fanout_ratio_alert:
        settings.TABLE_TAG_COST_FANOUT_RATIO_ALERT = tag_fanout_ratio_alert
    tag_selectivity_min = float(getattr(settings, "TABLE_TAG_COST_SELECTIVITY_MIN", 0.2) or 0.2)
    if not (0.0 <= tag_selectivity_min <= 1.0):
        raise ValueError("TABLE_TAG_COST_SELECTIVITY_MIN must be between 0 and 1")
    if settings.TABLE_TAG_COST_SELECTIVITY_MIN != tag_selectivity_min:
        settings.TABLE_TAG_COST_SELECTIVITY_MIN = tag_selectivity_min
    tag_low_conf = float(getattr(settings, "TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD", 0.55) or 0.55)
    if not (0.0 <= tag_low_conf <= 1.0):
        raise ValueError("TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD must be between 0 and 1")
    if settings.TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD != tag_low_conf:
        settings.TABLE_TAG_PLAN_LOW_CONFIDENCE_THRESHOLD = tag_low_conf
    if int(getattr(settings, "RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX", 0) or 0) < 1:
        raise ValueError("RETRIEVAL_MUST_RECALL_AUTO_EXPECTED_SOURCE_KEYS_MAX must be >= 1")


def validate_evidence_governance_and_quotas(settings):
    signing_key_id = str(getattr(settings, "EVIDENCE_CAPSULE_SIGNING_KEY_ID", "default") or "default").strip()
    if not signing_key_id:
        raise ValueError("EVIDENCE_CAPSULE_SIGNING_KEY_ID must be non-empty")
    if any(ch.isspace() for ch in signing_key_id):
        raise ValueError("EVIDENCE_CAPSULE_SIGNING_KEY_ID must not contain whitespace")
    if settings.EVIDENCE_CAPSULE_SIGNING_KEY_ID != signing_key_id:
        settings.EVIDENCE_CAPSULE_SIGNING_KEY_ID = signing_key_id

    if bool(getattr(settings, "EVIDENCE_CAPSULE_SIGNING_ENABLED", False)):
        signing_secret = str(getattr(settings, "EVIDENCE_CAPSULE_SIGNING_SECRET", "") or "").strip()
        if not signing_secret:
            raise ValueError("EVIDENCE_CAPSULE_SIGNING_SECRET must be non-empty when signing is enabled")

    index_strictness = str(getattr(settings, "INDEX_CONSISTENCY_STRICTNESS", "off") or "off").strip().lower()
    valid_index_strictness = {"off", "warn", "strict"}
    if index_strictness not in valid_index_strictness:
        raise ValueError(
            "INDEX_CONSISTENCY_STRICTNESS must be one of: "
            + ", ".join(sorted(valid_index_strictness))
        )
    if settings.INDEX_CONSISTENCY_STRICTNESS != index_strictness:
        settings.INDEX_CONSISTENCY_STRICTNESS = index_strictness

    if int(getattr(settings, "CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT", 0) or 0) < 0:
        raise ValueError("CHAT_ASSISTANT_TOKEN_QUOTA_LIMIT must be >= 0")
    if int(getattr(settings, "CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS", 0) or 0) <= 0:
        raise ValueError("CHAT_ASSISTANT_TOKEN_QUOTA_WINDOW_HOURS must be > 0")
    quota_mode = str(getattr(settings, "CHAT_ASSISTANT_TOKEN_QUOTA_MODE", "block") or "block").lower()
    if quota_mode not in {"block", "warn"}:
        raise ValueError("CHAT_ASSISTANT_TOKEN_QUOTA_MODE must be one of: block, warn")
    if settings.CHAT_ASSISTANT_TOKEN_QUOTA_MODE != quota_mode:
        settings.CHAT_ASSISTANT_TOKEN_QUOTA_MODE = quota_mode

    if int(getattr(settings, "TENANT_DOC_QUOTA_LIMIT", 0) or 0) < 0:
        raise ValueError("TENANT_DOC_QUOTA_LIMIT must be >= 0")
    if int(getattr(settings, "TENANT_STORAGE_QUOTA_LIMIT_BYTES", 0) or 0) < 0:
        raise ValueError("TENANT_STORAGE_QUOTA_LIMIT_BYTES must be >= 0")
    if int(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_LIMIT", 0) or 0) < 0:
        raise ValueError("TENANT_EMBED_CHAR_QUOTA_LIMIT must be >= 0")
    if int(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS", 0) or 0) <= 0:
        raise ValueError("TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS must be > 0")
    embed_quota_mode = str(getattr(settings, "TENANT_EMBED_CHAR_QUOTA_MODE", "block") or "block").lower()
    if embed_quota_mode not in {"block", "warn"}:
        raise ValueError("TENANT_EMBED_CHAR_QUOTA_MODE must be one of: block, warn")
    if settings.TENANT_EMBED_CHAR_QUOTA_MODE != embed_quota_mode:
        settings.TENANT_EMBED_CHAR_QUOTA_MODE = embed_quota_mode

    if int(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES", 0) or 0) <= 0:
        raise ValueError("PERSISTENT_SUMMARY_MEMORY_LOOKBACK_MESSAGES must be > 0")
    if int(getattr(settings, "PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS", 0) or 0) <= 0:
        raise ValueError("PERSISTENT_SUMMARY_MEMORY_MAX_SUMMARY_TOKENS must be > 0")


def validate_workflow_and_retrieval_profiles(settings):
    # Validate workflow mode
    valid_workflow_modes = {"chain", "routing", "parallel", "react", "planner", "evaluator"}
    if settings.WORKFLOW_MODE not in valid_workflow_modes:
        raise ValueError(
            f"WORKFLOW_MODE ({settings.WORKFLOW_MODE}) must be one of {valid_workflow_modes}"
        )

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
    chat_default_profile = str(getattr(settings, "CHAT_DEFAULT_RETRIEVAL_PROFILE", "") or "").strip().lower()
    if chat_default_profile not in valid_retrieval_profiles:
        raise ValueError(
            "CHAT_DEFAULT_RETRIEVAL_PROFILE must be one of: "
            + ", ".join(sorted(valid_retrieval_profiles))
        )
    if settings.CHAT_DEFAULT_RETRIEVAL_PROFILE != chat_default_profile:
        settings.CHAT_DEFAULT_RETRIEVAL_PROFILE = chat_default_profile

    retrieval_contract_mode = normalize_retrieval_contract_mode(
        str(getattr(settings, "RETRIEVAL_CONTRACT_MODE", "") or "")
    )
    if retrieval_contract_mode not in VALID_RETRIEVAL_CONTRACT_MODES:
        raise ValueError(
            "RETRIEVAL_CONTRACT_MODE must be one of: "
            + ", ".join(sorted(VALID_RETRIEVAL_CONTRACT_MODES))
        )
    if settings.RETRIEVAL_CONTRACT_MODE != retrieval_contract_mode:
        settings.RETRIEVAL_CONTRACT_MODE = retrieval_contract_mode


def validate_claim_verifier(settings):
    claim_verifier_mode = str(getattr(settings, "RAG_CLAIM_VERIFIER_MODE", "token_overlap") or "token_overlap").strip().lower()
    valid_claim_verifier_modes = {"token_overlap", "semantic_heuristic", "strict"}
    if claim_verifier_mode not in valid_claim_verifier_modes:
        raise ValueError(
            "RAG_CLAIM_VERIFIER_MODE must be one of: "
            + ", ".join(sorted(valid_claim_verifier_modes))
        )
    if settings.RAG_CLAIM_VERIFIER_MODE != claim_verifier_mode:
        settings.RAG_CLAIM_VERIFIER_MODE = claim_verifier_mode

    claim_nli_provider = str(
        getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"
    ).strip().lower()
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
            "RAG_CLAIM_NLI_VERIFIER_PROVIDER must be one of: "
            + ", ".join(sorted(valid_claim_nli_providers))
        )
    if settings.RAG_CLAIM_NLI_VERIFIER_PROVIDER != claim_nli_provider:
        settings.RAG_CLAIM_NLI_VERIFIER_PROVIDER = claim_nli_provider
    if int(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", 0) or 0) < 1:
        raise ValueError("RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC must be >= 1")
    if bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)) and claim_nli_provider == "openai_compatible":
        claim_nli_model = str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or "").strip()
        if not claim_nli_model:
            raise ValueError("RAG_CLAIM_NLI_VERIFIER_MODEL is required when NLI verifier is enabled")
        if settings.RAG_CLAIM_NLI_VERIFIER_MODEL != claim_nli_model:
            settings.RAG_CLAIM_NLI_VERIFIER_MODEL = claim_nli_model


def validate_retrieval_fallback_modes(settings):
    valid_retrieval_modes = {"hybrid", "vector", "keyword", "mmr"}
    fallback_mode = str(getattr(settings, "RETRIEVAL_HARD_FALLBACK_MODE", "keyword") or "keyword").strip().lower()
    if fallback_mode not in valid_retrieval_modes:
        raise ValueError(
            f"RETRIEVAL_HARD_FALLBACK_MODE ({fallback_mode}) must be one of {valid_retrieval_modes}"
        )
    if settings.RETRIEVAL_HARD_FALLBACK_MODE != fallback_mode:
        settings.RETRIEVAL_HARD_FALLBACK_MODE = fallback_mode
    if int(getattr(settings, "RETRIEVAL_HARD_FALLBACK_TOP_K", 0) or 0) < 1:
        raise ValueError("RETRIEVAL_HARD_FALLBACK_TOP_K must be >= 1")

    must_recall_second_pass_mode = str(
        getattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE", "keyword") or "keyword"
    ).strip().lower()
    if must_recall_second_pass_mode not in valid_retrieval_modes:
        raise ValueError(
            "RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE "
            f"({must_recall_second_pass_mode}) must be one of {valid_retrieval_modes}"
        )
    if settings.RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE != must_recall_second_pass_mode:
        settings.RETRIEVAL_MUST_RECALL_SECOND_PASS_MODE = must_recall_second_pass_mode
    if int(getattr(settings, "RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K", 0) or 0) < 1:
        raise ValueError("RETRIEVAL_MUST_RECALL_SECOND_PASS_TOP_K must be >= 1")
    contextual_followup_mode = str(
        getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE", "keyword") or "keyword"
    ).strip().lower()
    if contextual_followup_mode not in valid_retrieval_modes:
        raise ValueError(
            "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE "
            f"({contextual_followup_mode}) must be one of {valid_retrieval_modes}"
        )
    if settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE != contextual_followup_mode:
        settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_MODE = contextual_followup_mode
    if int(getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K", 0) or 0) < 1:
        raise ValueError("RETRIEVAL_CONTEXTUAL_FOLLOWUP_TOP_K must be >= 1")
    if int(getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS", 0) or 0) < 1:
        raise ValueError("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_DOCS must be >= 1")
    if int(getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS", 0) or 0) < 0:
        raise ValueError("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_TERMS must be >= 0")
    if int(getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS", 0) or 0) < 2:
        raise ValueError("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MIN_TERM_CHARS must be >= 2")
    if int(getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS", 0) or 0) < 32:
        raise ValueError("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_QUERY_CHARS must be >= 32")
    if int(getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS", 0) or 0) < 1:
        raise ValueError("RETRIEVAL_CONTEXTUAL_FOLLOWUP_MAX_HOPS must be >= 1")
    contextual_followup_latency_budget_ms = float(
        getattr(settings, "RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS", 500.0) or 500.0
    )
    if contextual_followup_latency_budget_ms < 0.0:
        raise ValueError("RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS must be >= 0")
    if settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS != contextual_followup_latency_budget_ms:
        settings.RETRIEVAL_CONTEXTUAL_FOLLOWUP_LATENCY_BUDGET_MS = contextual_followup_latency_budget_ms
    if int(getattr(settings, "RAG_CONTEXT_DENOISE_MAX_TOTAL_TOKENS", 0) or 0) < 0:
        raise ValueError("RAG_CONTEXT_DENOISE_MAX_TOTAL_TOKENS must be >= 0")
    if int(getattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_MAX_INPUT_CHARS", 0) or 0) < 0:
        raise ValueError("CONTEXTUAL_RETRIEVAL_LLM_MAX_INPUT_CHARS must be >= 0")
    if int(getattr(settings, "CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS", 0) or 0) < 0:
        raise ValueError("CONTEXTUAL_RETRIEVAL_LLM_MAX_SUMMARY_CHARS must be >= 0")
    intent_router_model_confidence_min = float(
        getattr(settings, "RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN", 0.7) or 0.7
    )
    if not (0.0 <= intent_router_model_confidence_min <= 1.0):
        raise ValueError("RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN must be between 0 and 1")
    if settings.RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN != intent_router_model_confidence_min:
        settings.RAG_INTENT_ROUTER_MODEL_CONFIDENCE_MIN = intent_router_model_confidence_min
    intent_router_model_path = str(getattr(settings, "RAG_INTENT_ROUTER_MODEL_PATH", "") or "").strip()
    if settings.RAG_INTENT_ROUTER_MODEL_PATH != intent_router_model_path:
        settings.RAG_INTENT_ROUTER_MODEL_PATH = intent_router_model_path


def validate_parse_quality(settings):
    low_quality = float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35) or 0.35)
    if low_quality < 0.0 or low_quality > 1.0:
        raise ValueError("RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD must be between 0 and 1")
    alert_ratio = float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5) or 0.5)
    if alert_ratio < 0.0 or alert_ratio > 1.0:
        raise ValueError("RETRIEVAL_PARSE_QUALITY_ALERT_RATIO must be between 0 and 1")
    parse_quality_gate_profile = str(
        getattr(settings, "RETRIEVAL_PARSE_QUALITY_GATE_PROFILE", "warn") or "warn"
    ).strip().lower()
    if parse_quality_gate_profile not in {"off", "warn", "strict"}:
        raise ValueError("RETRIEVAL_PARSE_QUALITY_GATE_PROFILE must be one of: off, warn, strict")
    if settings.RETRIEVAL_PARSE_QUALITY_GATE_PROFILE != parse_quality_gate_profile:
        settings.RETRIEVAL_PARSE_QUALITY_GATE_PROFILE = parse_quality_gate_profile
    parse_risk_min_low_ratio = float(getattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO", 0.5) or 0.5)
    if parse_risk_min_low_ratio < 0.0 or parse_risk_min_low_ratio > 1.0:
        raise ValueError("RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO must be between 0 and 1")
    raw_parse_risk_min_considered = getattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED", 3)
    parse_risk_min_considered = int(3 if raw_parse_risk_min_considered is None else raw_parse_risk_min_considered)
    if parse_risk_min_considered < 1:
        raise ValueError("RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED must be >= 1")
    parse_risk_auto_enqueue_levels = [
        p.strip()
        for p in str(
            getattr(
                settings,
                "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS",
                DEFAULT_RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS,
            )
            or DEFAULT_RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS
        ).split(",")
    ]
    allowed_levels = {str(x).strip().lower() for x in parse_risk_auto_enqueue_levels if str(x).strip()}
    if not allowed_levels:
        allowed_levels = {"high", "medium"}
    if not allowed_levels.issubset({"high", "medium", "low", "unknown"}):
        raise ValueError(
            "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS must be a CSV subset of: high, medium, low, unknown"
        )
    settings.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS = ",".join(sorted(allowed_levels))
    parse_risk_auto_enqueue_min_score = float(
        getattr(settings, "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE", 0.0) or 0.0
    )
    if parse_risk_auto_enqueue_min_score < 0.0 or parse_risk_auto_enqueue_min_score > 1.0:
        raise ValueError("RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE must be between 0 and 1")
    if settings.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE != parse_risk_auto_enqueue_min_score:
        settings.RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE = parse_risk_auto_enqueue_min_score
    raw_parse_risk_reparse_max_docs = getattr(settings, "RETRIEVAL_PARSE_RISK_REPARSE_MAX_DOCS", 100)
    parse_risk_reparse_max_docs = int(100 if raw_parse_risk_reparse_max_docs is None else raw_parse_risk_reparse_max_docs)
    if parse_risk_reparse_max_docs < 1:
        raise ValueError("RETRIEVAL_PARSE_RISK_REPARSE_MAX_DOCS must be >= 1")


def validate_sparse_and_colbert_providers(settings):
    sparse_provider = normalize_sparse_provider_name(
        str(getattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic") or "deterministic")
    )
    if sparse_provider not in VALID_SPARSE_PROVIDERS:
        raise ValueError(
            "SPARSE_RETRIEVAL_PROVIDER must be one of: "
            + ", ".join(sorted(VALID_SPARSE_PROVIDERS))
        )
    if settings.SPARSE_RETRIEVAL_PROVIDER != sparse_provider:
        settings.SPARSE_RETRIEVAL_PROVIDER = sparse_provider

    if bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False)) and sparse_provider == "splade":
        splade_model_name = str(getattr(settings, "SPARSE_SPLADE_MODEL_NAME", "") or "").strip()
        if not splade_model_name:
            raise ValueError(
                "SPARSE_SPLADE_MODEL_NAME is required when "
                "SPARSE_RETRIEVAL_ENABLED=true and SPARSE_RETRIEVAL_PROVIDER=splade"
            )
        if settings.SPARSE_SPLADE_MODEL_NAME != splade_model_name:
            settings.SPARSE_SPLADE_MODEL_NAME = splade_model_name

    colbert_rerank_provider = str(
        getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic") or "deterministic"
    ).strip().lower()
    if colbert_rerank_provider not in {"deterministic", "hf"}:
        raise ValueError("COLBERT_RERANK_PROVIDER must be one of: deterministic, hf")
    if settings.COLBERT_RERANK_PROVIDER != colbert_rerank_provider:
        settings.COLBERT_RERANK_PROVIDER = colbert_rerank_provider


def validate_checkpoint_memory_reranker(settings):
    # Validate checkpoint backend
    valid_checkpoint_backends = {"memory", "sqlite"}
    if settings.CHECKPOINT_BACKEND not in valid_checkpoint_backends:
        raise ValueError(
            f"CHECKPOINT_BACKEND ({settings.CHECKPOINT_BACKEND}) must be one of {valid_checkpoint_backends}"
        )

    # Validate memory store type
    valid_memory_stores = {"memory", "sqlite"}
    if settings.MEMORY_STORE_TYPE not in valid_memory_stores:
        raise ValueError(
            f"MEMORY_STORE_TYPE ({settings.MEMORY_STORE_TYPE}) must be one of {valid_memory_stores}"
        )

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
        "cross_encoder",
        "cross-encoder",
        "sentence_transformers",
        "sentence-transformers",
        "local_bge_v2_m3",
        "bge_v2_m3",
        "long_context",
        "mmr",
        "kg_pagerank",
        "kg_rrf",
        "none",
    }
    if settings.RERANKER_PROVIDER not in valid_reranker_providers:
        raise ValueError(
            f"RERANKER_PROVIDER ({settings.RERANKER_PROVIDER}) must be one of {valid_reranker_providers}"
        )


def validate_rag_eval_gate(settings):
    rag_eval_faithfulness_min = float(getattr(settings, "RAG_EVAL_GATE_FAITHFULNESS_MIN", 0.80) or 0.80)
    if rag_eval_faithfulness_min < 0.0 or rag_eval_faithfulness_min > 1.0:
        raise ValueError("RAG_EVAL_GATE_FAITHFULNESS_MIN must be between 0 and 1")
    if settings.RAG_EVAL_GATE_FAITHFULNESS_MIN != rag_eval_faithfulness_min:
        settings.RAG_EVAL_GATE_FAITHFULNESS_MIN = rag_eval_faithfulness_min

    rag_eval_answer_relevancy_min = float(getattr(settings, "RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN", 0.75) or 0.75)
    if rag_eval_answer_relevancy_min < 0.0 or rag_eval_answer_relevancy_min > 1.0:
        raise ValueError("RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN must be between 0 and 1")
    if settings.RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN != rag_eval_answer_relevancy_min:
        settings.RAG_EVAL_GATE_ANSWER_RELEVANCY_MIN = rag_eval_answer_relevancy_min

    rag_eval_context_precision_min = float(getattr(settings, "RAG_EVAL_GATE_CONTEXT_PRECISION_MIN", 0.70) or 0.70)
    if rag_eval_context_precision_min < 0.0 or rag_eval_context_precision_min > 1.0:
        raise ValueError("RAG_EVAL_GATE_CONTEXT_PRECISION_MIN must be between 0 and 1")
    if settings.RAG_EVAL_GATE_CONTEXT_PRECISION_MIN != rag_eval_context_precision_min:
        settings.RAG_EVAL_GATE_CONTEXT_PRECISION_MIN = rag_eval_context_precision_min

    rag_eval_summary_path = str(
        getattr(settings, "RAG_EVAL_GATE_SUMMARY_PATH", _DEFAULT_RAG_EVAL_SUMMARY_PATH)
        or _DEFAULT_RAG_EVAL_SUMMARY_PATH
    ).strip()
    if not rag_eval_summary_path:
        raise ValueError("RAG_EVAL_GATE_SUMMARY_PATH must be non-empty")
    if settings.RAG_EVAL_GATE_SUMMARY_PATH != rag_eval_summary_path:
        settings.RAG_EVAL_GATE_SUMMARY_PATH = rag_eval_summary_path
