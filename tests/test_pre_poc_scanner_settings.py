from __future__ import annotations


def test_resolve_pre_poc_scanner_thresholds_applies_overrides_and_clamps(monkeypatch) -> None:  # noqa: ANN001
    from app.core.config import settings
    from app.rag.tools.pre_poc_scanner.settings import resolve_pre_poc_scanner_thresholds

    monkeypatch.setattr(settings, "PRECHECK_PDF_SCAN_RATIO_THRESHOLD", 0.7, raising=False)
    monkeypatch.setattr(settings, "PRECHECK_PDF_LOW_DENSITY_RATIO_THRESHOLD", 0.3, raising=False)
    monkeypatch.setattr(settings, "PRECHECK_TEXT_SHORT_CHARS_THRESHOLD", 200, raising=False)
    monkeypatch.setattr(settings, "PRECHECK_NEAR_DUP_HAMMING_THRESHOLD", 5, raising=False)
    monkeypatch.setattr(settings, "PRECHECK_SAMPLE_SIZE", 60, raising=False)

    out = resolve_pre_poc_scanner_thresholds(
        {
            "pdf_scan_ratio_threshold": 0.95,
            "pdf_low_density_ratio_threshold": -1,
            "text_short_chars_threshold": 999999,
            "near_dup_hamming_threshold": 100,
            "sample_size": -5,
        }
    )

    assert out["schema"] == "mimirq.pre_poc.thresholds.v1"
    assert out["pdf_scan_ratio_threshold"] == 0.95
    assert out["pdf_low_density_ratio_threshold"] == 0.0
    assert out["text_short_chars_threshold"] == 100000
    assert out["near_dup_hamming_threshold"] == 32
    assert out["sample_size"] == 0


def test_dataset_precheck_request_accepts_threshold_overrides() -> None:
    from app.api.schemas.dataset_precheck import DatasetPrecheckScanRunCreateRequest

    body = DatasetPrecheckScanRunCreateRequest(
        root_path="/tmp/demo",
        threshold_overrides={
            "pdf_scan_ratio_threshold": 0.8,
            "near_dup_hamming_threshold": 4,
        },
    )

    assert body.threshold_overrides == {
        "pdf_scan_ratio_threshold": 0.8,
        "near_dup_hamming_threshold": 4,
    }
