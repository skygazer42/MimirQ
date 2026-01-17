from app.rag.kg.extraction.parser import EntityValueParser


def test_normalize_name_nfkc_whitespace_and_quotes():
    p = EntityValueParser()
    assert p.normalize_name("  Alice  ") == "alice"
    assert p.normalize_name("“Alice”") == "alice"
    assert p.normalize_name("ＡＢＣ") == "abc"


def test_normalize_type_maps_common_aliases():
    p = EntityValueParser()
    assert p.normalize_type("") == "unknown"
    assert p.normalize_type(" person ") == "Person"
    assert p.normalize_type("公司") == "Organization"
    assert p.normalize_type("API") == "API"
    assert p.normalize_type("CustomType") == "CustomType"

