
from types import SimpleNamespace

import pytest

from app.rag.preprocessing import diagnostics


def _artifact_rich_text() -> str:
    lines = [f"Readable paragraph line {index} with enough content to avoid very short lines." for index in range(80)]
    lines.extend(["exam-\nple"] * 5)
    lines.extend([f"| cell {index} | value |" for index in range(20)])
    lines.extend(
        [
            "<div>one</div><span>two</span><p>three</p>",
            "control:\x01",
            "https://example.test/a?utm_source=x",
            "https://example.test/b?gclid=y",
            "https://example.test/c?fbclid=z",
            " ".join(f"![image {index}](image-{index}.png)" for index in range(8)),
        ]
    )
    return "\n".join(lines)


def test_analyze_governance_preserves_issue_order_and_combined_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostics,
        "build_repeated_line_signatures",
        lambda *_args, **_kwargs: {"Header", "Footer"},
    )
    monkeypatch.setattr(
        diagnostics,
        "drop_if_outline_only",
        lambda *_args, **_kwargs: SimpleNamespace(dropped=False),
    )
    monkeypatch.setattr(
        diagnostics,
        "drop_if_low_density",
        lambda *_args, **_kwargs: SimpleNamespace(dropped=False),
    )

    issues, patch = diagnostics.analyze_governance(
        _artifact_rich_text(),
        "",
        options={
            "unwrap_lines": False,
            "remove_common_lines": False,
            "normalize_tables": False,
            "normalize_urls": False,
            "remove_images": "none",
        },
    )

    assert [issue.code for issue in issues] == [
        "html_tags_present",
        "control_chars",
        "pdf_soft_line_breaks",
        "pdf_hyphenation_breaks",
        "repeated_lines",
        "tables_detected",
        "tracking_urls",
        "many_images",
    ]
    assert patch == {
        "governance_unwrap_lines": True,
        "governance_remove_common_lines": True,
        "governance_normalize_tables": True,
        "governance_normalize_urls": True,
        "governance_normalize_urls_strip_tracking": True,
        "governance_remove_images": "decorative",
    }
    assert issues[0].samples == ["<div>", "</div>", "<span>"]
    assert issues[4].samples == ["Footer", "Header"]


def test_enabled_options_keep_detection_but_remove_redundant_suggestions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    soft_lines = "\n".join("x" * 60 for _ in range(80)) + "\n" + "\n".join(["exam-\nple"] * 5)
    monkeypatch.setattr(
        diagnostics,
        "build_repeated_line_signatures",
        lambda *_args, **_kwargs: {"Header"},
    )
    monkeypatch.setattr(
        diagnostics,
        "drop_if_outline_only",
        lambda *_args, **_kwargs: SimpleNamespace(dropped=False),
    )
    monkeypatch.setattr(
        diagnostics,
        "drop_if_low_density",
        lambda *_args, **_kwargs: SimpleNamespace(dropped=False),
    )

    issues, patch = diagnostics.analyze_governance(
        soft_lines,
        "",
        options={"unwrap_lines": True, "remove_common_lines": True},
    )

    assert [issue.code for issue in issues] == [
        "pdf_soft_line_breaks",
        "pdf_hyphenation_breaks",
        "repeated_lines",
    ]
    assert all(issue.suggested_pipeline_patch == {} for issue in issues)
    assert patch == {}


def test_filter_risks_and_after_clean_density_preserve_order_and_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostics,
        "build_repeated_line_signatures",
        lambda *_args, **_kwargs: set(),
    )
    seen: dict[str, float] = {}

    def outline(_text: str, *, min_content_chars: int, max_heading_ratio: float):
        seen["outline_min"] = min_content_chars
        seen["outline_ratio"] = max_heading_ratio
        return SimpleNamespace(dropped=True)

    def low_density(_text: str, *, threshold: float):
        seen["density_threshold"] = threshold
        return SimpleNamespace(dropped=True)

    monkeypatch.setattr(diagnostics, "drop_if_outline_only", outline)
    monkeypatch.setattr(diagnostics, "drop_if_low_density", low_density)

    issues, patch = diagnostics.analyze_governance(
        "Readable text",
        "!!!",
        options={
            "drop_outline_min_content_chars": 321,
            "drop_outline_max_heading_ratio": 0.7,
            "drop_low_density_threshold": 0.2,
        },
    )

    assert [issue.code for issue in issues] == [
        "outline_only_risk",
        "low_density_risk",
        "low_density_after_clean",
    ]
    assert patch == {
        "governance_drop_outline_only": True,
        "governance_drop_low_density": True,
    }
    assert seen == {
        "outline_min": 321,
        "outline_ratio": 0.7,
        "density_threshold": 0.2,
    }


def test_html_input_and_max_chars_bound_artifact_detection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        diagnostics,
        "build_repeated_line_signatures",
        lambda *_args, **_kwargs: set(),
    )
    monkeypatch.setattr(
        diagnostics,
        "drop_if_outline_only",
        lambda *_args, **_kwargs: SimpleNamespace(dropped=False),
    )
    monkeypatch.setattr(
        diagnostics,
        "drop_if_low_density",
        lambda *_args, **_kwargs: SimpleNamespace(dropped=False),
    )

    issues, patch = diagnostics.analyze_governance(
        "prefix<div>one</div><span>two</span><p>three</p>",
        "",
        input_format="html",
        max_chars=6,
    )

    assert issues == []
    assert patch == {}
