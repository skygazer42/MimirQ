from app.rag.preprocessing.code_blocks import strip_fenced_code_line_numbers


def test_strip_fenced_code_line_numbers_strips_numbered_blocks_and_preserves_indent():
    text = "\n".join(
        [
            "```python",
            "1 def foo():",
            "2     x = 1",
            "3     return x",
            "4     # blank",
            "5 print(foo())",
            "```",
        ]
    )
    res = strip_fenced_code_line_numbers(text)

    assert res.blocks_changed == 1
    assert res.lines_stripped == 5
    assert res.changed is True

    lines = res.text.splitlines()
    assert lines[1] == "def foo():"
    assert lines[2].startswith("    ")
    assert "x = 1" in lines[2]
    assert lines[3].startswith("    ")
    assert "return x" in lines[3]


def test_strip_fenced_code_line_numbers_does_not_touch_plain_text():
    text = "1 this is not code\n2 still not code"
    res = strip_fenced_code_line_numbers(text)
    assert res.text == text
    assert res.blocks_changed == 0
    assert res.lines_stripped == 0
    assert res.changed is False
