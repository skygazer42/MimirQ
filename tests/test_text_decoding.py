from app.parsing.utils.text import read_text_file


def test_read_text_file_handles_utf8_bom(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"\xef\xbb\xbfhello")
    decoded = read_text_file(p)
    assert decoded.text == "hello"
    assert decoded.encoding == "utf-8"
    assert decoded.had_bom is True


def test_read_text_file_best_effort_non_utf8(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("café".encode("latin-1"))
    decoded = read_text_file(p)
    assert "café" in decoded.text

