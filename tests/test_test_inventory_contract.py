from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_TEST_SUFFIXES = (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
IGNORED_WEB_DIRS = {"node_modules", ".next", ".next_build"}
CORE_E2E_TESTS = {
    "e2e/command-menu-document-view.spec.ts",
    "e2e/document-chat.smoke.spec.ts",
    "e2e/live-stack.smoke.spec.ts",
    "e2e/management-surfaces.smoke.spec.ts",
}


def _backend_test_files() -> list[Path]:
    return sorted((ROOT / "tests").rglob("test_*.py"))


def _frontend_test_files() -> list[Path]:
    return sorted(
        path
        for path in (ROOT / "web").rglob("*")
        if path.is_file()
        and not IGNORED_WEB_DIRS.intersection(path.parts)
        and path.name.endswith(WEB_TEST_SUFFIXES)
    )


def _makefile_paths(variable: str) -> set[str]:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    marker = f"{variable} :="

    for index, line in enumerate(lines):
        if not line.startswith(marker):
            continue

        paths: set[str] = set()
        for continuation in lines[index + 1 :]:
            stripped = continuation.strip()
            if not continuation.startswith("\t") or not stripped:
                break
            paths.add(stripped.removesuffix("\\").strip())
            if not stripped.endswith("\\"):
                break
        return paths

    raise AssertionError(f"{variable} is not declared in Makefile")


def _inventory_diff(actual: set[Path], expected: set[Path]) -> str:
    unexpected = sorted(path.relative_to(ROOT).as_posix() for path in actual - expected)
    missing = sorted(path.relative_to(ROOT).as_posix() for path in expected - actual)
    return f"unexpected={unexpected}; missing={missing}"


def test_repository_keeps_test_file_inventory_below_500() -> None:
    backend = _backend_test_files()
    frontend = _frontend_test_files()

    assert len(backend) + len(frontend) <= 500, (
        f"test inventory grew to {len(backend) + len(frontend)} files "
        f"(backend={len(backend)}, frontend={len(frontend)})"
    )


def test_repository_contains_only_declared_core_tests() -> None:
    backend = set(_backend_test_files())
    frontend = set(_frontend_test_files())
    expected_backend = {ROOT / path for path in _makefile_paths("CORE_TESTS")}
    expected_frontend = {
        *(ROOT / "web" / path for path in _makefile_paths("CORE_WEB_TESTS")),
        *(ROOT / "web" / path for path in CORE_E2E_TESTS),
    }

    assert backend == expected_backend, _inventory_diff(backend, expected_backend)
    assert frontend == expected_frontend, _inventory_diff(frontend, expected_frontend)


def test_core_test_files_remain_present() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    required = (
        "tests/test_auth_dependency_sets_request_state.py",
        "tests/test_parsing_extract_service.py",
        "tests/test_retrieval_fusion_budgeted_rrf.py",
        "tests/test_dify_external_knowledge_adapter.py",
        "tests/test_source_guard_contracts.py",
        "web/app/history/page.source.test.ts",
        "web/app/knowledge/knowledge-page.entry.test.ts",
        "web/app/evaluations/page.query.source.test.ts",
        "web/lib/api-runtime-contracts.test.ts",
    )

    for relative_path in required:
        assert (ROOT / relative_path).is_file(), relative_path
        assert relative_path.removeprefix("web/") in makefile
