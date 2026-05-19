from app.main import _expand_dev_cors_origins


def test_expand_dev_cors_origins_adds_local_aliases_and_playwright_port():
    expanded = _expand_dev_cors_origins(["http://localhost:3000"])

    assert "http://localhost:3000" in expanded
    assert "http://127.0.0.1:3000" in expanded
    assert "http://0.0.0.0:3000" in expanded
    assert "http://localhost:3100" in expanded
    assert "http://127.0.0.1:3100" in expanded
    assert "http://0.0.0.0:3100" in expanded
