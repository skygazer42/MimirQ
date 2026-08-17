"""
Dataset ingestion policy (file-level pre-processing + per-file-type overrides).

This layer is intentionally *declarative*:
- Policies and "scripts" are JSON objects only.
- No dynamic imports, no arbitrary code execution.

Security hardening:
- Strict allowlists (preprocess steps, pipeline_patch keys)
- Size/length caps (rule count, regex lengths, patch size)
- Best-effort regex ReDoS guard (nested quantifiers)
"""


import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.schemas.governance_profile import GovernanceProfileOut
from app.api.schemas.ingestion_policy import IngestionPolicy, IngestionPreprocessStep, IngestionRule
from app.core.regex_safety import looks_like_nested_quantifier
from app.services.governance_profiles_resolver import resolve_governance_profile_ref_effective
from app.services.pipeline_patch_validator import normalize_document_pipeline_patch

RULE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:\-]{0,99}$")
MAX_RULES = 60
MAX_EXTENSIONS_PER_RULE = 30
MAX_EXTENSION_LEN = 12
MAX_FILENAME_REGEX_LEN = 200
MAX_PREPROCESS_STEPS = 20
MAX_PIPELINE_PATCH_KEYS = 120

_ALLOWED_RE_FLAG_BITS = int(re.IGNORECASE)


# Public allowlist of supported file preprocess step ids.
ALLOWED_PREPROCESS_STEP_IDS: set[str] = {
    # Text-ish (applied to .txt/.md/.json/.csv/.html/...)
    "text.reencode_utf8",
    "text.strip_bom",
    "text.normalize_newlines",
    "text.collapse_blank_lines",
    "text.trim_trailing_whitespace",
    "text.remove_zero_width",
    "text.remove_control_chars",
    "text.normalize_unicode_nfc",
    "text.normalize_unicode_nfkc",
    # HTML-only (applied when ext in .html/.htm)
    "html.strip_scripts_styles",
    "html.strip_comments",
    "html.strip_boilerplate_tags",
}


def _is_suspicious_regex(pattern: str) -> bool:
    return looks_like_nested_quantifier(pattern)


def _normalize_extensions(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("match.extensions must be a list")
    if len(raw) > MAX_EXTENSIONS_PER_RULE:
        raise ValueError(f"match.extensions too many entries (max={MAX_EXTENSIONS_PER_RULE})")
    out: list[str] = []
    for item in raw:
        normalized = _normalize_extension_item(item)
        if normalized is None:
            continue
        if normalized not in out:
            out.append(normalized)
    return out


def _normalize_extension_item(item: object) -> str | None:
    if not isinstance(item, str):
        return None
    value = item.strip().lower()
    if not value:
        return None
    if not value.startswith("."):
        value = "." + value
    if len(value) > MAX_EXTENSION_LEN:
        raise ValueError("match.extensions contains an entry that is too long")
    if not re.fullmatch(r"\.[a-z0-9][a-z0-9._-]*", value):
        raise ValueError(f"invalid extension: {value}")
    return value


def _normalize_filename_regex(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("match.filename_regex must be a string")
    pat = raw.strip()
    if not pat:
        return None
    if len(pat) > MAX_FILENAME_REGEX_LEN:
        raise ValueError(f"match.filename_regex too long (max={MAX_FILENAME_REGEX_LEN})")
    if _is_suspicious_regex(pat):
        raise ValueError("match.filename_regex looks unsafe")
    try:
        re.compile(pat, flags=_ALLOWED_RE_FLAG_BITS)
    except re.error as exc:
        raise ValueError(f"invalid match.filename_regex: {str(exc)[:120]}") from exc
    return pat


def _coerce_preprocess_step(item: object, *, idx: int) -> IngestionPreprocessStep:
    if isinstance(item, IngestionPreprocessStep):
        return item
    if isinstance(item, dict):
        try:
            return IngestionPreprocessStep(**item)
        except ValidationError as exc:
            raise ValueError(f"invalid preprocess step at index={idx}") from exc
    raise ValueError(f"invalid preprocess step at index={idx}")


def _normalized_step_id(step: IngestionPreprocessStep, *, idx: int) -> str:
    sid = str(step.id or "").strip().lower()
    if not sid:
        raise ValueError(f"preprocess step id is required at index={idx}")
    if sid not in ALLOWED_PREPROCESS_STEP_IDS:
        raise ValueError(f"unsupported preprocess step id: {sid}")
    return sid


def _normalize_preprocess_steps(raw: object) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("preprocess.steps must be a list")
    if len(raw) > MAX_PREPROCESS_STEPS:
        raise ValueError(f"preprocess.steps too many steps (max={MAX_PREPROCESS_STEPS})")
    out: list[dict] = []
    for idx, item in enumerate(raw):
        step = _coerce_preprocess_step(item, idx=idx)
        sid = _normalized_step_id(step, idx=idx)

        params = step.params or {}
        if not isinstance(params, dict):
            raise ValueError(f"preprocess step params must be an object at index={idx}")
        # Keep v1 strict: no params yet (easy to reason about and secure).
        if params:
            raise ValueError(f"preprocess step params not supported (index={idx})")

        out.append({"id": sid, "params": {}})
    return out


def _normalize_pipeline_patch(raw: object) -> dict:
    return normalize_document_pipeline_patch(
        raw,
        field_label="pipeline_patch",
        invalid_message="invalid pipeline_patch",
        max_keys=MAX_PIPELINE_PATCH_KEYS,
    )


def _coerce_rule(rule: IngestionRule | dict[str, Any] | object, *, idx: int) -> IngestionRule:
    if isinstance(rule, IngestionRule):
        return rule
    try:
        return IngestionRule(**(rule if isinstance(rule, dict) else {}))
    except ValidationError as exc:
        raise ValueError(f"invalid rule at index={idx}") from exc


def _normalize_optional_override(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower() or None


def _normalize_governance_profile_ref(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip() or None
    if normalized and ("\x7f" in normalized or any(ord(ch) < 32 for ch in normalized)):
        raise ValueError("invalid governance_profile_ref")
    return normalized


def _normalize_rule(rule: IngestionRule | dict[str, Any] | object, *, idx: int, seen_ids: set[str]) -> IngestionRule:
    rule = _coerce_rule(rule, idx=idx)

    rid = str(rule.id or "").strip()
    if not rid:
        raise ValueError(f"rule.id is required at index={idx}")
    if not RULE_ID_RE.match(rid):
        raise ValueError(f"invalid rule.id format at index={idx}")
    if rid in seen_ids:
        raise ValueError(f"duplicate rule.id: {rid}")
    seen_ids.add(rid)

    name = str(rule.name or "").strip()
    if not name:
        raise ValueError(f"rule.name is required at index={idx}")

    match = rule.match or {}
    ext_list = _normalize_extensions(getattr(match, "extensions", None))
    filename_regex = _normalize_filename_regex(getattr(match, "filename_regex", None))

    preprocess = rule.preprocess
    preprocess_enabled = bool(getattr(preprocess, "enabled", True))
    preprocess_steps = getattr(preprocess, "steps", None) if preprocess_enabled else []
    steps_norm = _normalize_preprocess_steps(preprocess_steps)

    return IngestionRule(
        id=rid,
        name=name[:200],
        enabled=bool(rule.enabled),
        match={"extensions": ext_list, "filename_regex": filename_regex},
        preprocess={"enabled": preprocess_enabled, "steps": steps_norm},
        parser_backend=_normalize_optional_override(rule.parser_backend),
        chunk_strategy=_normalize_optional_override(rule.chunk_strategy),
        governance_profile_ref=_normalize_governance_profile_ref(rule.governance_profile_ref),
        pipeline_patch=_normalize_pipeline_patch(rule.pipeline_patch),
    )


def validate_and_normalize_ingestion_policy(policy: IngestionPolicy) -> IngestionPolicy:
    """
    Validate and normalize policy.

    Raises ValueError on invalid input.
    """
    if str(policy.version or "").strip() not in {"1"}:
        raise ValueError("unsupported ingestion policy version")

    rules_in = policy.rules or []
    if len(rules_in) > MAX_RULES:
        raise ValueError(f"too many rules (max={MAX_RULES})")

    seen_ids: set[str] = set()
    normalized_rules: list[IngestionRule] = []

    for idx, rule in enumerate(rules_in):
        normalized_rules.append(_normalize_rule(rule, idx=idx, seen_ids=seen_ids))

    return IngestionPolicy(version="1", rules=normalized_rules)


def parse_ingestion_policy_from_metadata(metadata: dict[str, Any]) -> IngestionPolicy | None:
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("ingestion_policy")
    if not isinstance(raw, dict):
        return None
    try:
        model = IngestionPolicy(**raw)
        return validate_and_normalize_ingestion_policy(model)
    except Exception:
        return None


def policy_to_metadata(policy: IngestionPolicy | None) -> dict | None:
    if policy is None:
        return None
    return validate_and_normalize_ingestion_policy(policy).model_dump()


def match_ingestion_rule(policy: IngestionPolicy | None, *, filename: str, file_ext: str) -> IngestionRule | None:
    if policy is None:
        return None
    ext = (file_ext or "").strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    fn = str(filename or "")
    for rule in policy.rules or []:
        if not bool(getattr(rule, "enabled", True)):
            continue
        match = getattr(rule, "match", None)
        exts = []
        rx = None
        if match is not None:
            exts = list(getattr(match, "extensions", None) or [])
            rx = getattr(match, "filename_regex", None)
        if exts and ext not in set(exts):
            continue
        if isinstance(rx, str) and rx.strip():
            try:
                if not re.search(rx, fn, flags=_ALLOWED_RE_FLAG_BITS):
                    continue
            except re.error:
                # Invalid stored regex should not break ingestion; treat as non-match.
                continue
        return rule
    return None


@dataclass(frozen=True)
class ResolvedGovernanceProfilePatch:
    profile: GovernanceProfileOut
    pipeline_patch: dict
    regex_rules: list[dict]


def resolve_governance_profile_ref(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
) -> ResolvedGovernanceProfilePatch:
    """
    Resolve a governance profile ref (builtin:<key> | UUID | tenant-scoped key).

    Returns normalized patch data suitable for merging into PipelineOptions.
    """
    resolved = resolve_governance_profile_ref_effective(db=db, tenant_id=tenant_id, profile_ref=profile_ref)
    payload = resolved.effective
    patch = payload.pipeline_patch or {}
    rules = [r.model_dump() for r in (payload.regex_rules or [])]
    return ResolvedGovernanceProfilePatch(profile=resolved.profile, pipeline_patch=dict(patch), regex_rules=rules)


def export_policy_json(policy: IngestionPolicy) -> bytes:
    """
    Export as UTF-8 JSON (stable, human-readable).
    """
    normalized = validate_and_normalize_ingestion_policy(policy)
    obj = normalized.model_dump()
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
