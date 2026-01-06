from app.rag.core.text import parse_json_from_text


def test_parse_json_from_text_expected_array_falls_back_to_lines():
    data, meta = parse_json_from_text("- hello\n- world\n", expected="array")

    assert data == ["hello", "world"]
    assert meta["ok"] is True
    assert meta["method"] == "lines"


def test_parse_json_from_text_expected_array_unwraps_common_wrapper():
    raw = '{"queries": ["q1", "q2"]}'
    data, meta = parse_json_from_text(raw, expected="array")

    assert data == ["q1", "q2"]
    assert meta["ok"] is True
    assert "wrapped:queries" in str(meta["method"])

