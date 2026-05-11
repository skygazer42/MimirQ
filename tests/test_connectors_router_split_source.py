from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_catalog_route_is_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_catalog.py")

    assert "from app.api.v1 import connectors_catalog" in connectors_source
    assert "router.routes.extend(connectors_catalog.router.routes)" in connectors_source

    assert '@router.get("",' not in connectors_source
    assert '@router.get("")' in split_source


def test_connectors_router_still_exposes_catalog_route() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("", ("GET",)) in routes


def test_validate_route_is_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_validation.py")

    assert "from app.api.v1 import connectors_catalog, connectors_validation" in connectors_source
    assert "router.routes.extend(connectors_validation.router.routes)" in connectors_source

    assert '@router.post("/validate"' not in connectors_source
    assert '@router.post("/validate"' in split_source


def test_connectors_router_still_exposes_validate_route() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/validate", ("POST",)) in routes
