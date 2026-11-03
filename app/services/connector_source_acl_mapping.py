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


def _build_group_mapping_index(config: ConnectorSourceAclConfig) -> dict[str, set[UUID]]:
    index: dict[str, set[UUID]] = {}
    for rule in config.group_mappings[:200]:
        index.setdefault(rule.source.key(), set()).add(rule.group_id)
    return index


def _collect_mapped_group_ids(
    *,
    source_acl: SourceAcl,
    index: dict[str, set[UUID]],
    max_groups: int,
) -> set[UUID]:
    mapped: set[UUID] = set()
    for principal in source_acl.principals[:500]:
        group_ids = index.get(principal.key())
        if group_ids:
            mapped.update(group_ids)
        if max_groups and len(mapped) >= max_groups:
            break
    return mapped


def _build_group_access_request(*, mapped: set[UUID], max_groups: int) -> DocumentAccessUpdateRequest:
    ordered = sorted(mapped, key=lambda value: str(value))
    if max_groups:
        ordered = ordered[: max(0, int(max_groups))]
    return DocumentAccessUpdateRequest(mode="partial_members", partial_group_list=ordered)


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

    if config is None or config.mode != "inherit":
        return None

    if config.allow_anyone and source_acl.has_anyone():
        return DocumentAccessUpdateRequest(mode="all_team_members")

    index = _build_group_mapping_index(config)
    mapped = _collect_mapped_group_ids(source_acl=source_acl, index=index, max_groups=max_groups)

    if mapped:
        return _build_group_access_request(mapped=mapped, max_groups=max_groups)

    # No mapped principals: apply fallback.
    return DocumentAccessUpdateRequest(mode=config.fallback_mode)


__all__ = ["resolve_document_access_from_source_acl"]
