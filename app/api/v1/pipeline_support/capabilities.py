"""Parser backend availability probes and chunk strategy metadata.

Extracted verbatim from ``app/api/v1/pipeline.py``. Submodules must not import
``app.api.v1.pipeline`` (circular import).
"""
import importlib.metadata as importlib_metadata
from collections.abc import Callable

from app.api.schemas.pipeline import ChunkStrategyInfo, ParserBackendInfo
from app.core.config import settings
from app.core.optional_deps import check_dependency
from app.parsing.parsers.magic_pdf_parser import magicpdf_service_configured, resolve_magicpdf_models_dir
from app.parsing.utils.cli import resolve_cli_command
from app.rag.chunking import chunker_factory
from app.rag.chunking.recommendations import decorate_chunk_strategy_note


def _dependency_backend_availability(
    *,
    enabled_setting: str,
    enable_note: str,
    module: str,
    attr: str | None = None,
    package_name: str,
) -> tuple[bool, str | None]:
    _ = (module, attr)
    if not bool(getattr(settings, enabled_setting, False)):
        return False, enable_note
    try:
        importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError as exc:
        return False, f"{package_name} not installed: {str(exc)[:200] or 'package not found'}"
    return True, None


def _enabled_api_backend_availability(
    *,
    enabled_setting: str,
    api_url_setting: str,
    enable_note: str,
    api_url_note: str,
) -> tuple[bool, str | None]:
    enabled = bool(getattr(settings, enabled_setting, False))
    api_url = bool((getattr(settings, api_url_setting, "") or "").strip())
    if not enabled:
        return False, enable_note
    if not api_url:
        return False, api_url_note
    return True, None


def _mineru_backend_availability() -> tuple[bool, str | None]:
    available = bool(settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL))
    if available:
        return True, None
    return False, "Set MINERU_ENABLED=true and configure MINERU_API_TOKEN or MINERU_LOCAL_SERVER_URL."


def _deepseek_ocr_backend_availability() -> tuple[bool, str | None]:
    enabled = bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False))
    api_key = bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip())
    if not enabled:
        return False, "Set DEEPSEEK_OCR_ENABLED=true."
    if not api_key:
        return False, "Configure SILICONFLOW_API_KEY."
    return True, None


def _qianfan_ocr_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="QIANFAN_OCR_ENABLED",
        api_url_setting="QIANFAN_OCR_API_URL",
        enable_note="Set QIANFAN_OCR_ENABLED=true.",
        api_url_note="Configure QIANFAN_OCR_API_URL (e.g., http://localhost:2090/convert).",
    )


def _textin_backend_availability() -> tuple[bool, str | None]:
    enabled = bool(getattr(settings, "TEXTIN_ENABLED", False))
    api_url = bool((getattr(settings, "TEXTIN_API_URL", "") or "").strip())
    app_id = bool((getattr(settings, "TEXTIN_APP_ID", "") or "").strip())
    secret_code = bool((getattr(settings, "TEXTIN_SECRET_CODE", "") or "").strip())
    if not enabled:
        return False, "Set TEXTIN_ENABLED=true."
    if not api_url:
        return False, "Configure TEXTIN_API_URL."
    if not app_id:
        return False, "Configure TEXTIN_APP_ID."
    if not secret_code:
        return False, "Configure TEXTIN_SECRET_CODE."
    return True, None


def _etl4llm_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="ETL4LLM_ENABLED",
        api_url_setting="ETL4LLM_API_URL",
        enable_note="Set ETL4LLM_ENABLED=true.",
        api_url_note="Configure ETL4LLM_API_URL (e.g., http://localhost:10001/v1/etl4llm/predict).",
    )


def _marker_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="MARKER_ENABLED",
        api_url_setting="MARKER_API_URL",
        enable_note="Set MARKER_ENABLED=true.",
        api_url_note="Configure MARKER_API_URL (e.g., http://localhost:2080/convert).",
    )


def _paddle_vl_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="PADDLE_VL_ENABLED",
        api_url_setting="PADDLE_VL_API_URL",
        enable_note="Set PADDLE_VL_ENABLED=true.",
        api_url_note="Configure PADDLE_VL_API_URL (e.g., http://localhost:9030/convert).",
    )


def _olmocr_backend_availability() -> tuple[bool, str | None]:
    return _enabled_api_backend_availability(
        enabled_setting="OLMOCR_ENABLED",
        api_url_setting="OLMOCR_API_URL",
        enable_note="Set OLMOCR_ENABLED=true.",
        api_url_note="Configure OLMOCR_API_URL (e.g., http://localhost:2085/convert).",
    )


def _magicpdf_backend_availability() -> tuple[bool, str | None]:
    if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
        return False, "MAGIC_PDF_ENABLED=false"
    if magicpdf_service_configured(getattr(settings, "MAGIC_PDF_API_URL", "")):
        return True, None
    cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
    if not resolve_cli_command(cli):
        return False, f"MagicPDF CLI not found: {cli} (try activating the env or set MAGIC_PDF_CLI to full path)"
    models_dir = resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
    if not models_dir:
        return False, "MagicPDF models not found: mount PDF-Extract-Kit cache or set MAGIC_PDF_MODELS_DIR"
    return True, None


_PARSER_BACKEND_CHECKS: dict[str, Callable[[], tuple[bool, str | None]]] = {
    "mineru": _mineru_backend_availability,
    "deepdoc": lambda: (True, None)
    if bool(getattr(settings, "DEEPDOC_ENABLED", False))
    else (False, "Set DEEPDOC_ENABLED=true."),
    "deepseek_ocr": _deepseek_ocr_backend_availability,
    "qianfan_ocr": _qianfan_ocr_backend_availability,
    "textin": _textin_backend_availability,
    "markitdown": lambda: _dependency_backend_availability(
        enabled_setting="MARKITDOWN_ENABLED",
        enable_note="Set MARKITDOWN_ENABLED=true.",
        module="markitdown",
        attr="MarkItDown",
        package_name="markitdown",
    ),
    "docling": lambda: _dependency_backend_availability(
        enabled_setting="DOCLING_ENABLED",
        enable_note="Set DOCLING_ENABLED=true.",
        module="docling.document_converter",
        attr="DocumentConverter",
        package_name="docling",
    ),
    "etl4llm": _etl4llm_backend_availability,
    "marker": _marker_backend_availability,
    "paddle_vl": _paddle_vl_backend_availability,
    "olmocr": _olmocr_backend_availability,
    "magicpdf": _magicpdf_backend_availability,
}


def _pipeline_parser_backend_info(name: str) -> ParserBackendInfo:
    backend = (name or "").strip().lower()
    if backend == "auto":
        return ParserBackendInfo(name=backend, available=True, notes="Auto routes to the best enabled backend.")
    if backend == "basic":
        return ParserBackendInfo(name=backend, available=True, notes=None)

    check = _PARSER_BACKEND_CHECKS.get(backend)
    if check is None:
        return ParserBackendInfo(name=backend, available=False, notes="Unknown backend")
    available, notes = check()
    return ParserBackendInfo(name=backend, available=bool(available), notes=notes)


_AUTO_CHUNK_STRATEGY_NOTE = (
    "Auto-selects a chunker per document (git_commit_log/diff/patch/subtitles/logs/stacktrace/http_trace/"
    "terraform_plan/xml/junit_xml/sitemap_xml/maven_pom/xml_feed/openapi/github_actions/docker_compose/gitlab_ci/"
    "ansible_playbook/yaml/toml/sql/terraform/nginx/dockerfile/makefile/kv-config/jsonl/graphql/proto/api/"
    "changelog/csv/spreadsheet/chat/email/jira/postmortem/qa/qa_markdown/prd/sop/glossary/meeting_minutes/"
    "timeline/resume/slides/laws/paper/book/outline/transcript/rst/asciidoc/latex/org/wiki/html/markdown_table/"
    "markdown_frontmatter/markdown/json/plain text)."
)
_MANUSCRIPT_CHUNK_STRATEGY_NOTE = (
    "Preset for manuscript-like documents (git_commit_log/diff/patch/subtitles/logs/stacktrace/http_trace/"
    "terraform_plan/xml/junit_xml/sitemap_xml/maven_pom/xml_feed/openapi/github_actions/docker_compose/gitlab_ci/"
    "ansible_playbook/yaml/toml/sql/terraform/nginx/dockerfile/makefile/kv-config/jsonl/graphql/proto/api/"
    "changelog/csv/spreadsheet/chat/email/jira/postmortem/qa/qa_markdown/prd/sop/glossary/meeting_minutes/"
    "timeline/resume/slides/laws/paper/book/outline/transcript/rst/asciidoc/latex/org/wiki/html/markdown_table/"
    "markdown_frontmatter/markdown/...)."
)
_CHUNK_STRATEGY_NOTES = {
    "auto": _AUTO_CHUNK_STRATEGY_NOTE,
    "manuscript": _MANUSCRIPT_CHUNK_STRATEGY_NOTE,
    "pdf_layout": "PDF layout-aware chunking. Requires parsers that emit position tags like @@page\\tl\\tr\\tt\\tb##; strips tags from chunk text and records bbox/column metadata.",
    "outline": "Numbered-outline aware chunking (keeps section heading context).",
    "transcript": "Transcript/dialogue aware chunking (keeps speaker turns together).",
    "qa_pairs": "FAQ / Q&A aware chunking (keeps Q/A pairs together).",
    "paper": "Academic paper/report aware chunking (splits by common paper sections).",
    "book_structured": "Book chapter/part aware chunking (keeps chapter context).",
    "laws_structured": "Legal/policy aware chunking (splits by articles/clauses).",
    "email_thread": "Email thread aware chunking (keeps whole messages together).",
    "sop_steps": "SOP/procedure aware chunking (splits by Step/步骤 headings).",
    "glossary": "Glossary/dictionary aware chunking (splits by term-definition entries).",
    "resume_structured": "Resume/CV section-aware chunking (splits by common resume headings).",
    "presentation_slides": "Slide-aware chunking (splits by separators/markers like '---' or 'Slide 1').",
    "csv_rows": "CSV row-aware chunking (groups 'row N:' blocks; best with CsvParser output).",
    "spreadsheet_sheet": "Spreadsheet sheet-aware chunking (splits by '## Sheet:' sections; best with ExcelParser output).",
    "markdown_table": "Markdown table-aware chunking (avoids splitting rows; splits large tables at row boundaries).",
    "chat_history": "Timestamped chat history chunking (keeps whole messages together with message-level overlap).",
    "changelog": "Changelog/release-notes aware chunking (splits by release headings like '## [1.2.3] - 2024-01-01').",
    "log_events": "Log-events aware chunking (keeps multi-line log entries together; entry-level overlap).",
    "subtitles": "Subtitles aware chunking (SRT/VTT-like; splits by timecode cues).",
    "api_reference": "API reference aware chunking (splits by endpoint signatures like 'GET /path').",
    "diff_patch": "Diff/patch aware chunking (splits by file blocks and @@ hunks).",
    "git_commit_log": "Git commit-log aware chunking (splits by 'commit <sha>' blocks; preserves commit context even with patches).",
    "kv_config": "Key-value config aware chunking (groups KEY=VALUE entries; supports INI sections).",
    "qa_markdown": "Markdown Q/A aware chunking (supports bullets/headings like '**Q:**' / '### Q:').",
    "meeting_minutes": "Meeting-minutes aware chunking (splits by common sections like agenda/actions/decisions).",
    "timeline_events": "Timeline/date-event aware chunking (keeps dated events together).",
    "html_sections": "HTML heading-aware chunking (splits by <h1>-<h6> tags).",
    "rst_sections": "reStructuredText section-aware chunking (splits by underlined headings).",
    "asciidoc_sections": "AsciiDoc section-aware chunking (splits by '=' heading lines).",
    "latex_sections": "LaTeX section-aware chunking (splits by \\section/\\chapter commands).",
    "orgmode_sections": "Org-mode section-aware chunking (splits by '*' heading lines).",
    "mediawiki_sections": "MediaWiki section-aware chunking (splits by '== Heading ==' lines).",
    "yaml_manifest": "YAML manifest aware chunking (splits by '---' documents; extracts kind/name when present).",
    "toml_config": "TOML config aware chunking (splits by [tables] and groups key/value entries).",
    "sql_schema": "SQL schema/DDL aware chunking (splits by CREATE/ALTER statements).",
    "stacktrace": "Stacktrace aware chunking (groups traceback blocks; for timestamped logs prefer log_events).",
    "http_trace": "HTTP trace aware chunking (splits by HTTP request blocks; keeps request+response together).",
    "terraform_plan": "Terraform plan output aware chunking (splits by '# ... will be ...' change headers).",
    "xml_feed": "XML feed (RSS/Atom) item-aware chunking (splits by <item>/<entry> blocks).",
    "junit_xml": "JUnit XML report aware chunking (splits by <testcase> blocks; preserves offsets).",
    "sitemap_xml": "Sitemap XML aware chunking (splits by <url>/<sitemap> entry blocks).",
    "maven_pom": "Maven POM XML aware chunking (chunks <dependency>/<plugin> records; preserves offsets).",
    "openapi_spec": "OpenAPI/Swagger spec aware chunking (splits by per-path blocks under `paths:`).",
    "github_actions": "GitHub Actions workflow aware chunking (splits by job blocks under `jobs:`).",
    "docker_compose": "Docker Compose YAML aware chunking (splits by service blocks under `services:`).",
    "gitlab_ci": "GitLab CI YAML aware chunking (splits by top-level job/config blocks).",
    "ansible_playbook": "Ansible playbook aware chunking (splits by top-level plays; preserves offsets).",
    "dockerfile": "Dockerfile aware chunking (splits by FROM stages and instruction blocks).",
    "makefile": "Makefile aware chunking (splits by target blocks and recipes).",
    "nginx_config": "Nginx config aware chunking (splits by server blocks; brace-aware).",
    "terraform_hcl": "Terraform/HCL block-aware chunking (splits by resource/module/variable blocks; brace-aware).",
    "graphql_schema": "GraphQL schema aware chunking (splits by top-level type/input/enum/interface/union/scalar/directive/schema definitions).",
    "proto_schema": "Protocol Buffers schema aware chunking (splits by message/enum/service blocks; brace-aware).",
    "jira_ticket": "Jira/issue-ticket aware chunking (splits by common fields like Summary/Description/Steps/Expected/Actual).",
    "prd_spec": "PRD/spec aware chunking (splits by common sections like Background/Goals/Scope/Requirements/Acceptance/Risks).",
    "postmortem_report": "Incident postmortem/RCA aware chunking (splits by common sections like Summary/Impact/Timeline/Root Cause/Action Items).",
    "jsonl_records": "JSONL/NDJSON record-aware chunking (groups whole JSON records per line; preserves offsets).",
    "markdown_frontmatter": "Markdown frontmatter aware chunking (keeps YAML frontmatter, then chunks the body).",
    "sentence_window": "Sentence window chunking with sentence-level overlap.",
}


def _llama_index_chunk_availability() -> tuple[bool, str | None]:
    if not bool(getattr(settings, "LLAMA_INDEX_ENABLED", False)):
        return False, "Set LLAMA_INDEX_ENABLED=true."
    ok, err = check_dependency("llama_index.core")
    return ok, None if ok else f"llama-index-core not installed: {err}"


def _integrated_pipeline_chunk_note() -> str:
    vision_enabled = bool(getattr(settings, "VISION_LLM_ENABLED", False))
    vision_key_ok = bool(((getattr(settings, "VISION_LLM_API_KEY", "") or getattr(settings, "LLM_API_KEY", "") or "").strip()))
    vision_model = (getattr(settings, "VISION_LLM_MODEL", "") or "").strip()
    if vision_enabled and vision_key_ok:
        return f"Integrated pipeline (parse+chunk). Vision enrichment enabled (model={vision_model or 'configured'})."
    if vision_enabled and not vision_key_ok:
        return "Integrated pipeline (parse+chunk). Vision enrichment enabled but missing API key (set MIMIRQ_VISION_LLM_API_KEY or LLM_API_KEY)."
    return "Integrated pipeline (parse+chunk). Vision enrichment disabled by default (set MIMIRQ_VISION_LLM_ENABLED=true to enable)."


def _pipeline_chunk_strategy_info(name: str) -> ChunkStrategyInfo:
    strategy = (name or "").strip().lower()
    available = True
    notes = _CHUNK_STRATEGY_NOTES.get(strategy)
    if strategy.startswith("llama_index"):
        available, notes = _llama_index_chunk_availability()
    elif strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
        notes = _integrated_pipeline_chunk_note()
    elif strategy == "markdown":
        notes = "Alias of markdown_header."
    return ChunkStrategyInfo(name=strategy, available=bool(available), notes=decorate_chunk_strategy_note(strategy, notes))
