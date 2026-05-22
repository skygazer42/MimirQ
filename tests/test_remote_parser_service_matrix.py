from __future__ import annotations

from scripts.remote_parser_service_matrix import classify_failure


def test_parser_service_matrix_fails_requested_resolved_backend_mismatch() -> None:
    summary = {"markdown_chars": 1200, "resolved_backend": "basic", "backend": "basic"}

    assert (
        classify_failure(
            200,
            {"resolved_backend": "basic"},
            summary,
            min_markdown_chars=80,
            requested_backend="magicpdf",
        )
        == "resolved_backend_mismatch:basic"
    )


def test_parser_service_matrix_accepts_requested_backend_when_resolved_matches() -> None:
    summary = {"markdown_chars": 1200, "resolved_backend": "magicpdf", "backend": "magicpdf"}

    assert (
        classify_failure(
            200,
            {"resolved_backend": "magicpdf"},
            summary,
            min_markdown_chars=80,
            requested_backend="magicpdf",
        )
        == "ok"
    )
