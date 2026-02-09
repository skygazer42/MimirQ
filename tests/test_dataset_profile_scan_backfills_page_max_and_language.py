from __future__ import annotations


def test_backfill_page_count_sets_meta_when_missing() -> None:
    from app.services.dataset_profile_scan_runner import _backfill_page_count

    meta: dict = {}
    parsed = {"page_count": 12}

    changed = _backfill_page_count(meta, parsed)
    assert changed is True
    assert meta.get("page_count") == 12


def test_backfill_language_sets_unknown_when_missing() -> None:
    from app.services.dataset_profile_scan_runner import _backfill_language

    meta: dict = {}
    changed = _backfill_language(meta)
    assert changed is True
    assert meta.get("language") == "unknown"


def test_backfill_language_copies_governance_language_when_present() -> None:
    from app.services.dataset_profile_scan_runner import _backfill_language

    meta: dict = {"governance_enrichment": {"language": "zh-cn"}}
    changed = _backfill_language(meta)
    assert changed is True
    assert meta.get("language") == "zh-cn"

