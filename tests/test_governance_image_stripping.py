from app.rag.preprocessing.images import strip_images


def test_strip_images_all_removes_markdown_and_html_images():
    text = "A ![logo](logo.png) B <img src='x.png' alt='x'/> C"
    res = strip_images(text, mode="all")
    assert "![logo]" not in res.text
    assert "<img" not in res.text.lower()
    assert res.removed == 2


def test_strip_images_decorative_removes_logo_keeps_diagram():
    text = "![diagram](diagram.png)\n![logo](logo.png)\n"
    res = strip_images(text, mode="decorative")
    assert "diagram.png" in res.text
    assert "logo.png" not in res.text
    assert res.removed == 1


def test_strip_images_preserves_code_fences():
    text = "```md\n![logo](logo.png)\n```\n![logo](logo.png)\n"
    res = strip_images(text, mode="all")
    assert "```md\n![logo](logo.png)\n```" in res.text
    assert res.text.count("![logo](logo.png)") == 1
    assert res.removed == 1

