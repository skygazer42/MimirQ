from __future__ import annotations

import io
import json
import zipfile

from app.api.v1.parsing import _extract_markdown_pair_from_documents, _sanitize_storage_value
from app.parsing.utils.mineru_layout import extract_position_tagged_markdown_from_zip_bytes


def test_extract_markdown_pair_prefers_position_tagged_metadata_for_original() -> None:
    original, cleaned = _extract_markdown_pair_from_documents(
        [
            {
                "page_content": "# Clean heading\n\nBody paragraph",
                "metadata": {
                    "position_tagged_markdown": "Heading@@1\t10\t20\t30\t40##\n\nBody@@1\t20\t30\t40\t50##",
                },
            },
            {
                "page_content": "## Next section",
                "metadata": {
                    "position_tagged_markdown": "Next@@2\t11\t21\t31\t41##",
                },
            },
        ]
    )

    assert cleaned == "# Clean heading\n\nBody paragraph\n\n## Next section"
    assert "Heading@@1\t10\t20\t30\t40##" in original
    assert "Next@@2\t11\t21\t31\t41##" in original


def test_extract_markdown_pair_removes_nul_chars_before_storage() -> None:
    original, cleaned = _extract_markdown_pair_from_documents(
        [
            {
                "page_content": "A\x00B@@1\t10\t20\t30\t40##",
                "metadata": {"position_tagged_markdown": "Tagged\x00Text@@1\t10\t20\t30\t40##"},
            }
        ]
    )

    assert "\x00" not in original
    assert "\x00" not in cleaned
    assert original == "TaggedText@@1\t10\t20\t30\t40##"
    assert cleaned == "AB@@1\t10\t20\t30\t40##"


def test_sanitize_storage_value_removes_nul_chars_recursively() -> None:
    sanitized = _sanitize_storage_value(
        {
            "bad\x00key": ["ok", "bad\x00value", {"nested": "x\x00y"}],
        }
    )

    assert sanitized == {"badkey": ["ok", "badvalue", {"nested": "xy"}]}


def test_extract_position_tagged_markdown_from_zip_bytes_uses_content_list_bbox() -> None:
    payload = [
        {"type": "text", "text": "Heading", "page_idx": 0, "bbox": [10, 20, 30, 40]},
        {"type": "image", "page_idx": 0, "bbox": [50, 60, 70, 80], "image_caption": [], "image_footnote": []},
        {
            "type": "table",
            "page_idx": 1,
            "bbox": [100, 110, 120, 130],
            "table_body": "<table><tr><td>A</td></tr></table>",
            "table_caption": ["Table caption"],
            "table_footnote": [],
        },
    ]

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("full.md", "# clean only")
        zf.writestr("sample_content_list.json", json.dumps(payload, ensure_ascii=False))

    tagged = extract_position_tagged_markdown_from_zip_bytes(buffer.getvalue())

    assert "Heading@@1\t10.0\t30.0\t20.0\t40.0##" in tagged
    assert "![Image](layout://image)@@1\t50.0\t70.0\t60.0\t80.0##" in tagged
    assert "<table><tr><td>A</td></tr></table>" in tagged
    assert "@@2\t100.0\t120.0\t110.0\t130.0##" in tagged


def test_extract_position_tagged_markdown_from_zip_bytes_normalizes_mineru_bbox_with_layout_page_size() -> None:
    payload = [
        {"type": "text", "text": "Heading", "page_idx": 0, "bbox": [250, 125, 750, 250]},
        {"type": "text", "text": "Body", "page_idx": 0, "bbox": [100, 500, 900, 900]},
    ]
    layout = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [612, 792],
            }
        ]
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("full.md", "# clean only")
        zf.writestr("sample_content_list.json", json.dumps(payload, ensure_ascii=False))
        zf.writestr("layout.json", json.dumps(layout, ensure_ascii=False))

    tagged = extract_position_tagged_markdown_from_zip_bytes(buffer.getvalue())

    assert "Heading@@1\t153.0\t459.0\t99.0\t198.0##" in tagged
    assert "Body@@1\t61.2\t550.8\t396.0\t712.8##" in tagged
