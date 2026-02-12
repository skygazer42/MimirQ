from __future__ import annotations


def test_risk_buckets_for_pdf_scanned_is_ocr() -> None:
    from app.services.dataset_precheck_risk_buckets import risk_buckets_for_file

    out = risk_buckets_for_file(file_type="pdf", findings=["pdf_scanned"])
    assert "ocr" in out


def test_risk_buckets_for_gibberish_is_garbage() -> None:
    from app.services.dataset_precheck_risk_buckets import risk_buckets_for_file

    out = risk_buckets_for_file(file_type="txt", findings=["gibberish_text"])
    assert "garbage" in out


def test_risk_buckets_for_low_density_is_low_density() -> None:
    from app.services.dataset_precheck_risk_buckets import risk_buckets_for_file

    out = risk_buckets_for_file(file_type="md", findings=["low_density_text"])
    assert "low_density" in out


def test_risk_buckets_for_html_marks_boilerplate() -> None:
    from app.services.dataset_precheck_risk_buckets import risk_buckets_for_file

    out = risk_buckets_for_file(file_type="html", findings=[])
    assert "boilerplate" in out


def test_risk_buckets_for_csv_marks_table_heavy() -> None:
    from app.services.dataset_precheck_risk_buckets import risk_buckets_for_file

    out = risk_buckets_for_file(file_type="csv", findings=[])
    assert "table_heavy" in out

