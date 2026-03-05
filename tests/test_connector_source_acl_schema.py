from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError


def test_source_principal_anyone_normalizes_id_to_empty() -> None:
    from app.api.schemas.connector_acl import SourcePrincipal

    p = SourcePrincipal(system="drive", kind="anyone", id="ignored")
    assert p.kind == "anyone"
    assert p.id == ""
    assert p.key() == "drive:anyone:"


def test_source_principal_domain_normalizes_to_lower() -> None:
    from app.api.schemas.connector_acl import SourcePrincipal

    p = SourcePrincipal(system="drive", kind="domain", id="Example.COM")
    assert p.id == "example.com"


def test_connector_source_acl_config_dedupes_mapping_rules() -> None:
    from app.api.schemas.connector_acl import ConnectorSourceAclConfig

    group_id = uuid.uuid4()
    cfg = ConnectorSourceAclConfig(
        mode="inherit",
        group_mappings=[
            {"source": {"system": "github", "kind": "team", "id": "acme/dev"}, "group_id": str(group_id)},
            {"source": {"system": "github", "kind": "team", "id": "acme/dev"}, "group_id": str(group_id)},
        ],
    )
    assert cfg.mode == "inherit"
    assert len(cfg.group_mappings) == 1
    assert cfg.group_mappings[0].group_id == group_id


def test_connector_source_acl_config_is_bounded() -> None:
    from app.api.schemas.connector_acl import ConnectorSourceAclConfig

    rules = []
    for i in range(201):
        rules.append({"source": {"system": "github", "kind": "team", "id": f"acme/t{i}"}, "group_id": str(uuid.uuid4())})

    with pytest.raises(ValidationError):
        ConnectorSourceAclConfig(mode="inherit", group_mappings=rules)

