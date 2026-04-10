from __future__ import annotations


def test_parsing_openapi_schema_exposes_typed_elements_pages_field() -> None:
    from app.main import app  # noqa: WPS433

    schema = app.openapi()
    components = schema.get("components") or {}
    schemas = components.get("schemas") or {}
    element_schema = schemas.get("ParsingElementOut") or {}
    properties = element_schema.get("properties") or {}
    pages = properties.get("pages") or {}
    pages_any_of = pages.get("anyOf") if isinstance(pages, dict) else None
    pages_array = next((item for item in (pages_any_of or []) if isinstance(item, dict) and item.get("type") == "array"), {})

    assert element_schema.get("type") == "object"
    assert pages_array.get("type") == "array"
    assert (pages_array.get("items") or {}).get("type") == "integer"

    response_schema = schemas.get("ParsingContentResponse") or {}
    response_props = response_schema.get("properties") or {}
    elements = response_props.get("elements") or {}
    elements_any_of = elements.get("anyOf") if isinstance(elements, dict) else None
    elements_array = next((item for item in (elements_any_of or []) if isinstance(item, dict) and item.get("type") == "array"), {})
    assert elements_array.get("type") == "array"
    assert (elements_array.get("items") or {}).get("$ref") == "#/components/schemas/ParsingElementOut"
