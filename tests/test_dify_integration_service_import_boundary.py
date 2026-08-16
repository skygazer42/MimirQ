import ast
from pathlib import Path


def test_dify_integration_services_do_not_import_api_modules() -> None:
    service_dir = Path("app/services/dify_integration")
    for path in sorted(service_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            assert all(not module.startswith("app.api") for module in modules), (
                f"{path} must not import API-layer modules: {modules}"
            )
