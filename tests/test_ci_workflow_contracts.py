import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _assert_uses_self_hosted_bootstrap(workflow: str, command: str, *, count: int) -> None:
    assert workflow.count(command) == count
    assert "python3.11/python3 not found on self-hosted runner" not in workflow
    assert 'if [ -d "$PY_BIN" ]; then' not in workflow
    assert 'echo "PIP_CACHE_DIR=$PIP_CACHE_DIR_VALUE"' not in workflow


def test_self_hosted_ci_bootstrap_script_contract() -> None:
    script = _read("scripts/prepare_self_hosted_ci.sh")

    assert script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "--include-torch-wheel-dir" in script
    assert 'PY_BIN="$(command -v python3.11 || true)"' in script
    assert 'CACHE_ROOT="${RUNNER_TOOL_CACHE:-$RUNNER_TEMP}/mimirq"' in script
    assert 'VENV_DIR="${SELF_HOSTED_VENV_DIR:-$CACHE_ROOT/python-3.11}"' in script
    assert 'PIP_CACHE_DIR_VALUE="${PIP_CACHE_DIR:-$CACHE_ROOT/pip}"' in script
    assert 'TORCH_WHEEL_DIR_VALUE="${TORCH_WHEEL_DIR:-$CACHE_ROOT/torch-wheels}"' in script
    assert 'echo "$VENV_DIR/bin" >> "$GITHUB_PATH"' in script
    assert 'echo "PIP_INDEX_URL=${PIP_INDEX_URL:-https://pypi.org/simple}"' in script
    assert 'echo "PIP_CACHE_DIR=$PIP_CACHE_DIR_VALUE"' in script
    assert 'echo "TORCH_WHEEL_DIR=$TORCH_WHEEL_DIR_VALUE"' in script
    assert 'echo "NO_PROXY=$NO_PROXY_VALUE"' in script
    assert 'HTTP_PROXY_VALUE="${SELF_HOSTED_HTTP_PROXY:-${HTTP_PROXY:-${http_proxy:-}}}"' in script
    assert 'HTTPS_PROXY_VALUE="${SELF_HOSTED_HTTPS_PROXY:-${HTTPS_PROXY:-${https_proxy:-}}}"' in script
    assert 'ALL_PROXY_VALUE="${ALL_PROXY:-${all_proxy:-}}"' in script
    assert 'PY_BIN="$(uv python find 3.11 2>/dev/null || true)"' in script
    assert 'if [ "$PY_VERSION" != "3.11" ]; then' in script
    assert "command -v python3 || true" not in script
    assert "/home/user/.local/share/uv" not in script
    assert "/data/actions-runner" not in script
    assert "127.0.0.1:35983" not in script


def test_self_hosted_python_jobs_allow_a_cold_cache_fill() -> None:
    workflow = _read(".github/workflows/ci.yml")

    expected_timeouts = {
        "test-and-verify": 90,
        "retrieval-only-bounded-gate": 60,
        "retrieval-regression-gate": 60,
        "kg-search-regression-gate": 60,
    }
    for job_name, timeout_minutes in expected_timeouts.items():
        pattern = rf"(?s)\n  {re.escape(job_name)}:\n.*?\n    timeout-minutes: {timeout_minutes}\n"
        assert re.search(pattern, workflow), job_name


def test_ci_seed_entrypoints_bootstrap_the_repository_before_app_imports() -> None:
    for relative_path in (
        "scripts/seed_ci_retrieval_regression.py",
        "scripts/seed_ci_kg_search_regression.py",
    ):
        script = _read(relative_path)
        bootstrap = "sys.path.insert(0, str(REPO_ROOT))"
        assert "REPO_ROOT = Path(__file__).resolve().parents[1]" in script
        assert bootstrap in script
        assert script.index(bootstrap) < script.index("import app.models._all")

    workflow = _read(".github/workflows/ci.yml")
    for step_name in (
        "Seed CI retrieval fixture (DB + cases bundle)",
        "Seed CI KG search fixture (DB + KG rows + cases bundle)",
    ):
        step = workflow.split(f"- name: {step_name}", 1)[1].split("\n      - name:", 1)[0]
        assert "ENV: ci" in step
        assert "AUTH_MODE: header" in step

    retrieval_job = workflow.split("\n  retrieval-regression-gate:\n", 1)[1].split(
        "\n  kg-search-regression-gate:\n", 1
    )[0]
    kg_job = workflow.split("\n  kg-search-regression-gate:\n", 1)[1]
    for job, log_path in (
        (retrieval_job, "artifacts/backend.log"),
        (kg_job, "artifacts/kg-backend.log"),
    ):
        assert f"> {log_path} 2>&1 &" in job
        assert "for i in $(seq 1 120); do" in job
        assert 'if ! kill -0 "$backend_pid" 2>/dev/null; then' in job
        assert "backend exited before becoming ready" in job
        assert f"tail -200 {log_path}" in job

    assert "id: backend_ready" in retrieval_job
    assert "if: always() && steps.backend_ready.outcome == 'success'" in retrieval_job


def test_retrieval_only_job_uses_the_non_jwt_ci_runtime() -> None:
    workflow = _read(".github/workflows/ci.yml")
    job = workflow.split("\n  retrieval-only-bounded-gate:\n", 1)[1].split("\n  retrieval-regression-gate:\n", 1)[0]

    assert "    env:\n      ENV: ci\n      AUTH_MODE: header\n" in job


def test_grounded_strict_ci_contract_preserves_the_configured_reranker() -> None:
    workflow = _read(".github/workflows/ci.yml")
    step = workflow.split("- name: Validate grounded_strict retrieval-profile contract", 1)[1].split(
        "\n      - name:", 1
    )[0]

    assert 'configured_reranker_provider = "llm"' in step
    assert "reranker_provider=configured_reranker_provider" in step
    assert '"reranker_provider": configured_reranker_provider' in step
    assert 'reranker_provider="none"' in step
    assert 'fallback_applied.get("reranker_provider") != "cross_encoder"' in step
    assert '"fallback_applied": fallback_applied' in step


def test_public_pr_live_core_gate_launcher_contract() -> None:
    script = _read("scripts/run_ci_live_core_gate.sh")

    assert script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert ': "${DATABASE_URL:?DATABASE_URL is required}"' in script
    assert ': "${REDIS_URL:?REDIS_URL is required}"' in script
    assert 'PRIMARY_PORT="${CI_LIVE_CORE_PRIMARY_PORT:-8000}"' in script
    assert 'SECONDARY_PORT="${CI_LIVE_CORE_SECONDARY_PORT:-8001}"' in script
    assert 'PRIMARY_LOG="artifacts/live-core-primary.log"' in script
    assert 'SECONDARY_LOG="artifacts/live-core-secondary.log"' in script
    assert 'export AUTH_MODE="${AUTH_MODE:-header}"' in script
    assert 'export VECTOR_BACKEND="${VECTOR_BACKEND:-faiss}"' in script
    assert 'export MINIO_ENABLED="${MINIO_ENABLED:-false}"' in script
    assert 'export UPLOAD_DEDUP_ENABLED="${UPLOAD_DEDUP_ENABLED:-true}"' in script
    assert 'export DIFY_EXTERNAL_KNOWLEDGE_ENABLED="false"' in script
    assert 'export DIFY_EXTERNAL_KNOWLEDGE_WARMUP_ENABLED="false"' in script
    assert 'export DIFY_EXTERNAL_KNOWLEDGE_WARMUP_REQUIRED_FOR_READY="false"' in script
    assert 'export RAG_RUNTIME_WARMUP_ENABLED="false"' in script
    assert 'export RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY="false"' in script
    assert (
        'export RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED="${RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED:-true}"'
        in script
    )
    assert 'export DATASET_ANALYSIS_PNG_STALE_AFTER_SEC="${DATASET_ANALYSIS_PNG_STALE_AFTER_SEC:-2}"' in script
    assert 'python -m uvicorn app.main:app --host 127.0.0.1 --port "$PRIMARY_PORT"' in script
    assert 'python -m uvicorn app.main:app --host 127.0.0.1 --port "$SECONDARY_PORT"' in script
    assert 'python scripts/api_ping.py --base-url "$base_url" >/dev/null' in script
    assert "python scripts/live_core_release_gate.py \\" in script
    assert '--base-url "http://127.0.0.1:${PRIMARY_PORT}" \\' in script
    assert '--secondary-base-url "http://127.0.0.1:${SECONDARY_PORT}" \\' in script
    assert '--out "$OUT_PATH"' in script


def test_main_ci_runs_database_migrations_and_integrations() -> None:
    workflow = _read(".github/workflows/ci.yml")
    conftest = _read("tests/conftest.py")

    assert 'MIMIRQ_INTEGRATION_TESTS: "1"' in workflow
    assert "make db-upgrade" in workflow
    assert workflow.count("SECRET_KEY: ci-db-upgrade-secret-key-0123456789") == 2
    assert "tests/test_alembic_upgrade_from_prior_revision.py" in workflow
    assert "tests/test_core_schema_integration.py" in workflow
    assert "tests/test_document_version_diff_integration.py" in workflow
    assert "tests/test_document_versions_integration.py" in workflow
    assert "Base.metadata.create_all" not in conftest


def test_repo_checks_enforce_api_type_drift_and_shared_python_audit_policy() -> None:
    makefile = _read("Makefile")
    security_workflow = _read(".github/workflows/security.yml")
    python_audit = makefile.split("audit-py:", 1)[1].split("audit-web:", 1)[0]

    assert (
        "node web/scripts/check-api-types-drift.mjs --strict --baseline web/scripts/api-types-drift-baseline.json"
    ) in makefile
    assert "make audit-py" in security_workflow
    assert "--no-deps" not in python_audit
    assert "PIP_DEFAULT_TIMEOUT=60" in python_audit
    assert "--timeout 60" in python_audit
    assert "--index-url https://pypi.org/simple" in python_audit
    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in python_audit
    for advisory in (
        "PYSEC-2026-311",
        "PYSEC-2026-3046",
        "PYSEC-2026-2447",
        "CVE-2026-45830",
        "CVE-2026-45831",
        "CVE-2026-45833",
        "PYSEC-2026-1325",
    ):
        assert f"--ignore-vuln {advisory}" in python_audit


def test_python_audit_chroma_exception_stays_bound_to_the_embedded_local_backend() -> None:
    makefile = _read("Makefile")
    vector_factory = _read("app/storage/vector/factory.py")
    helm_validation = _read("deploy/helm/mimirq/templates/validate-runtime.yaml")
    chroma_backend = vector_factory.split("class ChromaVectorStore(BaseVectorStore):", 1)[1].split(
        "\n\n_VECTOR_STORE_SINGLETONS:", 1
    )[0]

    assert "embedded local LangChain Chroma path" in makefile
    assert "Chroma HTTP or RBAC APIs" in makefile
    assert '"collection_name": key' in chroma_backend
    assert 'kwargs["persist_directory"] = self.persist_path' in chroma_backend
    assert "HttpClient" not in chroma_backend
    assert "host=" not in chroma_backend
    assert "port=" not in chroma_backend
    assert "headers=" not in chroma_backend
    assert "Distributed MimirQ deployments cannot use VECTOR_BACKEND=faiss or VECTOR_BACKEND=chroma." in (
        helm_validation
    )


def test_dependency_audit_covers_web_and_handbook_with_shared_policy() -> None:
    makefile = _read("Makefile")
    powershell_audit = _read("scripts/audit.ps1")
    security_workflow = _read(".github/workflows/security.yml")

    assert "audit-docs:" in makefile
    assert "cd web && pnpm audit --prod --audit-level high" in makefile
    assert "cd web && pnpm audit --audit-level high" in makefile
    assert "pnpm --dir web audit" not in makefile
    assert "scripts/check_pnpm_audit.py" not in makefile
    assert "--ignore-registry-errors" not in makefile
    assert "npm audit --audit-level=high --json" in makefile
    assert "scripts/check_npm_audit.py" in makefile
    assert "npm audit --omit=dev" not in makefile
    assert "$(MAKE) audit-web" in makefile
    assert "$(MAKE) audit-docs" in makefile
    assert "run: make audit-web" in security_workflow
    assert "run: make audit-docs" in security_workflow
    assert (
        "npm --prefix docs-site audit --audit-level=high --json | python scripts/check_npm_audit.py" in powershell_audit
    )
    assert powershell_audit.count("Assert-AuditSucceeded") == 5


def test_main_ci_runs_all_browser_smoke_specs_and_critical_coverage() -> None:
    workflow = _read(".github/workflows/ci.yml")
    web_job = workflow.split("\n  web-test-and-verify:\n", 1)[1].split("\n  docker-build:", 1)[0]

    assert "make test-web-e2e" in web_job
    assert "pnpm run test:coverage:critical" in web_job
    assert "make test-web" in web_job
    assert "pnpm install --frozen-lockfile" in web_job
    assert "pnpm exec playwright install chromium" in web_job
    assert "clean: true" in web_job
    assert "runs-on: [self-hosted, Linux, X64, mimirq]" in web_job
    assert "PLAYWRIGHT_LIVE_STACK" not in web_job
    # The web job is intentionally frontend-only: no Python dep install, no needs
    # chain, so it runs in parallel with the backend test-and-verify job.
    assert "needs:" not in web_job
    assert "filter_cpu_ci_requirements.py" not in web_job
    backend_job = workflow.split("\n  test-and-verify:\n", 1)[1].split("\n  web-test-and-verify:\n", 1)[0]
    assert "make test-web-e2e" not in backend_job
    assert "pnpm run test:coverage:critical" not in backend_job
    assert "make test\n" in backend_job
    assert "make test-matrix" in backend_job
    assert "make verify" in backend_job


def test_main_ci_host_browser_smoke_stays_on_the_live_stack_spec_in_pr_jobs_too() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "README host browser smoke" in workflow
    assert "pnpm exec playwright test e2e/live-stack.smoke.spec.ts" in workflow
    retrieval_regression_job = workflow.split("\n  retrieval-regression-gate:\n", 1)[1].split(
        "\n  kg-search-regression-gate:\n",
        1,
    )[0]
    assert "AUTH_MODE: header" in retrieval_regression_job
    assert "README host browser smoke" in retrieval_regression_job
    assert 'PLAYWRIGHT_LIVE_STACK: "1"' in retrieval_regression_job
    assert "NEXT_PUBLIC_USER_ID: ci-bot" in retrieval_regression_job
    assert "NEXT_PUBLIC_TENANT_ID: 00000000-0000-0000-0000-000000000000" in retrieval_regression_job
    browser_smoke = retrieval_regression_job.split("- name: README host browser smoke", 1)[1].split(
        "- name: README host quickstart smoke",
        1,
    )[0]
    assert 'NEXT_PUBLIC_API_URL="/"' in browser_smoke
    assert 'API_INTERNAL_URL="http://127.0.0.1:${MIMIRQ_RETRIEVAL_API_PORT}"' in browser_smoke
    assert 'NEXT_PUBLIC_API_URL="http://127.0.0.1:${MIMIRQ_RETRIEVAL_API_PORT}"' not in browser_smoke
    assert "pnpm exec playwright test e2e/live-stack.smoke.spec.ts" in retrieval_regression_job


def test_retrieval_regression_gate_is_offline_and_reuses_bounded_proof_artifacts() -> None:
    workflow = _read(".github/workflows/ci.yml")
    bounded_gate_job = workflow.split("\n  retrieval-only-bounded-gate:\n", 1)[1].split(
        "\n  retrieval-regression-gate:\n",
        1,
    )[0]
    retrieval_regression_job = workflow.split("\n  retrieval-regression-gate:\n", 1)[1].split(
        "\n  kg-search-regression-gate:\n",
        1,
    )[0]
    upload_step = bounded_gate_job.split("- name: Upload bounded gate artifacts", 1)[1]
    download_step = retrieval_regression_job.split("- name: Download bounded gate artifacts", 1)[1].split(
        "\n      - name:",
        1,
    )[0]
    backend_step = retrieval_regression_job.split("- name: Start backend (no external deps)", 1)[1].split(
        "\n      - name:",
        1,
    )[0]
    release_gate_step = retrieval_regression_job.split("- name: Release gate (SLO + cost budgets)", 1)[1].split(
        "\n      - name:",
        1,
    )[0]

    assert "name: retrieval-only-bounded-gate" in upload_step
    assert "artifacts/parsing_proof_broader_sample/summary.json" in upload_step
    assert "artifacts/parsing_proof_broader_sample/diff.json" in upload_step
    assert "name: retrieval-only-bounded-gate" in download_step
    assert "path: bounded_gate_artifacts" in download_step
    assert "EMBEDDING_PROVIDER: deterministic_test" in backend_step
    assert "EMBEDDING_MODEL: mimirq-deterministic-test-v1" in backend_step
    assert 'LLM_MOCK_ENABLED: "true"' in backend_step
    assert "RERANKER_PROVIDER: pc" in backend_step
    assert (
        "--parsing-proof-summary "
        "bounded_gate_artifacts/artifacts/parsing_proof_broader_sample/summary.json" in release_gate_step
    )
    assert (
        "--parsing-proof-diff "
        "bounded_gate_artifacts/artifacts/parsing_proof_broader_sample/diff.json" in release_gate_step
    )


def test_retrieval_regression_gate_requires_strict_provenance_integrity() -> None:
    workflow = _read(".github/workflows/ci.yml")
    retrieval_regression_job = workflow.split("\n  retrieval-regression-gate:\n", 1)[1].split(
        "\n  kg-search-regression-gate:\n",
        1,
    )[0]
    provenance_gate_step = retrieval_regression_job.split("- name: Must-recall + provenance gate", 1)[1].split(
        "\n      - name:",
        1,
    )[0]

    assert "--strict-integrity" in provenance_gate_step


def test_main_ci_uploads_the_generated_test_inventory() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "make test-matrix" in workflow
    assert "name: full-stack-test-inventory" in workflow
    assert "artifacts/test-coverage-matrix.json" in workflow
    assert "artifacts/test-coverage-matrix.md" in workflow
    assert "if-no-files-found: error" in workflow


def test_main_ci_routes_public_prs_to_hosted_smoke_checks() -> None:
    workflow = _read(".github/workflows/ci.yml")
    public_pr_job = workflow.split("\n  test-and-verify:\n", 1)[0]
    checkout_proxy = (
        "        env:\n"
        "          http_proxy: ${{ vars.CI_HTTP_PROXY || '' }}\n"
        "          https_proxy: ${{ vars.CI_HTTPS_PROXY || '' }}\n"
        "          no_proxy: ${{ vars.CI_NO_PROXY != '' && "
        "format('127.0.0.1,localhost,{0}', vars.CI_NO_PROXY) || "
        "'127.0.0.1,localhost' }}\n"
    )

    assert "permissions:\n  contents: read" in workflow
    assert "SELF_HOSTED_PYTHON_BIN: ${{ vars.CI_SELF_HOSTED_PYTHON_BIN || '' }}" in workflow
    assert "SELF_HOSTED_VENV_DIR: ${{ vars.CI_SELF_HOSTED_VENV_DIR || '' }}" in workflow
    assert "PIP_INDEX_URL: ${{ vars.CI_PIP_INDEX_URL || 'https://pypi.org/simple' }}" in workflow
    assert "PIP_CACHE_DIR: ${{ vars.CI_PIP_CACHE_DIR || '' }}" in workflow
    assert "TORCH_WHEEL_DIR: ${{ vars.CI_TORCH_WHEEL_DIR || '' }}" in workflow
    assert "SELF_HOSTED_HTTP_PROXY: ${{ vars.CI_HTTP_PROXY || '' }}" in workflow
    assert "SELF_HOSTED_HTTPS_PROXY: ${{ vars.CI_HTTPS_PROXY || '' }}" in workflow
    assert "SELF_HOSTED_NO_PROXY: ${{ vars.CI_NO_PROXY || '' }}" in workflow
    _assert_uses_self_hosted_bootstrap(
        workflow,
        "bash scripts/prepare_self_hosted_ci.sh --include-torch-wheel-dir",
        count=4,
    )
    assert "runner.name == 'mimirq-main-01'" not in workflow
    assert "/home/user/.local/share/uv" not in workflow
    assert "/data/actions-runner" not in workflow
    assert "127.0.0.1:35983" not in workflow
    assert "docker build --network host" in workflow
    assert workflow.count("docker build --network host") == 1
    assert "uses: docker/setup-buildx-action@37fe631027851001ddb9b187196cc803df7f5f0e # v4" in workflow
    assert "uses: docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a # v7" in workflow
    assert "Prepare Docker build proxy" in workflow
    assert '"${SELF_HOSTED_HTTP_PROXY:-${HTTP_PROXY:-}}"' in workflow
    assert '"${SELF_HOSTED_HTTPS_PROXY:-${HTTPS_PROXY:-}}"' in workflow
    assert "printf 'DOCKER_BUILD_NETWORK=host\\n'" in workflow
    assert workflow.count(checkout_proxy) == 6
    assert "http_proxy: ${{ vars.CI_HTTP_PROXY || '' }}" not in public_pr_job
    assert "https_proxy: ${{ vars.CI_HTTPS_PROXY || '' }}" not in public_pr_job
    assert "public-pr-verify:" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert "redis:\n        image: redis:7-alpine" in public_pr_job
    # Hosted PR job caching: stable cache paths + pip/pnpm/torch-wheel/Playwright caches.
    assert "PIP_CACHE_DIR: /home/runner/.cache/pip" in public_pr_job
    assert "TORCH_WHEEL_DIR: /home/runner/.cache/torch-wheels" in public_pr_job
    assert "${{ runner.temp }}/pip-cache" not in workflow
    assert "${{ runner.temp }}/torch-wheels" not in workflow
    assert "corepack enable" not in public_pr_job
    assert "uses: pnpm/action-setup@fc06bc1257f339d1d5d8b3a19a8cae5388b55320 # v4.4.0" in public_pr_job
    assert "package_json_file: web/package.json" in public_pr_job
    assert "cache: pip" in public_pr_job
    assert "cache-dependency-path: |\n            requirements.txt\n            requirements-dev.txt" in public_pr_job
    assert "cache: pnpm" in public_pr_job
    assert "cache-dependency-path: web/pnpm-lock.yaml" in public_pr_job
    assert public_pr_job.count("uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830 # v4.3.0") == 2
    assert "path: /home/runner/.cache/torch-wheels" in public_pr_job
    assert (
        "key: torch-wheels-${{ runner.os }}-py311-${{ hashFiles('ci/download_verified_wheels.py') }}" in public_pr_job
    )
    assert "path: /home/runner/.cache/ms-playwright" in public_pr_job
    assert "key: playwright-${{ runner.os }}-${{ hashFiles('web/pnpm-lock.yaml') }}" in public_pr_job
    assert 'python ci/download_verified_wheels.py --cache-dir "$TORCH_WHEEL_DIR"' in workflow
    assert "command -v rg" in workflow
    assert "rg --version | head -n 1" in workflow
    assert "make openapi-check" in workflow
    assert "cp .env.example .env" in workflow
    assert "docker compose --env-file .env -f docker/docker-compose.yml config --quiet" in workflow
    assert (
        "docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.web.yml config --quiet"
        in workflow
    )
    assert (
        'docker run --rm -v "$PWD:/work" -w /work '
        "alpine/helm@sha256:"
        "aef9b56f64e866207d9591d0abd8f6d767b36aadd12edf68f8a719716d9d29c9 "
        "lint deploy/helm/mimirq" in workflow
    )
    assert "template mimirq deploy/helm/mimirq >/dev/null" in workflow
    assert "make test" in workflow
    assert "PR deterministic retrieval-ranking proxy gate" in workflow
    assert "scripts/run_sample_retrieval_benchmark.py" in workflow
    assert "scripts/build_rag_quality_gate_artifacts.py" in workflow
    assert "data/sample/retrieval_fixture_hybrid_v1.json" in workflow
    assert "--retrieval-mode hybrid" in workflow
    assert "tests/rag/evaluation/test_rag_quality_gate.py" in workflow
    assert "artifacts/retrieval_ranking_proxy.summary.json" in workflow
    assert "artifacts/retrieval_ranking_proxy_gate.report.json" in workflow
    assert "PR hosted live core gate" in workflow
    assert "bash scripts/run_ci_live_core_gate.sh artifacts/live-core-release-gate.pr.json" in workflow
    assert "REDIS_URL: redis://127.0.0.1:${{ job.services.redis.ports['6379'] }}/0" in workflow
    assert "Upload PR live core gate artifacts" in workflow
    assert "name: public-pr-live-core-gate" in workflow
    assert "artifacts/live-core-release-gate.pr.json" in workflow
    assert "artifacts/live-core-primary.log" in workflow
    assert "artifacts/live-core-secondary.log" in workflow
    assert "make verify" in workflow
    assert "make test-web" in workflow
    assert "pnpm run build" in workflow
    assert "Install Playwright browsers for PR browser smoke" in public_pr_job
    assert "pnpm exec playwright install --with-deps chromium" in public_pr_job
    assert "PR hosted browser smoke" in public_pr_job
    assert 'PLAYWRIGHT_REUSE_BUILD: "1"' in public_pr_job
    assert "pnpm exec playwright test e2e/document-chat.smoke.spec.ts" in public_pr_job
    assert re.search(r"(?m)^\s+HTTP_PROXY: \$\{\{ vars\.CI_HTTP_PROXY", workflow) is None
    assert re.search(r"(?m)^\s+HTTPS_PROXY: \$\{\{ vars\.CI_HTTPS_PROXY", workflow) is None
    for job in (
        "test-and-verify",
        "web-test-and-verify",
        "docker-build",
        "kg-search-regression-gate",
    ):
        assert f"{job}:\n    if: github.event_name != 'pull_request'" in workflow
    for job in ("retrieval-only-bounded-gate", "retrieval-regression-gate"):
        assert f"{job}:\n    if: github.event_name != 'pull_request'" not in workflow


def test_ci_backend_full_suite_runs_pytest_xdist_in_parallel() -> None:
    makefile = _read("Makefile")
    requirements_dev = _read("requirements-dev.txt")
    workflow = _read(".github/workflows/ci.yml")

    # Both full backend suite runs in ci.yml go through `make test`, which is
    # parallelized with pytest-xdist (`-n auto`).
    assert "$(PY) -m pytest -q -n auto $(PYTEST_ARGS)" in makefile
    assert "pytest-xdist==3.8.0" in requirements_dev
    # Both jobs install the complete dev set; xgboost-cpu keeps the dependency
    # graph CPU-only without filtering requirements or bypassing pip metadata.
    assert workflow.count("python -m pip install --retries 10 --timeout 120 -r requirements-dev.txt") == 2
    assert "filter_cpu_ci_requirements.py" not in workflow
    assert "--no-deps xgboost" not in workflow
    assert workflow.count("run: make test\n") == 2


def test_host_setup_uses_project_venv_and_complete_cpu_dependencies() -> None:
    makefile = _read("Makefile")
    requirements = _read("requirements.txt")
    dockerfile = _read("docker/Dockerfile")
    compose = _read("docker/docker-compose.yml")
    env_example = _read(".env.example")

    assert "VENV_READY" not in makefile
    assert "ifneq ($(wildcard $(VENV_PY)),)" in makefile
    assert "$(VENV_PY) -m pip check" in makefile
    assert "cd web && pnpm install" in makefile
    assert 'xgboost-cpu==3.2.0; platform_system == "Linux"' in requirements
    assert "filter_cpu_ci_requirements.py" not in dockerfile
    assert "--no-deps" not in dockerfile
    assert "${MILVUS_IMAGE:-milvusdb/milvus:v2.6.11}" in compose
    assert "MIMIRQ_SMOKE_IDENTIFIER=" in env_example
    assert "MIMIRQ_SMOKE_PASSWORD=" in env_example
    assert "PNPM_REGISTRY=https://registry.npmmirror.com" in env_example

    for readme_path in ("README.md", "README_EN.md", "README_JA.md", "README_KO.md"):
        readme = _read(readme_path)
        assert "git clone --depth 1 --single-branch" in readme
        assert "make setup-host" in readme
        assert "pnpm -C web install" not in readme

    assert "make core-e2e CORE_E2E_BASE_URL=http://127.0.0.1:8000 CORE_E2E_BOOTSTRAP_REGISTER=1" not in _read(
        "README.md"
    )
    assert "make core-e2e CORE_E2E_BASE_URL=http://127.0.0.1:8000 CORE_E2E_BOOTSTRAP_REGISTER=1" not in _read(
        "docs/quickstart.md"
    )


def test_pull_request_lint_and_security_jobs_use_hosted_runners() -> None:
    runner_policy = "runs-on: ${{ github.event_name == 'pull_request' && 'ubuntu-latest' || 'mimirq' }}"
    expected_counts = {
        ".github/workflows/lint-fast.yml": 1,
        ".github/workflows/security.yml": 2,
    }

    for workflow_path, expected_count in expected_counts.items():
        workflow = _read(workflow_path)
        assert "pull_request:" in workflow
        assert workflow.count(runner_policy) == expected_count
        assert "runs-on: [self-hosted" not in workflow
        assert "contents: read" in workflow
        assert "github.event_name != 'pull_request' && vars.CI_HTTP_PROXY" in workflow
        assert "github.event_name != 'pull_request' && vars.CI_HTTPS_PROXY" in workflow
        assert "if: ${{ runner.environment == 'github-hosted' }}" in workflow
        assert "if: ${{ runner.environment == 'self-hosted' }}" in workflow
        assert "run: bash scripts/prepare_self_hosted_ci.sh" in workflow
        assert "Prepare self-hosted Node" in workflow


def test_api_docs_workflow_actually_deploys_pages() -> None:
    workflow = _read(".github/workflows/api-docs.yml")
    hosted_build = workflow.split("\n  deploy:\n", 1)[0]
    checkout_proxy = (
        "        env:\n"
        "          http_proxy: ${{ vars.CI_HTTP_PROXY || '' }}\n"
        "          https_proxy: ${{ vars.CI_HTTPS_PROXY || '' }}\n"
        "          no_proxy: ${{ vars.CI_NO_PROXY != '' && "
        "format('127.0.0.1,localhost,{0}', vars.CI_NO_PROXY) || "
        "'127.0.0.1,localhost' }}\n"
    )

    assert "pull_request:" in workflow
    assert "SELF_HOSTED_PYTHON_BIN: ${{ vars.CI_SELF_HOSTED_PYTHON_BIN || '' }}" in workflow
    assert "SELF_HOSTED_VENV_DIR: ${{ vars.CI_SELF_HOSTED_VENV_DIR || '' }}" in workflow
    assert "PIP_INDEX_URL: ${{ vars.CI_PIP_INDEX_URL || 'https://pypi.org/simple' }}" in workflow
    assert "PIP_CACHE_DIR: ${{ vars.CI_PIP_CACHE_DIR || '' }}" in workflow
    assert "TORCH_WHEEL_DIR: ${{ vars.CI_TORCH_WHEEL_DIR || '' }}" in workflow
    assert "SELF_HOSTED_HTTP_PROXY: ${{ vars.CI_HTTP_PROXY || '' }}" in workflow
    assert "SELF_HOSTED_HTTPS_PROXY: ${{ vars.CI_HTTPS_PROXY || '' }}" in workflow
    assert "SELF_HOSTED_NO_PROXY: ${{ vars.CI_NO_PROXY || '' }}" in workflow
    _assert_uses_self_hosted_bootstrap(
        workflow,
        "bash scripts/prepare_self_hosted_ci.sh --include-torch-wheel-dir",
        count=1,
    )
    assert "runner.name == 'mimirq-main-01'" not in workflow
    assert "/home/user/.local/share/uv" not in workflow
    assert "/data/actions-runner" not in workflow
    assert "127.0.0.1:35983" not in workflow
    assert "\n  build:\n" in workflow
    assert "runs-on: ubuntu-latest" in workflow
    assert workflow.count("make api-docs-build") == 2
    assert workflow.count("python ci/download_verified_wheels.py") == 2
    assert "make api-docs-build-static" not in workflow
    assert "Upload API site artifact" in workflow
    assert "actions/upload-artifact@" in workflow
    assert "actions/download-artifact@" in workflow
    assert "name: api-docs-site" in workflow
    assert workflow.count(checkout_proxy) == 1
    assert "http_proxy: ${{ vars.CI_HTTP_PROXY || '' }}" not in hosted_build
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
    assert "actions/download-artifact@" in publish_job
    assert "make api-docs-build" not in publish_job
    assert "actions/checkout@" not in publish_job
    assert "pages: write" not in build_job
    assert "id-token: write" not in build_job
    assert "pages: write" in publish_job
    assert "id-token: write" in publish_job


def test_security_workflow_pins_trufflehog_by_digest() -> None:
    workflow = _read(".github/workflows/security.yml")

    assert (
        "trufflesecurity/trufflehog@sha256:c28ab4a11e01d6fcc10776f65cce015bdf9795f2393cffa2ec0a7c8464ee58b6" in workflow
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
    torch_version = re.search(r'^torch==([^;]+); platform_system == "Linux"$', requirements, re.MULTILINE)
    torchvision_version = re.search(r'^torchvision==([^;]+); platform_system == "Linux"$', requirements, re.MULTILINE)

    assert torch_version is not None
    assert torchvision_version is not None
    for install_surface in ("docker/Dockerfile", ".github/workflows/ci.yml"):
        content = _read(install_surface)
        assert set(re.findall(r"\btorch-([0-9.]+)\+cpu-", content)) == {torch_version.group(1)}
        assert set(re.findall(r"\btorchvision-([0-9.]+)\+cpu-", content)) == {torchvision_version.group(1)}


def test_docker_ci_supports_cold_web_builds() -> None:
    workflow = _read(".github/workflows/ci.yml")
    docker_job = workflow.split("\n  docker-build:", 1)[1].split("\n  retrieval-only-bounded-gate:", 1)[0]
    retrieval_compose = _read("docker/docker-compose.retrieval-dev.yml")
    full_compose = _read("docker/docker-compose.yml")
    lite_compose = _read("docker/docker-compose.lite.yml")
    backend_dockerfile = _read("docker/Dockerfile")
    web_dockerfile = _read("web/Dockerfile.prod")
    web_compose = _read("docker/docker-compose.web.yml")

    assert "timeout-minutes: 90" in docker_job
    assert "docker compose -f docker/docker-compose.retrieval-dev.yml config --quiet" in workflow
    assert "target=/root/.local/share/pnpm/store" in web_dockerfile
    assert "https://registry.npmmirror.com" in web_dockerfile
    assert "ENV COREPACK_NPM_REGISTRY=$PNPM_REGISTRY" in web_dockerfile
    assert "/opt/venv/bin/python scripts/bootstrap_mimirq_models.py" in backend_dockerfile
    assert 'if [ "$attempt" = "3" ]; then exit 1; fi' in backend_dockerfile
    assert "PNPM_REGISTRY: ${PNPM_REGISTRY:-https://registry.npmmirror.com}" in web_compose
    assert 'python scripts/select_free_docker_subnet.py --seed "$GITHUB_RUN_ID"' in docker_job
    assert "printf 'DOCKER_BUILD_NETWORK=host\\n'" in docker_job
    assert "Set up Docker Buildx" in docker_job
    assert "uses: docker/setup-buildx-action@37fe631027851001ddb9b187196cc803df7f5f0e # v4" in docker_job
    assert "id: backend_buildx" in docker_job
    assert "network=host" in docker_job
    assert "uses: docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a # v7" in docker_job
    assert "builder: ${{ steps.backend_buildx.outputs.name }}" in docker_job
    assert "load: true" in docker_job
    assert "allow: network.host" in docker_job
    assert "cache-from: type=gha,scope=mimirq-backend" in docker_job
    assert "cache-to: type=gha,mode=max,scope=mimirq-backend" in docker_job
    assert "build-args: |\n            HTTP_PROXY\n            HTTPS_PROXY\n            NO_PROXY" in docker_job
    assert "--build-arg NEXT_PUBLIC_API_URL=/" in docker_job
    assert "README docker quickstart smoke" in docker_job
    assert 'API_HEALTHCHECK_START_PERIOD: "420s"' in docker_job
    assert "EMBEDDING_PROVIDER_DOCKER: deterministic_test" in docker_job
    assert "EMBEDDING_MODEL_DOCKER: mimirq-deterministic-test-v1" in docker_job
    assert "Diagnose README docker quickstart failure" in docker_job
    assert '"${compose[@]}" logs --tail=300 mimirq-api mimirq-worker' in docker_job
    for compose in (full_compose, lite_compose, retrieval_compose):
        assert "start_period: ${API_HEALTHCHECK_START_PERIOD:-240s}" in compose
    assert "EMBEDDING_PROVIDER: ${EMBEDDING_PROVIDER_DOCKER:-${EMBEDDING_PROVIDER}}" in full_compose
    assert "EMBEDDING_MODEL: ${EMBEDDING_MODEL_DOCKER:-${EMBEDDING_MODEL}}" in full_compose
    assert "make up-web" in docker_job
    assert "artifacts/core-e2e.readme-docker.json" in docker_job
    assert "README lite quickstart smoke" in docker_job
    assert "make up-lite" in docker_job
    assert "artifacts/core-e2e.readme-lite.json" in docker_job
    assert docker_job.count('BACKEND_PORT: "0"') >= 6
    assert 'WEB_PORT: "0"' in docker_job
    assert docker_job.count('api_port=$("${compose[@]}" port mimirq-api 8000') >= 2
    assert "CORE_E2E_BASE_URL=http://127.0.0.1:$api_port" in docker_job
    assert "http://127.0.0.1:$api_port/api/v1/health/ready" in docker_job
    assert "Clean up README lite quickstart stack" in docker_job
    assert "docker compose --env-file .env -f docker/docker-compose.lite.yml down -v --remove-orphans" in docker_job
    assert "Smoke built backend and web images" in docker_job
    assert "up -d --no-build" in docker_job
    assert "Docker web-proxy and dual-api core smoke" in docker_job
    assert "python scripts/smoke_test.py" in docker_job
    assert "JWT built-web browser smoke" in docker_job
    assert "--web-base-url http://mimirq-web-smoke-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}:3000" in docker_job
    assert "--secondary-base-url http://$api2_name:8000" in docker_job
    assert "artifacts/core-e2e.web-dual-api.json" in docker_job
    assert '--name "$api2_name" --no-deps mimirq-api' in docker_job
    assert "Docker live core release gate" in docker_job
    assert "python scripts/live_core_release_gate.py" in docker_job
    assert "python scripts/seed_ci_retrieval_regression.py" in docker_job
    assert "--membership-only" in docker_job
    assert "--account-id ci-live-gate" in docker_job
    assert "--secondary-base-url http://$api2_name:8000" in docker_job
    assert "AUTH_MODE_RETRIEVAL_DEV: header" in docker_job
    assert 'UPLOAD_DEDUP_ENABLED_RETRIEVAL_DEV: "true"' in docker_job
    assert 'RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED_RETRIEVAL_DEV: "true"' in docker_job
    assert 'RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY_RETRIEVAL_DEV: "3"' in docker_job
    assert 'RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY_RETRIEVAL_DEV: "3"' in docker_job
    assert 'DATASET_ANALYSIS_PNG_STALE_AFTER_SEC_RETRIEVAL_DEV: "2"' in docker_job
    assert "if: always()" in docker_job
    assert "image: ${MIMIRQ_BACKEND_IMAGE:-mimirq-backend}" in retrieval_compose
    assert "RETRIEVAL_CANDIDATE_CACHE_ENABLED_RETRIEVAL_DEV:-false" in retrieval_compose
    assert "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED_RETRIEVAL_DEV:-true" in retrieval_compose
    assert "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY_RETRIEVAL_DEV:-3" in retrieval_compose
    assert "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY_RETRIEVAL_DEV:-3" in retrieval_compose
    assert "DATASET_ANALYSIS_PNG_STALE_AFTER_SEC_RETRIEVAL_DEV:-60" in retrieval_compose
    assert "EMBEDDING_PROVIDER_RETRIEVAL_DEV:-deterministic_test" in retrieval_compose
    assert "EMBEDDING_MODEL_RETRIEVAL_DEV:-mimirq-deterministic-test-v1" in retrieval_compose


def test_live_core_gate_keeps_png_cross_instance_and_worker_lost_probes() -> None:
    source = _read("scripts/live_core_release_gate.py")

    assert "_probe_png_cross_instance(" in source
    assert "_probe_png_worker_lost(" in source
    assert 'report["png_cross_instance"]' in source
    assert 'report["png_worker_lost"]' in source
    assert "analysis/export.png" in source
    assert "analysis/export-tasks" in source
    assert "worker_lost" in source


def test_built_web_jwt_browser_smoke_is_explicitly_wired() -> None:
    workflow = _read(".github/workflows/ci.yml")
    docker_job = workflow.split("\n  docker-build:", 1)[1].split("\n  retrieval-only-bounded-gate:", 1)[0]
    script = _read("scripts/run_ci_jwt_browser_smoke.sh")
    playwright_config = _read("web/playwright.config.ts")

    assert script.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert "set -x" not in script
    assert 'docker port "$WEB_CONTAINER" 3000/tcp' in script
    assert '"${web_base_url}/api/v1/auth/register"' in script
    assert "MIMIRQ_SMOKE_IDENTIFIER and MIMIRQ_SMOKE_PASSWORD must be set together" in script
    assert "reuse_account=1" in script
    assert "@example.com`" in script
    assert "@example.invalid" not in script
    assert "PLAYWRIGHT_EXTERNAL_SERVER=1" in script
    assert "PLAYWRIGHT_LIVE_STACK=1" in script
    assert 'PLAYWRIGHT_PORT="$mapped_port"' in script
    assert 'PLAYWRIGHT_LIVE_IDENTIFIER="$jwt_identifier"' in script
    assert 'PLAYWRIGHT_LIVE_PASSWORD="$jwt_password"' in script
    assert "pnpm --dir web exec playwright test e2e/live-stack.smoke.spec.ts" in script
    assert '>>"$GITHUB_ENV"' in script
    assert "::add-mask::%s" in script
    assert "MIMIRQ_SMOKE_IDENTIFIER=%s" in script
    assert "MIMIRQ_SMOKE_PASSWORD=%s" in script

    assert "PLAYWRIGHT_EXTERNAL_SERVER" in playwright_config
    assert "webServer: useExternalServer ? undefined" in playwright_config
    assert "Install JWT browser smoke dependencies" in docker_job
    assert "Prepare self-hosted Node" in docker_job
    assert "node -v" in docker_job
    assert "npm -v" in docker_job
    assert "pnpm -v" in docker_job
    assert "pnpm install --frozen-lockfile" in docker_job
    assert "pnpm exec playwright install chromium" in docker_job
    assert "-p 127.0.0.1::3000" in docker_job
    assert "JWT built-web browser smoke" in docker_job
    assert "bash scripts/run_ci_jwt_browser_smoke.sh" in docker_job
    dual_api_step = docker_job.split("- name: Docker web-proxy and dual-api core smoke", 1)[1].split(
        "\n      - name:", 1
    )[0]
    assert "--identifier" not in dual_api_step
    assert "--password" not in dual_api_step
    assert "--bootstrap-register" not in dual_api_step
    assert "-e MIMIRQ_SMOKE_IDENTIFIER" in dual_api_step
    assert "-e MIMIRQ_SMOKE_PASSWORD" in dual_api_step


def test_playwright_prod_server_can_reuse_an_existing_build_artifact() -> None:
    playwright_config = _read("web/playwright.config.ts")

    assert "const reuseBuildOutput = process.env.PLAYWRIGHT_REUSE_BUILD === '1'" in playwright_config
    assert (
        "MARKDOWN_IMAGE_PROXY_SECRET=${markdownImageProxySecret} HOST=127.0.0.1 PORT=${PORT} pnpm start"
        in playwright_config
    )
    assert (
        "MARKDOWN_IMAGE_PROXY_SECRET=${markdownImageProxySecret} "
        "pnpm exec next build --webpack && "
        "MARKDOWN_IMAGE_PROXY_SECRET=${markdownImageProxySecret} "
        "HOST=127.0.0.1 PORT=${PORT} pnpm start" in playwright_config
    )


def test_generic_browser_suite_does_not_probe_an_ambient_live_backend() -> None:
    playwright_config = _read("web/playwright.config.ts")
    live_config = _read("web/playwright.live.config.ts")

    assert "const runLiveStack = process.env.PLAYWRIGHT_LIVE_STACK === '1'" in playwright_config
    assert "testIgnore: runLiveStack ? undefined : /live-stack\\.smoke\\.spec\\.ts/" in playwright_config
    assert "testMatch: /live-stack\\.smoke\\.spec\\.ts/" in live_config


def test_main_ci_runs_core_e2e_against_the_existing_host_backend() -> None:
    workflow = _read(".github/workflows/ci.yml")
    regression_job = workflow.split("\n  retrieval-regression-gate:", 1)[1].split("\n  kg-search-regression-gate:", 1)[
        0
    ]

    assert "README host web contract smoke" in regression_job
    assert "node web/scripts/api-ping.mjs" in regression_job
    assert 'NEXT_PUBLIC_API_URL="http://127.0.0.1:${MIMIRQ_RETRIEVAL_API_PORT}"' in regression_job
    assert "Install web deps" in regression_job
    assert "pnpm install --frozen-lockfile" in regression_job
    assert "Install Playwright browsers for host browser smoke" in regression_job
    assert "README host browser smoke" in regression_job
    assert 'PLAYWRIGHT_USE_PROD_SERVER: "1"' in regression_job
    assert "pnpm exec playwright test e2e/live-stack.smoke.spec.ts" in regression_job
    assert "README host quickstart smoke" in regression_job
    assert "make core-e2e" in regression_job
    host_quickstart = regression_job.split("- name: README host quickstart smoke", 1)[1].split(
        "- name: Run retrieval-only regression gate",
        1,
    )[0]
    assert "NEXT_PUBLIC_USER_ID: ci-bot" in host_quickstart
    assert "NEXT_PUBLIC_TENANT_ID: 00000000-0000-0000-0000-000000000000" in host_quickstart
    assert 'CORE_E2E_BASE_URL="http://127.0.0.1:${MIMIRQ_RETRIEVAL_API_PORT}"' in regression_job
    assert "CORE_E2E_OUT=artifacts/core-e2e.retrieval-regression.json" in regression_job


def test_host_regression_jobs_isolate_database_and_api_ports() -> None:
    workflow = _read(".github/workflows/ci.yml")
    retrieval_job = workflow.split("\n  retrieval-regression-gate:\n", 1)[1].split(
        "\n  kg-search-regression-gate:\n",
        1,
    )[0]
    kg_job = workflow.split("\n  kg-search-regression-gate:\n", 1)[1]

    for job, port_var in (
        (retrieval_job, "MIMIRQ_RETRIEVAL_API_PORT"),
        (kg_job, "MIMIRQ_KG_API_PORT"),
    ):
        assert "- 5432/tcp" in job
        assert "- 5432:5432" not in job
        assert "Allocate isolated host ports" in job
        assert f'echo "{port_var}=$port" >> "$GITHUB_ENV"' in job
        assert f'--port "${port_var}"' in job
        assert "${{ job.services.postgres.ports['5432'] }}" in job
        assert "http://localhost:8000" not in job
        assert "http://127.0.0.1:8000" not in job

    assert 'echo "MIMIRQ_RETRIEVAL_WEB_PORT=$port" >> "$GITHUB_ENV"' in retrieval_job
    assert 'PLAYWRIGHT_PORT="$MIMIRQ_RETRIEVAL_WEB_PORT"' in retrieval_job


def test_live_browser_smoke_never_bootstraps_a_persistent_admin() -> None:
    live_spec = _read("web/e2e/live-stack.smoke.spec.ts")

    assert "PLAYWRIGHT_LIVE_IDENTIFIER" in live_spec
    assert "PLAYWRIGHT_LIVE_PASSWORD" in live_spec
    assert "JWT live smoke requires" in live_spec
    assert "getByRole('button', { name: '首次设置' })" not in live_spec


def test_live_browser_smoke_targets_the_current_full_index_execution_controls() -> None:
    live_spec = _read("web/e2e/live-stack.smoke.spec.ts")

    assert "getByRole('group', { name: '执行终点' })" in live_spec
    assert 'input[name="ingestion-execution-mode"][value="full_index"]' in live_spec
    assert "await fullIndexMode.check()" in live_spec
    assert "await expect(fullIndexMode).toBeChecked()" in live_spec
    assert "getByText('执行阶段', { exact: true })" not in live_spec
    assert "getByRole('combobox')" not in live_spec
    assert "getByRole('option', { name: /解析 \\+ 索引/ })" not in live_spec
    assert "/api/v1/documents/upload-batch" in live_spec
    assert "选择数据集" in live_spec
    assert "来源与证据" in live_spec


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
