from __future__ import annotations

import pytest


def test_backfill_parse_quality_adds_when_missing():
    from app.services.dataset_profile_scan_runner import _backfill_parse_quality  # noqa: WPS433

    meta = {
        "pdf_quality": {"score": 0.8, "is_scanned": False},
        "parsed_text_quality": {"density": 0.2, "replacement_ratio": 0.0},
    }
    changed = _backfill_parse_quality(meta)
    assert changed is True
    assert isinstance(meta.get("parse_quality"), dict)
    assert meta["parse_quality"]["score"] == pytest.approx(0.62)


def test_backfill_parse_quality_noop_when_already_present():
    from app.services.dataset_profile_scan_runner import _backfill_parse_quality  # noqa: WPS433

    meta = {
        "pdf_quality": {"score": 0.8, "is_scanned": False},
        "parsed_text_quality": {"density": 0.2, "replacement_ratio": 0.0},
        "parse_quality": {"score": 0.62},
    }
    changed = _backfill_parse_quality(meta)
    assert changed is False

