import ast
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SILENT_PASS_RE = re.compile(r"except[^\n]*:\n[ \t]*pass\b")

SILENT_PASS_GUARD_PATHS = (
    "app/api/v1/audit.py",
    "app/api/v1/chat.py",
    "app/api/v1/connectors.py",
    "app/api/v1/datasets.py",
    "app/api/v1/evaluations.py",
    "app/api/v1/evidence.py",
    "app/api/v1/ltr.py",
    "app/api/v1/parsing.py",
    "app/api/v1/pipeline.py",
    "app/api/v1/pipeline_support/auto_annotations.py",
    "app/api/v1/pipeline_support/capabilities.py",
    "app/api/v1/pipeline_support/clean_preview.py",
    "app/api/v1/pipeline_support/governance_profiles.py",
    "app/api/v1/pipeline_support/ingestion_preview.py",
    "app/deepdoc/parser/docling_parser.py",
    "app/deepdoc/parser/excel_parser.py",
    "app/parsing/enrich/image_understanding.py",
    "app/parsing/parsers/deepseek_ocr_parser.py",
    "app/parsing/parsers/email_parser.py",
    "app/parsing/preprocess/image_preprocess.py",
    "app/parsing/preprocess/watermark.py",
    "app/parsing/quality/scorer.py",
    "app/parsing/subprocess_runner.py",
    "app/parsing/subprocess_worker.py",
    "app/parsing/utils/text.py",
    "app/rag/checkpointer/time_travel.py",
    "app/rag/chunking/strategies/llama_index.py",
    "app/rag/core/citations.py",
    "app/rag/embedding/adapter.py",
    "app/rag/engine.py",
    "app/rag/engine_support/common.py",
    "app/rag/engine_support/doc_utils.py",
    "app/rag/engine_support/llm_routing.py",
    "app/rag/evaluation/ragas.py",
    "app/rag/evaluation/regression_sample_builder.py",
    "app/rag/kg/extraction/extractor.py",
    "app/rag/preprocessing/diagnostics.py",
    "app/rag/preprocessing/processor.py",
    "app/rag/retrieval/hybrid/bm25_index.py",
    "app/rag/retrieval/hybrid/colbert_index.py",
    "app/rag/retrieval/hybrid/common.py",
    "app/rag/retrieval/hybrid/dedup.py",
    "app/rag/retrieval/hybrid/fusion.py",
    "app/rag/retrieval/hybrid/lexical.py",
    "app/rag/retrieval/hybrid/post_process.py",
    "app/rag/retrieval/hybrid/sparse_index.py",
    "app/rag/retrieval/orchestration/anchors.py",
    "app/rag/retrieval/orchestration/channel_budget.py",
    "app/rag/retrieval/orchestration/citation_quality.py",
    "app/rag/retrieval/orchestration/common.py",
    "app/rag/retrieval/orchestration/debug_sanitize.py",
    "app/rag/retrieval/orchestration/hierarchy.py",
    "app/rag/retrieval/orchestration/kg_merge_boost.py",
    "app/rag/retrieval/orchestrator.py",
    "app/rag/retriever.py",
    "app/rag/workflows/evaluator_optimizer.py",
    "app/services/dataset_precheck_scan_runner.py",
    "app/services/deps_diagnostics_service.py",
    "app/services/evidence_reference_repair_service.py",
    "app/services/indexer.py",
    "app/services/ingestion_run_service.py",
    "app/services/metrics_logger.py",
    "app/services/mineru_service.py",
    "app/services/rag_metrics_dashboard.py",
    "app/services/report_service.py",
    "app/services/retention_jobs.py",
    "app/storage/vector/milvus.py",
    "app/tasks/jobs.py",
    "app/tasks/locks.py",
)

REQUESTS_GUARD_PATHS = (
    "app/deepdoc/parser/mineru_parser.py",
    "app/deepdoc/parser/tcadp_parser.py",
    "app/parsing/enrich/chart_to_data.py",
    "app/parsing/enrich/formula_ocr.py",
    "app/parsing/enrich/vlm_image_caption.py",
    "app/parsing/parsers/mathpix_parser.py",
    "app/parsing/preprocess/deskew.py",
    "app/parsing/preprocess/handwriting_cleanup.py",
    "app/parsing/preprocess/watermark.py",
    "app/services/mineru_service.py",
    "app/third_party/integrated_pipeline/chunkers/naive.py",
)

# Line-count ratchet for modules that were deliberately split into support
# packages. Budgets may only go DOWN (keep splitting) or be raised explicitly
# in the same change that justifies the growth — never drift back up silently.
MODULE_LINE_BUDGETS = {
    "app/api/v1/integrations_dify.py": 8000,
    "app/api/v1/pipeline.py": 1800,
    "app/core/config.py": 2550,
    "app/parsing/processors/processor.py": 4750,
    "app/rag/engine.py": 4100,
    "app/rag/kg/api/routes.py": 2600,
    "app/rag/retrieval/orchestrator.py": 4800,
    "app/rag/retriever.py": 3400,
    "web/app/knowledge/ingestion/page-client.tsx": 4200,
    "web/app/knowledge/quarantine/page.tsx": 1950,
    "web/app/reports/page-client.tsx": 800,
    "web/components/graph/kg-snapshots-page.tsx": 50,
    "web/components/ragviz/similarity-workbench.tsx": 2300,
}

FULL_SHA_RE = re.compile(r"@[0-9a-f]{40}(?:\s|$)")
_FASTAPI_ROUTE_DECORATOR_NAMES = {"get", "post", "put", "delete", "patch", "options", "head", "api_route"}


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _helm_runtime_script_paths() -> list[str]:
    chart_dir = ROOT / "deploy/helm/mimirq"
    sources = [chart_dir / "values.yaml", *sorted((chart_dir / "templates").glob("*.yaml"))]
    return sorted(
        {
            match
            for source in sources
            for match in re.findall(r"scripts/[A-Za-z0-9_./-]+\.py", source.read_text(encoding="utf-8"))
        }
    )


def _decorator_target(decorator: ast.expr) -> ast.expr:
    return decorator.func if isinstance(decorator, ast.Call) else decorator


def _is_fastapi_route(function: ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        target = _decorator_target(decorator)
        if (
            isinstance(target, ast.Attribute)
            and target.attr in _FASTAPI_ROUTE_DECORATOR_NAMES
        ):
            return True
    return False


def _uses_sync_session_dependency(function: ast.AsyncFunctionDef) -> bool:
    for arg in (*function.args.args, *function.args.kwonlyargs):
        if arg.annotation is None:
            continue
        annotation = ast.unparse(arg.annotation)
        if "Session" in annotation and "AsyncSession" not in annotation and "Depends(" in annotation:
            return True
    return False


def _function_body_has_async_ops(function: ast.AsyncFunctionDef) -> bool:
    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.found = False

        def visit_Await(self, node: ast.Await) -> None:  # noqa: N802
            self.found = True

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
            self.found = True

        def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
            self.found = True

        def visit_Yield(self, node: ast.Yield) -> None:  # noqa: N802
            self.found = True

        def visit_YieldFrom(self, node: ast.YieldFrom) -> None:  # noqa: N802
            self.found = True

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802, ARG002
            return None

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            if node is function:
                self.generic_visit(node)
            return None

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802, ARG002
            return None

        def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802, ARG002
            return None

    visitor = _Visitor()
    visitor.visit(function)
    return visitor.found


def _iter_fake_async_sync_db_routes() -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for path in sorted((ROOT / "app").rglob("*.py")):
        rel_path = str(path.relative_to(ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if not _is_fastapi_route(node):
                continue
            if not _uses_sync_session_dependency(node):
                continue
            if _function_body_has_async_ops(node):
                continue
            hits.append((rel_path, node.lineno, node.name))
    return hits


@pytest.mark.parametrize("rel_path", SILENT_PASS_GUARD_PATHS)
def test_critical_modules_do_not_use_silent_pass_fallbacks(rel_path: str) -> None:
    assert SILENT_PASS_RE.search(_read(rel_path)) is None, rel_path


@pytest.mark.parametrize("rel_path", sorted(MODULE_LINE_BUDGETS))
def test_split_modules_stay_within_line_budgets(rel_path: str) -> None:
    budget = MODULE_LINE_BUDGETS[rel_path]
    lines = _read(rel_path).count("\n") + 1
    assert lines <= budget, (
        f"{rel_path} is {lines} lines (budget {budget}). Move code into its "
        "support package instead of growing the module, or raise the budget "
        "explicitly in this table with a justification."
    )


@pytest.mark.parametrize("rel_path", REQUESTS_GUARD_PATHS)
def test_managed_http_modules_do_not_bypass_shared_clients(rel_path: str) -> None:
    assert "requests." not in _read(rel_path), rel_path


def test_time_context_helpers_do_not_use_naive_datetime_now() -> None:
    assert 'datetime.now().strftime("%Y-%m-%d %H:%M")' not in _read("app/rag/middleware/base.py")
    assert 'datetime.now().strftime("%Y%m%d_%H%M%S")' not in _read("app/deepdoc/parser/tcadp_parser.py")


def test_fastapi_sync_db_routes_do_not_run_on_event_loop() -> None:
    offenders = [
        f"{rel_path}:{lineno}:{name}"
        for rel_path, lineno, name in _iter_fake_async_sync_db_routes()
    ]
    assert offenders == [], offenders


def test_parser_service_dockerfiles_drop_root_after_install() -> None:
    expected_users = {
        "docker/magicpdf/Dockerfile": "USER appuser",
        "docker/marker/Dockerfile": "USER appuser",
        "docker/olmocr/Dockerfile": "USER appuser",
        "docker/paddlevl/Dockerfile": "USER paddleocr",
        "docker/qianfanocr/Dockerfile": "USER appuser",
    }

    for dockerfile_path, user_line in expected_users.items():
        dockerfile = _read(dockerfile_path)
        assert user_line in dockerfile
        assert dockerfile.rfind(user_line) > dockerfile.rfind("COPY")


def test_sonar_flagged_workflow_actions_are_pinned_to_full_sha() -> None:
    workflow_paths = (
        ".github/workflows/ci.yml",
        ".github/workflows/lint-fast.yml",
        ".github/workflows/security.yml",
    )
    flagged_actions = ("pnpm/action-setup", "trufflesecurity/trufflehog")

    for workflow_path in workflow_paths:
        for line in _read(workflow_path).splitlines():
            if line.lstrip().startswith("uses:") and any(action in line for action in flagged_actions):
                assert FULL_SHA_RE.search(line), line


def test_parser_quality_gates_cannot_ignore_complete_regressions() -> None:
    profile = json.loads(_read("ci/parser_strict_profile.v1.json"))
    assert all(0 <= float(value) < 1 for value in profile["thresholds"].values())

    for workflow_path in (
        ".github/workflows/ci.yml",
        ".github/workflows/parsing-proof-nightly.yml",
        ".github/workflows/parsing-proof-sample.yml",
        ".github/workflows/rag-quality-gate.yml",
    ):
        workflow = _read(workflow_path)
        assert "parsing_retrieval_proof_gate.py" in workflow
        assert "gate.json || true" not in workflow

    for workflow_path in (
        ".github/workflows/ci.yml",
        ".github/workflows/parsing-proof-sample.yml",
        ".github/workflows/rag-quality-gate.yml",
    ):
        workflow = _read(workflow_path)
        assert "build_parsing_retrieval_proof_artifacts.py" not in workflow

    ci_workflow = _read(".github/workflows/ci.yml")
    assert "--input-dir tests/fixtures/parsing_golden" in ci_workflow
    assert "--manifest tests/fixtures/parsing_golden/manifest.json" in ci_workflow


def test_self_hosted_workflows_clean_checkout_state() -> None:
    for workflow_path in (
        ".github/workflows/api-docs.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/lint-fast.yml",
        ".github/workflows/security.yml",
    ):
        assert "clean: false" not in _read(workflow_path)


def test_backend_entrypoint_uses_an_explicit_forwarded_proxy_allowlist() -> None:
    entrypoint = _read("docker/start_backend.sh")
    assert ': "${FORWARDED_ALLOW_IPS:=127.0.0.1}"' in entrypoint
    assert '--forwarded-allow-ips "${FORWARDED_ALLOW_IPS}"' in entrypoint


def test_production_helm_example_uses_distributed_runtime_settings() -> None:
    values = yaml.safe_load(_read("deploy/helm/mimirq/examples/values-prod.yaml"))
    assert int(values["api"]["replicas"]) > 1
    extra_env = {str(item["name"]): str(item["value"]).lower() for item in values["api"]["extraEnv"]}
    assert extra_env["RATE_LIMIT_REDIS_ENABLED"] == "true"
    assert extra_env["BM25_INDEX_ENABLED"] == "false"
    assert extra_env["UPLOAD_DEDUP_ENABLED"] == "true"
    assert extra_env["RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED"] == "true"
    assert extra_env["RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY"] == "3"
    assert extra_env["ENV"] == "production"
    assert extra_env["DB_CREATE_ALL_ON_STARTUP"] == "false"
    assert extra_env["DB_RUNTIME_MIGRATIONS_ENABLED"] == "false"
    worker_extra_env = {str(item["name"]): str(item["value"]).lower() for item in values["worker"]["extraEnv"]}
    assert worker_extra_env["ENV"] == "production"
    assert worker_extra_env["DB_CREATE_ALL_ON_STARTUP"] == "false"
    assert worker_extra_env["DB_RUNTIME_MIGRATIONS_ENABLED"] == "false"
    assert worker_extra_env["UPLOAD_DEDUP_ENABLED"] == "true"
    assert worker_extra_env["RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED"] == "true"
    assert worker_extra_env["RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY"] == "3"
    assert values["migrations"]["enabled"] is True
    assert str(values["runtimeGuards"]["environment"]).lower() == "production"
    assert str(values["runtimeGuards"]["vectorBackend"]).lower() == "milvus"
    assert str(values["runtimeGuards"]["minioEnabled"]).lower() == "true"
    assert str(values["runtimeGuards"]["minioDocumentsEnabled"]).lower() == "true"
    assert str(values["runtimeGuards"]["dbCreateAllOnStartup"]).lower() == "false"
    assert str(values["runtimeGuards"]["dbRuntimeMigrationsEnabled"]).lower() == "false"
    assert values["ingress"]["enabled"] is True
    assert values["ingress"]["tls"]
    assert values["networkPolicy"]["enabled"] is True
    assert values["networkPolicy"]["api"]["ingress"]["allowSameNamespace"] is False
    assert values["networkPolicy"]["api"]["ingress"]["extraFrom"]
    assert values["networkPolicy"]["egress"]["restrict"] is True
    assert values["networkPolicy"]["egress"]["rules"]


def test_helm_defaults_keep_single_replica_dev_path_usable() -> None:
    values = yaml.safe_load(_read("deploy/helm/mimirq/values.yaml"))
    assert values["secretEnv"]["ENV"] == "development"
    assert str(values["secretEnv"]["DB_CREATE_ALL_ON_STARTUP"]).lower() == "true"
    assert str(values["secretEnv"]["DB_RUNTIME_MIGRATIONS_ENABLED"]).lower() == "true"
    assert int(values["api"]["replicas"]) == 1
    assert int(values["worker"]["replicas"]) == 1
    assert values["worker"]["healthcheckCommand"] == [
        "arq",
        "--check",
        "app.tasks.queue.WorkerHealthSettings",
    ]
    assert values["worker"]["readinessProbe"]["enabled"] is True
    assert "livenessProbe" not in values["worker"]
    assert values["migrations"]["enabled"] is False


def test_hardened_helm_overlay_preserves_production_network_allowlists() -> None:
    path = "deploy/helm/mimirq/examples/values-hardened.yaml"
    values = yaml.safe_load(_read(path))
    source = _read(path)

    assert "networkPolicy" not in values
    assert "-f deploy/helm/mimirq/examples/values-prod.yaml" in source
    assert "-f deploy/helm/mimirq/examples/values-hardened.yaml" in source


def test_production_docs_call_out_strong_compose_credentials_and_proxy_boundary() -> None:
    docker_doc = _read("docs/deployment/docker_compose.md")
    assert "MINIO_ACCESS_KEY_DOCKER" in docker_doc
    assert "MINIO_SECRET_KEY_DOCKER" in docker_doc
    assert "UPLOAD_DEDUP_ENABLED_DOCKER=true" in docker_doc
    assert "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED_DOCKER=true" in docker_doc
    assert "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY_DOCKER=3" in docker_doc
    assert "FORWARDED_ALLOW_IPS_DOCKER" in docker_doc
    assert "禁止 `*`" in docker_doc
    assert "MARKDOWN_IMAGE_PROXY_SECRET" in docker_doc

    readme = _read("README.md")
    assert "[Docker Compose 部署指南](./docs/deployment/docker_compose.md)" in readme

    env_example = _read(".env.example")
    assert "生产环境必须改掉默认的 minioadmin" in env_example
    assert "生产环境禁止设为 *" in env_example


def test_production_make_targets_validate_and_propagate_environment() -> None:
    compose = yaml.safe_load(_read("docker/docker-compose.yml"))
    assert compose["x-backend-env"]["ENV"] == "${ENV:-development}"
    assert compose["x-backend-env"]["UPLOAD_DEDUP_ENABLED"] == "${UPLOAD_DEDUP_ENABLED_DOCKER:-true}"
    assert (
        compose["x-backend-env"]["RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED"]
        == "${RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED_DOCKER:-true}"
    )
    assert (
        compose["x-backend-env"]["RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY"]
        == "${RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY_DOCKER:-3}"
    )
    lite_compose = yaml.safe_load(_read("docker/docker-compose.lite.yml"))
    assert lite_compose["x-backend-env"]["UPLOAD_DEDUP_ENABLED"] == "${UPLOAD_DEDUP_ENABLED_DOCKER:-true}"
    assert (
        lite_compose["x-backend-env"]["RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED"]
        == "${RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED_DOCKER:-true}"
    )
    assert (
        lite_compose["x-backend-env"]["RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY"]
        == "${RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY_DOCKER:-3}"
    )

    makefile = _read("Makefile")
    assert "prod-preflight: init" in makefile
    assert 'ENV=production $(PY) -c "from app.core.config import settings"' in makefile
    assert "up-prod: prod-preflight" in makefile
    assert "ENV=production $(COMPOSE) up -d --build" in makefile
    assert "up-prod-web: prod-preflight" in makefile
    assert "ENV=production $(COMPOSE_WEB) up -d --build" in makefile


def test_host_quickstart_make_targets_cover_backend_worker_and_web() -> None:
    makefile = _read("Makefile")
    readme = _read("README.md")
    quickstart = _read("docs/quickstart.md")

    assert "make worker   - run background worker locally from the project venv (arq)" in makefile
    assert "make worker-check - verify a running local worker is publishing its Redis health sentinel" in makefile
    assert "\nworker:\n" in makefile
    assert "\t$(PY) -m arq app.tasks.worker.WorkerSettings\n" in makefile
    assert "\nworker-check:\n" in makefile
    assert "\t$(PY) -m arq --check app.tasks.queue.WorkerHealthSettings\n" in makefile

    assert "make backend" in readme
    assert "make web" in readme
    assert ".venv/bin/arq app.tasks.worker.WorkerSettings" not in readme
    assert "源码开发（Python venv + pip + pnpm）" in readme

    assert "make setup-host" in quickstart
    assert "make backend" in quickstart
    assert "make worker" in quickstart
    assert "make web" in quickstart
    assert "make worker-check" in quickstart
    assert "分别打开两个终端" in quickstart
    assert "需要独立队列时" in quickstart
    assert "第三个终端运行 `make worker`" in quickstart


def test_makefile_recipes_do_not_execute_posix_comment_lines() -> None:
    makefile = _read("Makefile")

    # A tab-indented `#` line is passed to the recipe shell. It is harmless in
    # POSIX shells but becomes an attempted executable under Windows cmd.exe.
    assert re.findall(r"(?m)^\t@?#", makefile) == []


def test_optional_parser_profiles_are_actionable_from_public_docs() -> None:
    makefile = _read("Makefile")
    readme = _read("README.md")
    readme_en = _read("README_EN.md")
    quickstart = _read("docs/quickstart.md")
    parser_targets = (
        "up-etl4llm",
        "up-marker",
        "up-paddlevl",
        "up-mineru",
        "up-mineru-vlm",
        "up-olmocr",
        "up-magicpdf",
        "up-qianfanocr",
    )

    for target in parser_targets:
        assert f"\n{target}:" in makefile
        assert f"`make {target}`" in readme
        assert f"`make {target}`" in readme_en

    assert "\ninfra-up-magicpdf:" in makefile
    assert "PADDLE_VL_API_URL=http://mimirq-paddlevl:9030/convert" in quickstart
    assert "PADDLE_VL_API_URL=http://127.0.0.1:9030/convert" not in quickstart


def test_docker_verification_keeps_dev_lint_tools_out_of_the_runtime_image() -> None:
    makefile = _read("Makefile")
    lint_target = makefile.split("\nlint-py-docker:", 1)[1].split("\ncompileall-docker:", 1)[0]
    compile_target = makefile.split("\ncompileall-docker:", 1)[1].split("\n# No patched releases", 1)[0]

    assert "$(MAKE) --no-print-directory lint-py" in lint_target
    assert "$(COMPOSE) exec" not in lint_target
    assert "PYTHONPYCACHEPREFIX=/tmp/mimirq-pycache" in compile_target


def test_helm_docs_call_out_tls_and_network_policy_for_production() -> None:
    helm_doc = _read("docs/deployment/helm.md")
    assert "ingress.tls" in helm_doc
    assert "networkPolicy.egress.rules" in helm_doc
    assert "不要直接把 chart 默认值当成生产 values" in helm_doc
    assert "UPLOAD_DEDUP_ENABLED=true" in helm_doc
    assert "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED=true" in helm_doc
    assert "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY" in helm_doc


def test_helm_runtime_validation_has_fail_fast_guards_for_multi_instance_risks() -> None:
    template = _read("deploy/helm/mimirq/templates/validate-runtime.yaml")
    assert "Distributed MimirQ deployments require ENV=production." in template
    assert "Distributed MimirQ deployments require DB_CREATE_ALL_ON_STARTUP=false." in template
    assert "Distributed MimirQ deployments require DB_RUNTIME_MIGRATIONS_ENABLED=false." in template
    assert "Distributed MimirQ deployments cannot use VECTOR_BACKEND=faiss or VECTOR_BACKEND=chroma." in template
    assert "Distributed MimirQ deployments with local document storage require persistence.uploads.accessModes to include ReadWriteMany." in template
    assert "migrations.enabled=true requires existingSecretName" in template
    assert template.count('"env" .Values.worker.extraEnv') >= 6
    assert "$workerDbCreateAllOnStartup" in template
    assert "$workerDbRuntimeMigrationsEnabled" in template
    assert "$workerVectorBackend" in template
    assert "$workerMinioDocumentsEnabled" in template


def test_helm_env_lookup_helper_uses_helm_supported_string_coercion() -> None:
    helper = _read("deploy/helm/mimirq/templates/_helpers.tpl")
    assert 'printf "%v"' in helper
    assert "str (" not in helper
    assert "str(" not in helper


def test_worker_deployment_uses_arq_check_for_readiness_only() -> None:
    template = _read("deploy/helm/mimirq/templates/deployment-worker.yaml")

    assert "readinessProbe:" in template
    assert "{{- toYaml .Values.worker.healthcheckCommand | nindent 16 }}" in template
    assert "livenessProbe:" not in template


def test_helm_migration_job_is_a_pre_install_upgrade_hook_backed_by_existing_secret() -> None:
    template = _read("deploy/helm/mimirq/templates/job-migrate.yaml")
    values = yaml.safe_load(_read("deploy/helm/mimirq/values.yaml"))
    assert '"helm.sh/hook": pre-install,pre-upgrade' in template
    assert '"helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded' in template
    assert 'secretRef:' in template
    assert 'name: {{ include "mimirq.secretName" . }}' in template
    assert "{{- toYaml .Values.migrations.command | nindent 12 }}" in template
    assert values["migrations"]["command"][:2] == ["python", "scripts/alembic_cli.py"]


def test_production_image_bundles_only_runtime_scripts_needed_by_helm_jobs() -> None:
    dockerfile = _read("docker/Dockerfile")

    expected_runtime_scripts = _helm_runtime_script_paths()

    for script_path in expected_runtime_scripts:
        assert Path(script_path).exists(), script_path
        assert script_path in dockerfile

    assert "COPY scripts/bootstrap_mimirq_models.py ./scripts/bootstrap_mimirq_models.py" in dockerfile
    assert "COPY scripts ./scripts" not in dockerfile


def test_runtime_scripts_bundled_for_helm_jobs_do_not_depend_on_other_local_scripts() -> None:
    expected_runtime_scripts = _helm_runtime_script_paths()

    for script_path in expected_runtime_scripts:
        tree = ast.parse(_read(script_path), filename=script_path)
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.add(str(node.module or ""))

        script_deps = sorted(
            module
            for module in imported_modules
            if module == "scripts" or module.startswith("scripts.")
        )
        assert script_deps == [], f"{script_path} unexpectedly depends on local scripts modules: {script_deps}"


def test_web_production_healthcheck_uses_ipv4_loopback() -> None:
    dockerfile = _read("web/Dockerfile.prod")
    assert "http://127.0.0.1:3000/" in dockerfile
    assert "http://localhost:3000/" not in dockerfile


def test_web_production_image_drops_next_build_cache() -> None:
    dockerfile = _read("web/Dockerfile.prod")
    assert "RUN rm -rf .next_build/cache" in dockerfile
