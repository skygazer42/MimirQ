from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_test_coverage_matrix.py"
    spec = importlib.util.spec_from_file_location("generate_test_coverage_matrix", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_matrix_discovers_backend_frontend_and_tests(tmp_path: Path) -> None:
    _write(
        tmp_path / "app" / "api" / "v1" / "__init__.py",
        """
from . import auth, reports

router.include_router(auth.router, prefix="/auth")
router.include_router(reports.router, prefix="/reports")
""".strip(),
    )
    _write(
        tmp_path / "app" / "api" / "v1" / "auth.py",
        """
@router.get("/me")
def get_me():
    return {}

@router.post("/login")
def login():
    return {}
""".strip(),
    )
    _write(
        tmp_path / "app" / "api" / "v1" / "reports.py",
        """
@router.get("/datasets/{dataset_id}")
def get_dataset_report():
    return {}
""".strip(),
    )
    _write(
        tmp_path / "web" / "lib" / "api" / "reports.ts",
        """
import { apiClient } from '@/lib/api/core'

export async function getDatasetReport(datasetId: string) {
  const { data } = await apiClient.get(`/reports/datasets/${datasetId}`)
  return data
}
""".strip(),
    )
    _write(tmp_path / "web" / "app" / "prompts" / "page.tsx", "export default function Page() { return null }\n")
    _write(tmp_path / "web" / "app" / "reports" / "page.tsx", "export default function Page() { return null }\n")
    _write(tmp_path / "tests" / "test_prompt_templates_endpoints.py", "def test_placeholder():\n    assert True\n")
    _write(tmp_path / "web" / "lib" / "api-client-management-surfaces.test.ts", "import { describe, it } from 'vitest'\n")
    _write(tmp_path / "web" / "e2e" / "management-surfaces.smoke.spec.ts", "import { test } from '@playwright/test'\n")

    module = _load_script_module()
    matrix = module.build_matrix(tmp_path)

    assert matrix["summary"]["backend_routes"] == 3
    assert matrix["summary"]["frontend_pages"] == 2
    assert matrix["summary"]["backend_tests"] == 1
    assert matrix["summary"]["frontend_tests"] == 1
    assert matrix["summary"]["playwright_specs"] == 1

    backend_keys = {(entry["method"], entry["path"]) for entry in matrix["backend_routes"]}
    assert ("GET", "/auth/me") in backend_keys
    assert ("POST", "/auth/login") in backend_keys
    assert ("GET", "/reports/datasets/{}") in backend_keys

    page_routes = [entry["route"] for entry in matrix["frontend_pages"]]
    assert page_routes == ["/prompts", "/reports"]

    markdown = module.render_markdown(matrix)
    assert "# Full-Stack Test Coverage Matrix" in markdown
    assert "`GET /auth/me`" in markdown
    assert "`/prompts`" in markdown
    assert "test_prompt_templates_endpoints.py" in markdown
