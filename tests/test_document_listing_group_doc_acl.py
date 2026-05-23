from __future__ import annotations

from pathlib import Path


def test_document_listing_mentions_group_based_doc_acl_filters() -> None:
    source = Path("app/api/v1/document_listing.py").read_text(encoding="utf-8")

    assert "DocumentGroupPermission" in source
    assert "TenantGroupMember" in source
