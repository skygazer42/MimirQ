from __future__ import annotations

import re

import pytest


def test_parse_cache_key_is_stable_and_bounded():
    from app.services.parse_cache import build_parse_cache_key

    k1 = build_parse_cache_key(
        file_sha256="ABCDEF",
        resolved_backend="Marker",
        config_hash="ph123",
        version="v1",
    )
    k2 = build_parse_cache_key(
        file_sha256="abcdef",
        resolved_backend="marker",
        config_hash="ph123",
        version="v1",
    )
    assert k1 == k2
    assert isinstance(k1, str)
    assert len(k1) == 32
    assert re.fullmatch(r"[0-9a-f]{32}", k1)


def test_parse_cache_object_name_requires_components():
    from app.services.parse_cache import build_parse_cache_object_name

    with pytest.raises(ValueError):
        build_parse_cache_object_name(tenant_id="", dataset_id="d", cache_key="k")
    with pytest.raises(ValueError):
        build_parse_cache_object_name(tenant_id="t", dataset_id="", cache_key="k")
    with pytest.raises(ValueError):
        build_parse_cache_object_name(tenant_id="t", dataset_id="d", cache_key="")


def test_parse_cache_entry_from_obj_strips_unstable_meta_fields():
    from app.services.parse_cache import SCHEMA, ParseCacheEntry

    obj = {
        "schema": SCHEMA,
        "created_at": "2026-03-19T00:00:00+00:00",
        "file_sha256": "deadbeef",
        "resolved_backend": "marker",
        "config_hash": "ph",
        "documents": [
            {
                "page_content": "hello",
                "metadata": {
                    "artifact_dir": "/tmp/a",
                    "asset_base_dir": "/tmp/b",
                    "image_path": "/tmp/c",
                    "keep": "ok",
                },
                "id": "p1",
            }
        ],
    }

    entry = ParseCacheEntry.from_obj(obj)
    assert entry is not None
    assert entry.documents
    meta = entry.documents[0]["metadata"]
    assert meta.get("keep") == "ok"
    assert "artifact_dir" not in meta
    assert "asset_base_dir" not in meta
    assert "image_path" not in meta

