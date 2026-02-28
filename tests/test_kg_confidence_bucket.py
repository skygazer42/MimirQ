from __future__ import annotations


def test_confidence_bucket_basic_thresholds() -> None:
    from app.rag.kg.search.utils import confidence_bucket

    assert confidence_bucket(0.0, low_max=0.4, mid_max=0.7) == "low"
    assert confidence_bucket(0.39, low_max=0.4, mid_max=0.7) == "low"
    assert confidence_bucket(0.4, low_max=0.4, mid_max=0.7) == "mid"
    assert confidence_bucket(0.69, low_max=0.4, mid_max=0.7) == "mid"
    assert confidence_bucket(0.7, low_max=0.4, mid_max=0.7) == "high"
    assert confidence_bucket(1.0, low_max=0.4, mid_max=0.7) == "high"


def test_confidence_bucket_handles_invalid_inputs_and_misconfigured_thresholds() -> None:
    from app.rag.kg.search.utils import confidence_bucket

    # Invalid confidence -> treated as 0.0
    assert confidence_bucket("oops", low_max=0.4, mid_max=0.7) == "low"  # type: ignore[arg-type]
    assert confidence_bucket(None, low_max=0.4, mid_max=0.7) == "low"  # type: ignore[arg-type]

    # low_max >= mid_max should fall back to defaults (0.4/0.7).
    # With default thresholds, 0.5 is "mid".
    assert confidence_bucket(0.5, low_max=0.9, mid_max=0.1) == "mid"
