import ast
from pathlib import Path


def test_dify_integration_services_do_not_import_api_routes_or_dependencies() -> None:
    service_dir = Path(__file__).resolve().parents[1] / "app/services/dify"
    assert service_dir.is_dir()
    for path in sorted(service_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            assert all(
                not module.startswith("app.api") or module.startswith("app.api.schemas.") for module in modules
            ), f"{path} must not import API routes or dependencies: {modules}"
