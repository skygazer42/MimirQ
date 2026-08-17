"""
Governance profile inheritance resolver.

Profiles are declarative payloads that can optionally extend another profile via
`payload.extends`. Resolution produces an "effective" payload where:
  - pipeline_patch is merged (parent -> child; child keys override)
  - regex_rules are concatenated (parent first, child last)
  - processing_scripts are concatenated for review/audit (never executed here)
  - input_formats are unioned in order (parent first)

This module is intentionally light-weight so it can be used by both API and
pipeline services without pulling in FastAPI-specific code.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.schemas.governance_profile import (
    GovernanceProfileOut,
    GovernanceProfilePayload,
    GovernanceProfileSummary,
    RegexRuleModel,
)
from app.models.governance_profile import GovernanceProfile as DBGovernanceProfile
from app.services.governance_profiles import builtin_profile_to_out, get_builtin_governance_profiles


@dataclass(frozen=True)
class ResolvedGovernanceProfile:
    """Resolved governance profile data for applying to pipeline options."""

    profile: GovernanceProfileOut
    chain: list[GovernanceProfileSummary]
    effective: GovernanceProfilePayload


def _profile_identity(profile: GovernanceProfileOut) -> str:
    # Custom profiles have id; builtins do not. key is always present.
    if getattr(profile, "id", None):
        return str(profile.id)
    return str(profile.key or "")


def _summary(profile: GovernanceProfileOut) -> GovernanceProfileSummary:
    return GovernanceProfileSummary(
        id=getattr(profile, "id", None),
        key=str(getattr(profile, "key", "") or ""),
        name=str(getattr(profile, "name", "") or ""),
        description=getattr(profile, "description", None),
        is_system=bool(getattr(profile, "is_system", False)),
    )


def _resolve_profile_chain(
    *,
    start: GovernanceProfileOut,
    fetch_by_ref: Callable[[str], GovernanceProfileOut],
    max_depth: int,
) -> list[GovernanceProfileOut]:
    chain_leaf_to_root: list[GovernanceProfileOut] = []
    seen: set[str] = set()

    current = start
    for _ in range(max_depth):
        ident = _profile_identity(current)
        if ident in seen:
            raise ValueError("governance profile inheritance cycle detected")
        seen.add(ident)
        chain_leaf_to_root.append(current)

        parent_ref = str(getattr(current.payload, "extends", None) or "").strip()
        if not parent_ref:
            return list(reversed(chain_leaf_to_root))
        current = fetch_by_ref(parent_ref)

    raise ValueError("governance profile inheritance chain too deep")


def _merge_profile_payload(chain: list[GovernanceProfileOut]) -> GovernanceProfilePayload:
    input_formats: list[str] = []
    pipeline_patch: dict = {}
    regex_rules: list[RegexRuleModel] = []
    processing_scripts: list = []

    for profile in chain:
        for fmt in getattr(profile.payload, "input_formats", None) or []:
            value = str(fmt or "").strip().lower()
            if value in {"markdown", "html"} and value not in input_formats:
                input_formats.append(value)

        patch = getattr(profile.payload, "pipeline_patch", None) or {}
        if isinstance(patch, dict):
            pipeline_patch.update(dict(patch))

        for rule in getattr(profile.payload, "regex_rules", None) or []:
            if isinstance(rule, RegexRuleModel):
                regex_rules.append(rule)
            elif isinstance(rule, dict):
                regex_rules.append(RegexRuleModel(**rule))

        processing_scripts.extend(list(getattr(profile.payload, "processing_scripts", None) or []))

    return GovernanceProfilePayload(
        version="1",
        extends=None,
        input_formats=input_formats or ["markdown"],  # type: ignore[arg-type]
        pipeline_patch=pipeline_patch,
        regex_rules=regex_rules,
        processing_scripts=processing_scripts[:10],
    )


def resolve_profile_inheritance(
    start: GovernanceProfileOut,
    *,
    fetch_by_ref: Callable[[str], GovernanceProfileOut],
    max_depth: int = 12,
) -> ResolvedGovernanceProfile:
    """
    Resolve inheritance chain and compute effective payload.

    This function is pure (does not touch DB) and can be unit tested by injecting
    a `fetch_by_ref` implementation.
    """
    if max_depth <= 0:
        raise ValueError("max_depth must be > 0")

    chain = _resolve_profile_chain(start=start, fetch_by_ref=fetch_by_ref, max_depth=max_depth)
    effective = _merge_profile_payload(chain)

    return ResolvedGovernanceProfile(
        profile=start,
        chain=[_summary(p) for p in chain],
        effective=effective,
    )


def _load_governance_profile_ref(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
) -> GovernanceProfileOut:
    ref = str(profile_ref or "").strip()
    if not ref:
        raise ValueError("profile_ref is required")

    builtins = get_builtin_governance_profiles()
    builtin_by_key = {p.key: p for p in builtins}
    if ref in builtin_by_key:
        return builtin_profile_to_out(builtin_by_key[ref])

    # Allow UUID lookup.
    try:
        ref_uuid = UUID(ref)
    except Exception:
        ref_uuid = None

    q = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    row = (
        q.filter(DBGovernanceProfile.id == ref_uuid).first()
        if ref_uuid
        else q.filter(DBGovernanceProfile.key == ref).first()
    )
    if row is None:
        raise ValueError("governance profile not found")

    payload_raw = getattr(row, "payload", None)
    if not isinstance(payload_raw, dict):
        payload_raw = {}

    try:
        return GovernanceProfileOut(
            id=row.id,
            key=(str(getattr(row, "key", "") or "").strip() or f"custom:{str(row.id)}"),
            name=str(getattr(row, "name", "") or ""),
            description=getattr(row, "description", None),
            is_system=bool(getattr(row, "is_system", False)),
            payload=payload_raw,  # pydantic validates nested payload
            created_at=getattr(row, "created_at", None),
            updated_at=getattr(row, "updated_at", None),
        )
    except ValidationError as exc:
        raise ValueError("invalid governance profile payload in DB") from exc


def resolve_governance_profile_ref_effective(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
    max_depth: int = 12,
) -> ResolvedGovernanceProfile:
    """
    Resolve a governance profile ref (builtin:<key> | UUID | tenant-scoped key) to an effective payload.
    """

    start = _load_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref)

    def fetch(parent_ref: str) -> GovernanceProfileOut:
        return _load_governance_profile_ref(db=db, tenant_id=tenant_id, profile_ref=parent_ref)

    return resolve_profile_inheritance(start, fetch_by_ref=fetch, max_depth=max_depth)


__all__ = [
    "ResolvedGovernanceProfile",
    "resolve_governance_profile_ref_effective",
    "resolve_profile_inheritance",
]
