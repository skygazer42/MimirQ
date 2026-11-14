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

from app.api.schemas.identity import FlsPolicy, FlsRule
from app.core.regex_safety import looks_like_nested_quantifier

RULE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:\-]{0,99}$")
MAX_RULES = 80

ALLOWED_SOURCES: set[str] = {"table_store", "db_catalog"}

_ALLOWED_RE_FLAG_BITS = int(re.IGNORECASE)

DEFAULT_MASK = "[REDACTED]"


def _normalize_sources(raw: list[str]) -> list[str]:
    out: list[str] = []
    for item in raw:
        v = item.strip().lower()
        if not v:
            continue
        if v not in ALLOWED_SOURCES:
            raise ValueError(f"unsupported source: {v}")
        if v not in out:
            out.append(v)
    return out


def _normalize_allow_roles(raw: list[str]) -> list[str]:
    out: list[str] = []
    for item in raw:
        v = item.strip().lower()
        if not v:
            continue
        if len(v) > 40:
            raise ValueError("allow_roles contains an entry that is too long")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.:\-]*", v):
            raise ValueError(f"invalid role: {v}")
        if v not in out:
            out.append(v)
    return out


def _normalize_allow_account_ids(raw: list[str]) -> list[str]:
    out: list[str] = []
    for item in raw:
        v = item.strip()
        if not v:
            continue
        if len(v) > 255:
            raise ValueError("allow_account_ids contains an entry that is too long")
        if v not in out:
            out.append(v)
    return out


def _normalize_mask(raw: str | None) -> str | None:
    if raw is None:
        return None
    v = raw.strip()
    if not v:
        return None
    return v


def _normalize_column_name_regex(raw: str) -> str:
    pat = raw.strip()
    if not pat:
        raise ValueError("column_name_regex is required")
    if looks_like_nested_quantifier(pat):
        raise ValueError("column_name_regex looks unsafe")
    try:
        re.compile(pat, flags=_ALLOWED_RE_FLAG_BITS)
    except re.error as exc:
        raise ValueError(f"invalid column_name_regex: {str(exc)[:120]}") from exc
    return pat


def _normalize_fls_rule(rule: FlsRule, *, index: int, seen_ids: set[str]) -> FlsRule:
    rid = rule.id.strip()
    if not RULE_ID_RE.match(rid):
        raise ValueError(f"invalid rule.id format at index={index}")
    if rid in seen_ids:
        raise ValueError(f"duplicate rule.id: {rid}")
    seen_ids.add(rid)

    name = rule.name.strip()
    if not name:
        raise ValueError(f"rule.name is required at index={index}")

    sources = _normalize_sources(rule.sources)
    if not sources:
        raise ValueError(f"rule.sources is required at index={index}")

    allow_roles = _normalize_allow_roles(rule.allow_roles)
    allow_accounts = _normalize_allow_account_ids(rule.allow_account_ids)
    if not allow_roles and not allow_accounts:
        raise ValueError(f"rule allowlist is empty at index={index}")

    return FlsRule(
        id=rid,
        name=name,
        enabled=rule.enabled,
        sources=sources,
        column_name_regex=_normalize_column_name_regex(rule.column_name_regex),
        allow_roles=allow_roles,
        allow_account_ids=allow_accounts,
        mask=_normalize_mask(rule.mask),
    )


def validate_and_normalize_fls_policy(policy: FlsPolicy) -> FlsPolicy:
    if policy.version.strip() != "1":
        raise ValueError("unsupported FLS policy version")

    if len(policy.rules) > MAX_RULES:
        raise ValueError(f"too many rules (max={MAX_RULES})")

    seen_ids: set[str] = set()
    out_rules: list[FlsRule] = []

    for idx, rule in enumerate(policy.rules):
        out_rules.append(_normalize_fls_rule(rule, index=idx, seen_ids=seen_ids))

    return FlsPolicy(version="1", rules=out_rules)


def parse_fls_policy_from_metadata(metadata: dict[str, Any]) -> FlsPolicy | None:
    raw = metadata.get("fls_policy")
    if raw is None:
        return None
    # An invalid configured policy must not turn into an unmasked response.
    model = FlsPolicy.model_validate(raw)
    return validate_and_normalize_fls_policy(model)


@dataclass(frozen=True)
class FlsUserContext:
    account_id: str
    role: str


def _is_allowed(rule: FlsRule, ctx: FlsUserContext) -> bool:
    return ctx.account_id in rule.allow_account_ids or ctx.role.strip().lower() in rule.allow_roles


def resolve_fls_mask_for_column(
    policy: FlsPolicy | None,
    *,
    source: str,
    column_name: str,
    ctx: FlsUserContext,
    default_mask: str = DEFAULT_MASK,
) -> str | None:
    if policy is None:
        return None
    src = source.strip().lower()
    for rule in policy.rules:
        if not rule.enabled or src not in rule.sources:
            continue
        if re.search(rule.column_name_regex, column_name, flags=_ALLOWED_RE_FLAG_BITS) is None:
            continue

        if _is_allowed(rule, ctx):
            return None

        return default_mask if rule.mask is None else rule.mask
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
    for name in columns:
        if not name:
            continue
        mask = resolve_fls_mask_for_column(policy, source=source, column_name=name, ctx=ctx, default_mask=default_mask)
        if mask:
            out[name] = mask
    return out


def redact_row_dicts(rows: Iterable[Mapping[str, Any]], *, mask_map: Mapping[str, str]) -> list[dict[str, Any]]:
    if not mask_map:
        return [dict(row) for row in rows]
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for col, mask in mask_map.items():
            if col in item:
                item[col] = mask
        out.append(item)
    return out


def redact_row_lists(rows: Iterable[list[Any]], *, columns: list[str], mask_map: Mapping[str, str]) -> list[list[Any]]:
    if not mask_map:
        return [list(row) for row in rows]

    idx_mask: dict[int, str] = {}
    for i, col in enumerate(columns):
        if col in mask_map:
            idx_mask[i] = mask_map[col]
    if not idx_mask:
        return [list(row) for row in rows]

    out: list[list[Any]] = []
    for row in rows:
        item = list(row)
        for i, mask in idx_mask.items():
            if i < len(item):
                item[i] = mask
        out.append(item)
    return out
