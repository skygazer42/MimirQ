import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_main_ci_runs_database_migrations_and_integrations() -> None:
    workflow = _read(".github/workflows/ci.yml")
    conftest = _read("tests/conftest.py")

    assert "MIMIRQ_INTEGRATION_TESTS: \"1\"" in workflow
    assert "make db-upgrade" in workflow
    assert "tests/test_core_schema_integration.py" in workflow
    assert "tests/test_document_version_diff_integration.py" in workflow
    assert "tests/test_document_versions_integration.py" in workflow
    assert "Base.metadata.create_all" not in conftest


def test_repo_checks_enforce_api_type_drift_and_shared_python_audit_policy() -> None:
    makefile = _read("Makefile")
    security_workflow = _read(".github/workflows/security.yml")

    assert (
        "node web/scripts/check-api-types-drift.mjs --strict "
        "--baseline web/scripts/api-types-drift-baseline.json"
    ) in makefile
    assert "make audit-py" in security_workflow


def test_main_ci_runs_all_browser_smoke_specs_and_critical_coverage() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "make test-web-e2e" in workflow
    assert "pnpm run test:coverage:critical" in workflow


def test_main_ci_uploads_the_generated_test_inventory() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "make test-matrix" in workflow
    assert "name: full-stack-test-inventory" in workflow
    assert "artifacts/test-coverage-matrix.json" in workflow
    assert "artifacts/test-coverage-matrix.md" in workflow
    assert "if-no-files-found: error" in workflow


def test_main_ci_routes_public_prs_to_hosted_smoke_checks() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "permissions:\n  contents: read" in workflow
    assert "public-pr-verify:" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "python ci/download_verified_wheels.py --cache-dir \"$TORCH_WHEEL_DIR\"" in workflow
    assert "make openapi-check" in workflow
    assert "make test" in workflow
    assert "make verify" in workflow
    assert "make test-web" in workflow
    assert "pnpm run build" in workflow
    for job in (
        "test-and-verify",
        "docker-build",
        "retrieval-only-bounded-gate",
        "retrieval-regression-gate",
        "kg-search-regression-gate",
    ):
        assert f"{job}:\n    if: github.event_name != 'pull_request'" in workflow


def test_pull_request_lint_and_security_jobs_use_hosted_runners() -> None:
    for workflow_path in (
        ".github/workflows/lint-fast.yml",
        ".github/workflows/security.yml",
    ):
        workflow = _read(workflow_path)
        assert "pull_request:" in workflow
        assert "runs-on: ubuntu-latest" in workflow
        assert "runs-on: [self-hosted" not in workflow
        assert "contents: read" in workflow


def test_api_docs_workflow_actually_deploys_pages() -> None:
    workflow = _read(".github/workflows/api-docs.yml")

    assert "pull_request:" in workflow
    assert "\n  build:\n" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "make api-docs-build-static" in workflow
    assert "actions/configure-pages@" in workflow
    assert "actions/upload-pages-artifact@" in workflow
    assert "actions/deploy-pages@" in workflow


def test_api_docs_pages_actions_are_gated_before_runner_setup() -> None:
    workflow = _read(".github/workflows/api-docs.yml")

    pr_build_job = workflow.split("\n  deploy:\n", 1)[0]
    assert "actions/configure-pages@" not in pr_build_job
    assert "actions/upload-pages-artifact@" not in pr_build_job
    assert "actions/deploy-pages@" not in pr_build_job
    assert "runs-on: [self-hosted" not in pr_build_job
    assert "\n  publish:\n" in workflow
    build_job, publish_job = workflow.split("\n  publish:\n", 1)
    assert "if: github.event_name != 'pull_request'" in build_job
    assert "needs: deploy" in publish_job
    assert "needs.deploy.outputs.pages_enabled == 'true'" in publish_job
    assert "pages: write" not in build_job
    assert "id-token: write" not in build_job
    assert "pages: write" in publish_job
    assert "id-token: write" in publish_job


def test_security_workflow_pins_trufflehog_by_digest() -> None:
    workflow = _read(".github/workflows/security.yml")

    assert (
        "trufflesecurity/trufflehog@sha256:c28ab4a11e01d6fcc10776f65cce015bdf9795f2393cffa2ec0a7c8464ee58b6"
        in workflow
    )


def test_fresh_database_migrations_widen_alembic_revision_storage() -> None:
    migration = _read("alembic/versions/0002_add_kg_relations.py")

    assert "ALTER TABLE alembic_version" in migration
    assert "VARCHAR(255)" in migration


def test_backend_dockerfile_uses_bundled_buildkit_frontend() -> None:
    dockerfile = _read("docker/Dockerfile")

    assert not dockerfile.lstrip().startswith("# syntax=docker/dockerfile:")


def test_cpu_torch_wheels_match_linux_runtime_requirements() -> None:
    requirements = _read("requirements.txt")
    torch_version = re.search(
        r'^torch==([^;]+); platform_system == "Linux"$', requirements, re.MULTILINE
    )
    torchvision_version = re.search(
        r'^torchvision==([^;]+); platform_system == "Linux"$', requirements, re.MULTILINE
    )

    assert torch_version is not None
    assert torchvision_version is not None
    for install_surface in ("docker/Dockerfile", ".github/workflows/ci.yml"):
        content = _read(install_surface)
        assert set(re.findall(r"\btorch-([0-9.]+)\+cpu-", content)) == {
            torch_version.group(1)
        }
        assert set(re.findall(r"\btorchvision-([0-9.]+)\+cpu-", content)) == {
            torchvision_version.group(1)
        }


def test_docker_ci_supports_cold_web_builds() -> None:
    workflow = _read(".github/workflows/ci.yml")
    docker_job = workflow.split("\n  docker-build:", 1)[1].split(
        "\n  retrieval-only-bounded-gate:", 1
    )[0]
    retrieval_compose = _read("docker/docker-compose.retrieval-dev.yml")
    web_dockerfile = _read("web/Dockerfile.prod")

    assert "timeout-minutes: 60" in docker_job
    assert "target=/root/.local/share/pnpm/store" in web_dockerfile
    assert "https://registry.npmmirror.com" in web_dockerfile
    assert "Smoke built backend and web images" in docker_job
    assert "up -d --no-build" in docker_job
    assert "if: always()" in docker_job
    assert "image: ${MIMIRQ_BACKEND_IMAGE:-mimirq-backend}" in retrieval_compose


def test_dockerfiles_bypass_broken_docker_hub_mirror() -> None:
    backend_dockerfile = _read("docker/Dockerfile")
    web_dockerfile = _read("web/Dockerfile.prod")

    assert re.search(
        r"^ARG PYTHON_BASE_IMAGE=public\.ecr\.aws/docker/library/python:3\.11-slim@sha256:[0-9a-f]{64}$",
        backend_dockerfile,
        re.MULTILINE,
    )
    assert "FROM ${PYTHON_BASE_IMAGE} AS base" in backend_dockerfile
    assert re.search(
        r"^ARG NODE_BASE_IMAGE=public\.ecr\.aws/docker/library/node:20-alpine@sha256:[0-9a-f]{64}$",
        web_dockerfile,
        re.MULTILINE,
    )
    assert "FROM ${NODE_BASE_IMAGE} AS base" in web_dockerfile
