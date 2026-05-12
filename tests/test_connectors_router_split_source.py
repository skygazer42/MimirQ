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


def test_run_routes_are_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_runs.py")

    assert "connectors_runs" in connectors_source
    assert "router.routes.extend(connectors_runs.router.routes)" in connectors_source

    split_route_decorators = (
        '@router.post("/runs"',
        '@router.get("/runs"',
        '@router.get("/runs/{run_id}"',
        '@router.post("/runs/{run_id}/retry-failed"',
        '@router.post("/runs/{run_id}/resume"',
        '@router.post("/runs/{run_id}/cancel"',
    )
    for decorator in split_route_decorators:
        assert decorator not in connectors_source
        assert decorator in split_source


def test_connectors_router_still_exposes_run_routes() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/runs", ("POST",)) in routes
    assert ("/runs", ("GET",)) in routes
    assert ("/runs/{run_id}", ("GET",)) in routes
    assert ("/runs/{run_id}/retry-failed", ("POST",)) in routes
    assert ("/runs/{run_id}/resume", ("POST",)) in routes
    assert ("/runs/{run_id}/cancel", ("POST",)) in routes


def test_config_routes_are_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_configs.py")

    assert "connectors_configs" in connectors_source
    assert "router.routes.extend(connectors_configs.router.routes)" in connectors_source

    split_route_decorators = (
        '@router.get("/configs"',
        '@router.post("/configs"',
        '@router.put("/configs/{config_id}"',
        '@router.delete("/configs/{config_id}"',
        '@router.post("/configs/{config_id}/run"',
        '@router.post("/configs/{config_id}/reconcile"',
    )
    for decorator in split_route_decorators:
        assert decorator not in connectors_source
        assert decorator in split_source


def test_connectors_router_still_exposes_config_routes() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/configs", ("GET",)) in routes
    assert ("/configs", ("POST",)) in routes
    assert ("/configs/{config_id}", ("PUT",)) in routes
    assert ("/configs/{config_id}", ("DELETE",)) in routes
    assert ("/configs/{config_id}/run", ("POST",)) in routes
    assert ("/configs/{config_id}/reconcile", ("POST",)) in routes


def test_scheduled_tick_route_is_split_from_connectors_router() -> None:
    connectors_source = _source("app/api/v1/connectors.py")
    split_source = _source("app/api/v1/connectors_schedules.py")

    assert "connectors_schedules" in connectors_source
    assert "router.routes.extend(connectors_schedules.router.routes)" in connectors_source

    assert '@router.post("/scheduled/tick"' not in connectors_source
    assert '@router.post("/scheduled/tick"' in split_source


def test_connectors_router_still_exposes_scheduled_tick_route() -> None:
    from app.api.v1.connectors import router

    routes = {
        (getattr(route, "path", ""), tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in router.routes
    }

    assert ("/scheduled/tick", ("POST",)) in routes
