from __future__ import annotations

import uuid


def test_resolve_document_access_from_source_acl_maps_groups() -> None:
    from app.api.schemas.connector_acl import ConnectorSourceAclConfig, SourceAcl
    from app.services.connector_source_acl_mapping import resolve_document_access_from_source_acl

    group_id = uuid.uuid4()
    cfg = ConnectorSourceAclConfig(
        mode="inherit",
        group_mappings=[{"source": {"system": "github", "kind": "team", "id": "acme/dev"}, "group_id": str(group_id)}],
    )
    source_acl = SourceAcl(principals=[{"system": "github", "kind": "team", "id": "acme/dev"}])

    access = resolve_document_access_from_source_acl(source_acl=source_acl, config=cfg)
    assert access is not None
    assert access.mode == "partial_members"
    assert access.partial_group_list == [group_id]


def test_resolve_document_access_from_source_acl_anyone_opt_in() -> None:
    from app.api.schemas.connector_acl import ConnectorSourceAclConfig, SourceAcl
    from app.services.connector_source_acl_mapping import resolve_document_access_from_source_acl

    cfg = ConnectorSourceAclConfig(mode="inherit", allow_anyone=True)
    source_acl = SourceAcl(principals=[{"system": "drive", "kind": "anyone", "id": ""}])
    access = resolve_document_access_from_source_acl(source_acl=source_acl, config=cfg)
    assert access is not None
    assert access.mode == "all_team_members"


def test_resolve_document_access_from_source_acl_fallback_mode() -> None:
    from app.api.schemas.connector_acl import ConnectorSourceAclConfig, SourceAcl
    from app.services.connector_source_acl_mapping import resolve_document_access_from_source_acl

    cfg = ConnectorSourceAclConfig(mode="inherit", fallback_mode="only_me")
    source_acl = SourceAcl(principals=[{"system": "github", "kind": "team", "id": "acme/unmapped"}])
    access = resolve_document_access_from_source_acl(source_acl=source_acl, config=cfg)
    assert access is not None
    assert access.mode == "only_me"

