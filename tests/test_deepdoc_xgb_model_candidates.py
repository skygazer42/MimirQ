from __future__ import annotations

from app.deepdoc.parser.pdf_parser import _updown_concat_model_candidates, get_default_resource_dir


def test_deepdoc_xgb_model_candidates_prefer_modern_bundled_artifacts() -> None:
    existing = [path for path in _updown_concat_model_candidates(get_default_resource_dir()) if path.exists()]

    assert existing, "expected at least one bundled xgboost model artifact"
    assert existing[0].name in {"updown_concat_xgb.ubj", "updown_concat_xgb.json"}
    assert "app/deepdoc/resources/data_parser/qieci" in str(existing[0]).replace("\\", "/")
    assert any(path.name == "updown_concat_xgb.model" for path in existing)
