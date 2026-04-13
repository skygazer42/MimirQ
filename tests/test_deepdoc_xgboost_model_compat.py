from __future__ import annotations

from pathlib import Path

import xgboost as xgb


def test_deepdoc_bundles_compatible_xgboost_model() -> None:
    model_path = Path("app/deepdoc/resources/data_parser/qieci/updown_concat_xgb.ubj")

    assert model_path.exists(), "Expected a UBJ-formatted DeepDoc xgboost model in the repo"

    booster = xgb.Booster()
    booster.load_model(str(model_path))
