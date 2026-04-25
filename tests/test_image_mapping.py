from __future__ import annotations

import json

from app.storage.object.image_mapping import (
    load_image_mapping,
    save_image_mapping,
)


def test_save_and_load_image_mapping_roundtrip(tmp_path) -> None:  # noqa: ANN001
    mapping_path = tmp_path / "image_url_mapping.json"
    payload = {
        "images/a.png": "https://cdn.local/a.png",
        "images/b 1.png": "https://cdn.local/b%201.png",
    }

    save_image_mapping(mapping_path, payload)

    raw = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert raw == payload
    loaded = load_image_mapping(mapping_path)
    assert loaded == payload


def test_load_image_mapping_returns_empty_for_missing_file(tmp_path) -> None:  # noqa: ANN001
    assert load_image_mapping(tmp_path / "missing.json") == {}
