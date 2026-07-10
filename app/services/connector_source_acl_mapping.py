"""
Source ACL -> document access mapping helpers.

This module is intentionally connector-agnostic. Individual connectors are expected to:
- Fetch/compute a `SourceAcl` (who can read a source object)
- Apply a `ConnectorSourceAclConfig` to map source principals -> tenant groups
- Convert the result into a document-level ACL override (`DocumentAccessUpdateRequest`)
"""


from uuid import UUID

from app.api.schemas.connector_acl import ConnectorSourceAclConfig, SourceAcl
from app.api.schemas.document import DocumentAccessUpdateRequest
from app.rag.core.logging import get_logger


def resolve_document_access_from_source_acl(
    *,
    source_acl: SourceAcl,
    config: ConnectorSourceAclConfig | None,
    max_groups: int = 200,
) -> DocumentAccessUpdateRequest | None:
    """
    Map a connector-provided `SourceAcl` into a document-level access override.

    Fail-closed defaults:
    - If mode!=inherit -> None (no override)
    - If no groups are mapped -> fallback_mode (default: partial_members -> owner-only)
    """

    if config is None:
        return None
    if str(config.mode or "disabled") != "inherit":
        return None

    if bool(config.allow_anyone) and bool(source_acl.has_anyone()):
        return DocumentAccessUpdateRequest(mode="all_team_members")

    # Build a mapping index from source principal key -> group ids.
    index: dict[str, set[UUID]] = {}
    for rule in (config.group_mappings or [])[:200]:
        try:
            key = rule.source.key()
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        index.setdefault(key, set()).add(rule.group_id)

    mapped: set[UUID] = set()
    for p in (source_acl.principals or [])[:500]:
        try:
            key = p.key()
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        gids = index.get(key)
        if gids:
            mapped.update(gids)
        if max_groups and len(mapped) >= max_groups:
            break

    if mapped:
        # Deterministic ordering for stable behavior/tests.
        ordered = sorted(mapped, key=lambda v: str(v))
        if max_groups:
            ordered = ordered[: max(0, int(max_groups))]
        return DocumentAccessUpdateRequest(mode="partial_members", partial_group_list=ordered)

    # No mapped principals: apply fallback.
    return DocumentAccessUpdateRequest(mode=str(config.fallback_mode or "partial_members"))


__all__ = ["resolve_document_access_from_source_acl"]

