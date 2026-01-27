from __future__ import annotations


def test_parse_csv_empty():
    from app.core.utils import parse_csv

    assert parse_csv(None) == []
    assert parse_csv("") == []
    assert parse_csv("   ") == []


def test_parse_csv_basic():
    from app.core.utils import parse_csv

    assert parse_csv("a,b,c") == ["a", "b", "c"]
    assert parse_csv(" a, b ,c ") == ["a", "b", "c"]
    assert parse_csv("a,,b, ,c") == ["a", "b", "c"]


def test_parse_csv_wildcard():
    from app.core.utils import parse_csv

    assert parse_csv("*") == ["*"]


def test_parse_csv_exported_in_all() -> None:
    import app.core.utils as utils

    assert "parse_csv" in getattr(utils, "__all__", [])

