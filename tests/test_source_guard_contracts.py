import re
from pathlib import Path

import pytest

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
    "app/rag/evaluation/ragas.py",
    "app/rag/evaluation/regression_sample_builder.py",
    "app/rag/kg/extraction/extractor.py",
    "app/rag/preprocessing/diagnostics.py",
    "app/rag/preprocessing/processor.py",
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

FULL_SHA_RE = re.compile(r"@[0-9a-f]{40}(?:\s|$)")


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel_path", SILENT_PASS_GUARD_PATHS)
def test_critical_modules_do_not_use_silent_pass_fallbacks(rel_path: str) -> None:
    assert SILENT_PASS_RE.search(_read(rel_path)) is None, rel_path


@pytest.mark.parametrize("rel_path", REQUESTS_GUARD_PATHS)
def test_managed_http_modules_do_not_bypass_shared_clients(rel_path: str) -> None:
    assert "requests." not in _read(rel_path), rel_path


def test_time_context_helpers_do_not_use_naive_datetime_now() -> None:
    assert 'datetime.now().strftime("%Y-%m-%d %H:%M")' not in _read("app/rag/middleware/base.py")
    assert 'datetime.now().strftime("%Y%m%d_%H%M%S")' not in _read("app/deepdoc/parser/tcadp_parser.py")


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
