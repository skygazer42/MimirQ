"""
Field-level security (FLS) policy validation + matching.

This layer is intentionally declarative:
- Policies are JSON objects only (stored in dataset metadata).
- Matching is regex-based with conservative validation to reduce ReDoS risk.
"""


import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.api.schemas.fls_policy import FlsPolicy, FlsRule
from app.core.regex_safety import looks_like_nested_quantifier

RULE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:\-]{0,99}$")
MAX_RULES = 80
MAX_COLUMN_REGEX_LEN = 200

ALLOWED_SOURCES: set[str] = {"table_store", "db_catalog"}

_ALLOWED_RE_FLAG_BITS = int(re.IGNORECASE)

DEFAULT_MASK = "[REDACTED]"


def _is_suspicious_regex(pattern: str) -> bool:
    return looks_like_nested_quantifier(pattern)


def _normalize_sources(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("sources must be a list")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        v = item.strip().lower()
        if not v:
            continue
        if v not in ALLOWED_SOURCES:
            raise ValueError(f"unsupported source: {v}")
        if v not in out:
            out.append(v)
        if len(out) >= 10:
            break
    return out


def _normalize_allow_roles(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("allow_roles must be a list")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        v = item.strip().lower()
        if not v:
            continue
        if len(v) > 40:
            raise ValueError("allow_roles contains an entry that is too long")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.:\-]*", v):
            raise ValueError(f"invalid role: {v}")
        if v not in out:
            out.append(v)
        if len(out) >= 50:
            break
    return out


def _normalize_allow_account_ids(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("allow_account_ids must be a list")
    out: list[str] = []
    for item in raw:
        v = str(item or "").strip()
        if not v:
            continue
        if len(v) > 255:
            raise ValueError("allow_account_ids contains an entry that is too long")
        if v not in out:
            out.append(v)
        if len(out) >= 200:
            break
    return out


def _normalize_mask(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("mask must be a string")
    v = raw.strip()
    if not v:
        return None
    if len(v) > 80:
        raise ValueError("mask is too long")
    return v


def _normalize_column_name_regex(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("column_name_regex must be a string")
    pat = raw.strip()
    if not pat:
        raise ValueError("column_name_regex is required")
    if len(pat) > MAX_COLUMN_REGEX_LEN:
        raise ValueError(f"column_name_regex too long (max={MAX_COLUMN_REGEX_LEN})")
    if _is_suspicious_regex(pat):
        raise ValueError("column_name_regex looks unsafe")
    try:
        re.compile(pat, flags=_ALLOWED_RE_FLAG_BITS)
    except re.error as exc:
        raise ValueError(f"invalid column_name_regex: {str(exc)[:120]}") from exc
    return pat


def _coerce_rule(rule: FlsRule | Mapping[str, Any] | object, *, index: int) -> FlsRule:
    if isinstance(rule, FlsRule):
        return rule
    try:
        return FlsRule(**(rule if isinstance(rule, dict) else {}))
    except ValidationError as exc:
        raise ValueError(f"invalid rule at index={index}") from exc


def _normalize_fls_rule(rule: FlsRule, *, index: int, seen_ids: set[str]) -> FlsRule:
    rid = str(rule.id or "").strip()
    if not RULE_ID_RE.match(rid):
        raise ValueError(f"invalid rule.id format at index={index}")
    if rid in seen_ids:
        raise ValueError(f"duplicate rule.id: {rid}")
    seen_ids.add(rid)

    name = str(rule.name or "").strip()
    if not name:
        raise ValueError(f"rule.name is required at index={index}")

    sources = _normalize_sources(getattr(rule, "sources", None))
    if not sources:
        raise ValueError(f"rule.sources is required at index={index}")

    allow_roles = _normalize_allow_roles(getattr(rule, "allow_roles", None))
    allow_accounts = _normalize_allow_account_ids(getattr(rule, "allow_account_ids", None))
    if not allow_roles and not allow_accounts:
        raise ValueError(f"rule allowlist is empty at index={index}")

    return FlsRule(
        id=rid,
        name=name[:200],
        enabled=bool(rule.enabled),
        sources=sources,
        column_name_regex=_normalize_column_name_regex(getattr(rule, "column_name_regex", None)),
        allow_roles=allow_roles,
        allow_account_ids=allow_accounts,
        mask=_normalize_mask(getattr(rule, "mask", None)),
    )


def validate_and_normalize_fls_policy(policy: FlsPolicy) -> FlsPolicy:
    if str(policy.version or "").strip() not in {"1"}:
        raise ValueError("unsupported FLS policy version")

    rules_in = policy.rules or []
    if len(rules_in) > MAX_RULES:
        raise ValueError(f"too many rules (max={MAX_RULES})")

    seen_ids: set[str] = set()
    out_rules: list[FlsRule] = []

    for idx, rule in enumerate(rules_in):
        out_rules.append(_normalize_fls_rule(_coerce_rule(rule, index=idx), index=idx, seen_ids=seen_ids))

    return FlsPolicy(version="1", rules=out_rules)


def parse_fls_policy_from_metadata(metadata: dict[str, Any]) -> FlsPolicy | None:
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("fls_policy")
    if not isinstance(raw, dict):
        return None
    try:
        model = FlsPolicy(**raw)
        return validate_and_normalize_fls_policy(model)
    except Exception:
        return None


def fls_policy_to_metadata(policy: FlsPolicy | None) -> dict | None:
    if policy is None:
        return None
    return validate_and_normalize_fls_policy(policy).model_dump()


@dataclass(frozen=True)
class FlsUserContext:
    account_id: str
    role: str


def _is_allowed(rule: FlsRule, ctx: FlsUserContext) -> bool:
    if ctx.account_id and ctx.account_id in (rule.allow_account_ids or []):
        return True
    role = (ctx.role or "").strip().lower()
    if role and role in (rule.allow_roles or []):
        return True
    return False


def resolve_fls_mask_for_column(
    policy: FlsPolicy | None,
    *,
    source: str,
    column_name: str,
    ctx: FlsUserContext,
    default_mask: str = DEFAULT_MASK,
) -> str | None:
    if policy is None or not policy.rules:
        return None
    src = str(source or "").strip().lower()
    if not src:
        return None

    name = str(column_name or "")
    for rule in policy.rules:
        if not bool(getattr(rule, "enabled", True)):
            continue
        sources = getattr(rule, "sources", None) or []
        if src not in sources:
            continue
        pat = str(getattr(rule, "column_name_regex", "") or "").strip()
        if not pat:
            continue
        try:
            if re.search(pat, name, flags=_ALLOWED_RE_FLAG_BITS) is None:
                continue
        except re.error:
            continue

        if _is_allowed(rule, ctx):
            return None

        mask = str(getattr(rule, "mask", "") or "").strip()
        return mask or default_mask
    return None


def build_fls_column_mask_map(
    policy: FlsPolicy | None,
    *,
    source: str,
    columns: Iterable[str],
    ctx: FlsUserContext,
    default_mask: str = DEFAULT_MASK,
) -> dict[str, str]:
    out: dict[str, str] = {}
    for col in columns or []:
        name = str(col or "")
        if not name:
            continue
        mask = resolve_fls_mask_for_column(policy, source=source, column_name=name, ctx=ctx, default_mask=default_mask)
        if mask:
            out[name] = mask
    return out


def redact_row_dicts(rows: Iterable[Mapping[str, Any]], *, mask_map: Mapping[str, str]) -> list[dict[str, Any]]:
    if not mask_map:
        return [dict(r) for r in rows or [] if isinstance(r, Mapping)]
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if not isinstance(r, Mapping):
            continue
        item = dict(r)
        for col, mask in mask_map.items():
            if col in item:
                item[col] = mask
        out.append(item)
    return out


def redact_row_lists(rows: Iterable[object], *, columns: list[str], mask_map: Mapping[str, str]) -> list[list[Any]]:
    if not mask_map:
        return [list(r) if isinstance(r, (list, tuple)) else [r] for r in rows or []]

    idx_mask: dict[int, str] = {}
    for i, col in enumerate(columns or []):
        if col in mask_map:
            idx_mask[int(i)] = str(mask_map[col])
    if not idx_mask:
        return [list(r) if isinstance(r, (list, tuple)) else [r] for r in rows or []]

    out: list[list[Any]] = []
    for r in rows or []:
        if isinstance(r, tuple):
            r = list(r)
        if not isinstance(r, list):
            continue
        item = list(r)
        for i, mask in idx_mask.items():
            if i < len(item):
                item[i] = mask
        out.append(item)
    return out
