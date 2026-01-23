"""
Lightweight parsing and hierarchical chunk preview APIs:
- /pipeline/parse-preview: route parsing by file type (auto/Pandoc/MarkItDown/DeepDoc/MinerU/...), return Markdown + image refs
- /pipeline/chunk-preview: hierarchical Markdown chunking (paragraph/sentence) with highlight offsets
"""

from pathlib import Path
import shutil
import uuid
import zipfile
from uuid import UUID
from difflib import SequenceMatcher, unified_diff
import json
import re

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.api.schemas.pipeline import (
    ParsePreviewResponse,
    ChunkPreviewRequest,
    ChunkPreviewResponse,
    CleanPreviewRequest,
    CleanPreviewResponse,
    CleanRulesResponse,
    GovernanceAnalyzeRequest,
    GovernanceAnalyzeResponse,
    GovernanceIssue,
    RegexRuleModel,
    KeywordExtractRequest,
    KeywordExtractResponse,
    LLMCleanPreviewRequest,
    LLMCleanPreviewResponse,
    PipelineCapabilitiesResponse,
    ParserBackendInfo,
    ChunkStrategyInfo,
    ZipWithImagesResponse,
)
from app.api.schemas.governance_profile import (
    GovernanceProfileCreate,
    GovernanceProfileImportResponse,
    GovernanceProfileListResponse,
    GovernanceProfileOut,
    GovernanceProfileSummary,
    GovernanceProfileUpdate,
    GovernanceProfilePayload,
)
from app.parsing.backends import normalize_parser_backend
from app.parsing.factory import ParserFactory
from app.parsing.subprocess_runner import SubprocessCancelled, SubprocessWorkerError, run_subprocess_worker
from app.rag.chunking import hierarchical_chunk_markdown
from app.rag.chunking import chunker_factory
from app.parsing.utils.zip_processor import zip_image_processor
from app.parsing.utils.cli import resolve_cli_command
from app.api.dependencies.auth import get_current_account_id
from app.rag.preprocessing.cleaning import clean_markdown, RegexRule, build_repeated_line_signatures
from app.rag.preprocessing.rules import DEFAULT_MARKDOWN_RULES
from app.rag.preprocessing.boilerplate import remove_markdown_boilerplate
from app.rag.preprocessing.images import strip_images
from app.rag.preprocessing.pii_anonymizer import anonymize_pii
from app.rag.preprocessing.secrets import redact_secrets
from app.rag.preprocessing.tables import normalize_markdown_tables
from app.rag.preprocessing.code_blocks import strip_fenced_code_line_numbers
from app.rag.preprocessing.frontmatter import extract_markdown_frontmatter, extract_markdown_title
from app.rag.preprocessing.keyword import extract_keywords as extract_keywords_preview
from app.rag.preprocessing.language import detect_language
from app.rag.preprocessing.paragraph_dedup import drop_duplicate_paragraphs
from app.rag.preprocessing.references import trim_references_section
from app.rag.preprocessing.urls import normalize_urls
from app.rag.preprocessing.quality_filters import drop_if_low_density, drop_if_outline_only
from app.rag.preprocessing.diagnostics import analyze_governance
from app.rag.preprocessing.html_xpath import extract_text_from_html
from app.services.dataset_service import DatasetService
from app.services.prompt_resolver import resolve_prompt_template
from app.rag.core.errors import ConfigError
from app.rag.llm.factory import create_llm_client
from app.rag.llm.models import LLMMessage, LLMRole
from app.api.utils.upload import save_upload_file
from app.models.governance_profile import GovernanceProfile as DBGovernanceProfile
from app.services.governance_profiles import (
    builtin_profile_to_out,
    get_builtin_governance_profiles,
    validate_and_normalize_payload,
    validate_profile_key,
)

router = APIRouter()

_BUILTIN_GOVERNANCE_PROFILES = get_builtin_governance_profiles()
_BUILTIN_GOVERNANCE_BY_KEY = {p.key: p for p in _BUILTIN_GOVERNANCE_PROFILES}


def _profile_key_for_row(row: DBGovernanceProfile) -> str:
    raw = str(getattr(row, "key", "") or "").strip()
    if raw:
        return raw
    return f"custom:{str(row.id)}"


def _profile_summary_from_row(row: DBGovernanceProfile) -> GovernanceProfileSummary:
    return GovernanceProfileSummary(
        id=row.id,
        key=_profile_key_for_row(row),
        name=str(getattr(row, "name", "") or ""),
        description=getattr(row, "description", None),
        is_system=bool(getattr(row, "is_system", False)),
    )


def _profile_out_from_row(row: DBGovernanceProfile) -> GovernanceProfileOut:
    payload_raw = getattr(row, "payload", None)
    if not isinstance(payload_raw, dict):
        payload_raw = {}
    payload = GovernanceProfilePayload(**payload_raw)
    return GovernanceProfileOut(
        id=row.id,
        key=_profile_key_for_row(row),
        name=str(getattr(row, "name", "") or ""),
        description=getattr(row, "description", None),
        is_system=bool(getattr(row, "is_system", False)),
        payload=payload,
        created_at=getattr(row, "created_at", None),
        updated_at=getattr(row, "updated_at", None),
    )


def _resolve_profile_ref(
    *,
    db: Session,
    tenant_id: UUID,
    profile_ref: str,
) -> GovernanceProfileOut:
    ref = str(profile_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="profile_ref is required")

    if ref in _BUILTIN_GOVERNANCE_BY_KEY:
        return builtin_profile_to_out(_BUILTIN_GOVERNANCE_BY_KEY[ref])

    # Allow UUID lookup.
    try:
        ref_uuid = UUID(ref)
    except Exception:
        ref_uuid = None

    q = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    if ref_uuid is not None:
        row = q.filter(DBGovernanceProfile.id == ref_uuid).first()
        if row is not None:
            return _profile_out_from_row(row)
    # Allow key lookup (tenant-scoped).
    row = q.filter(DBGovernanceProfile.key == ref).first()
    if row is not None:
        return _profile_out_from_row(row)

    raise HTTPException(status_code=404, detail="Governance profile not found")


def _line_diff_stats(before: str, after: str) -> tuple[int, int, int]:
    """
    Compute coarse line-level diff stats for governance preview.

    Returns: (added_lines, removed_lines, changed_lines)
    - changed_lines counts "replaced" blocks (approximate: max(len(a), len(b))).
    """
    a = (before or "").splitlines()
    b = (after or "").splitlines()
    sm = SequenceMatcher(a=a, b=b, autojunk=False)
    added = 0
    removed = 0
    changed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            added += (j2 - j1)
        elif tag == "delete":
            removed += (i2 - i1)
        elif tag == "replace":
            # Count replaced region as changed (best-effort).
            changed += max(i2 - i1, j2 - j1)
    return added, removed, changed

def _unified_diff_text(before: str, after: str, *, max_lines: int) -> tuple[str | None, bool]:
    """
    Build a unified diff for UI preview (best-effort).

    Returns: (diff_text_or_none, truncated)
    """
    cap = max(0, int(max_lines or 0))
    if cap == 0:
        return None, False

    diff_lines = list(
        unified_diff(
            (before or "").splitlines(),
            (after or "").splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    if not diff_lines:
        return "", False
    if len(diff_lines) > cap:
        hidden = len(diff_lines) - cap
        diff_lines = diff_lines[:cap] + [f"... (truncated, {hidden} more lines)"]
        return "\n".join(diff_lines), True
    return "\n".join(diff_lines), False

def _check_python_import(module_name: str, *, attr: str | None = None) -> tuple[bool, str | None]:
    try:
        mod = __import__(module_name, fromlist=[attr] if attr else [])
        if attr:
            getattr(mod, attr)
        return True, None
    except (ImportError, AttributeError) as exc:
        return False, str(exc)[:200] or "import failed"


@router.get("/capabilities", response_model=PipelineCapabilitiesResponse)
async def get_pipeline_capabilities(
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Return available parsers and chunking strategies for the frontend.

    Note: only availability info is returned (no sensitive config like API keys).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    default_parser_backend = normalize_parser_backend(getattr(settings, "DEFAULT_PARSER_BACKEND", "auto") or "auto") or "auto"
    default_chunk_strategy = (getattr(settings, "DEFAULT_CHUNK_STRATEGY", "langchain_recursive") or "langchain_recursive").strip().lower()

    def magicpdf_available() -> tuple[bool, str | None]:
        if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
            return False, "MAGIC_PDF_ENABLED=false"
        cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
        if not resolve_cli_command(cli):
            return False, f"MagicPDF CLI not found: {cli} (try activating the env or set MAGIC_PDF_CLI to full path)"
        return True, None

    pdf_backends: list[ParserBackendInfo] = []
    for name in sorted(ParserFactory.SUPPORTED_PDF_BACKENDS):
        b = (name or "").strip().lower()
        available = False
        notes: str | None = None

        if b == "auto":
            available = True
            notes = "Auto routes to the best enabled backend."
        elif b == "basic":
            available = True
        elif b == "mineru":
            available = bool(settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL))
            if not available:
                notes = "Set MINERU_ENABLED=true and configure MINERU_API_TOKEN or MINERU_LOCAL_SERVER_URL."
        elif b == "deepdoc":
            available = bool(getattr(settings, "DEEPDOC_ENABLED", False))
            if not available:
                notes = "Set DEEPDOC_ENABLED=true."
        elif b == "deepseek_ocr":
            enabled = bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False))
            api_key = bool((getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip())
            available = bool(enabled and api_key)
            if not enabled:
                notes = "Set DEEPSEEK_OCR_ENABLED=true."
            elif not api_key:
                notes = "Configure SILICONFLOW_API_KEY."
        elif b == "markitdown":
            if not bool(getattr(settings, "MARKITDOWN_ENABLED", False)):
                available = False
                notes = "Set MARKITDOWN_ENABLED=true."
            else:
                ok, err = _check_python_import("markitdown", attr="MarkItDown")
                available = ok
                if not ok:
                    notes = f"markitdown not installed: {err}"
        elif b == "docling":
            if not bool(getattr(settings, "DOCLING_ENABLED", False)):
                available = False
                notes = "Set DOCLING_ENABLED=true."
            else:
                ok, err = _check_python_import("docling.document_converter", attr="DocumentConverter")
                available = ok
                if not ok:
                    notes = f"docling not installed: {err}"
        elif b == "etl4llm":
            enabled = bool(getattr(settings, "ETL4LLM_ENABLED", False))
            api_url = bool((getattr(settings, "ETL4LLM_API_URL", "") or "").strip())
            available = bool(enabled and api_url)
            if not enabled:
                notes = "Set ETL4LLM_ENABLED=true."
            elif not api_url:
                notes = "Configure ETL4LLM_API_URL (e.g., http://localhost:10001/v1/etl4llm/predict)."
        elif b == "marker":
            enabled = bool(getattr(settings, "MARKER_ENABLED", False))
            api_url = bool((getattr(settings, "MARKER_API_URL", "") or "").strip())
            available = bool(enabled and api_url)
            if not enabled:
                notes = "Set MARKER_ENABLED=true."
            elif not api_url:
                notes = "Configure MARKER_API_URL (e.g., http://localhost:2080/convert)."
        elif b == "paddle_vl":
            enabled = bool(getattr(settings, "PADDLE_VL_ENABLED", False))
            api_url = bool((getattr(settings, "PADDLE_VL_API_URL", "") or "").strip())
            available = bool(enabled and api_url)
            if not enabled:
                notes = "Set PADDLE_VL_ENABLED=true."
            elif not api_url:
                notes = "Configure PADDLE_VL_API_URL (e.g., http://localhost:9030/convert)."
        elif b == "olmocr":
            enabled = bool(getattr(settings, "OLMOCR_ENABLED", False))
            api_url = bool((getattr(settings, "OLMOCR_API_URL", "") or "").strip())
            available = bool(enabled and api_url)
            if not enabled:
                notes = "Set OLMOCR_ENABLED=true."
            elif not api_url:
                notes = "Configure OLMOCR_API_URL (e.g., http://localhost:2085/convert)."
        elif b == "magicpdf":
            available, notes = magicpdf_available()
        else:  # pragma: no cover
            available = False
            notes = "Unknown backend"

        pdf_backends.append(ParserBackendInfo(name=b, available=bool(available), notes=notes))

    chunk_strategies: list[ChunkStrategyInfo] = []
    # Expose all strategies known to the backend (frontends may choose a subset).
    all_strats = set(chunker_factory.SUPPORTED_STRATEGIES.keys()) | set(chunker_factory.RAGFLOW_STRATEGIES)
    for name in sorted(all_strats):
        s = (name or "").strip().lower()
        available = True
        notes: str | None = None
        if s == "auto":
            available = True
            notes = "Auto-selects a chunker per document (git_commit_log/diff/patch/subtitles/logs/stacktrace/http_trace/terraform_plan/xml/junit_xml/sitemap_xml/maven_pom/xml_feed/openapi/github_actions/docker_compose/gitlab_ci/ansible_playbook/yaml/toml/sql/terraform/nginx/dockerfile/makefile/kv-config/jsonl/graphql/proto/api/changelog/csv/spreadsheet/chat/email/jira/postmortem/qa/qa_markdown/prd/sop/glossary/meeting_minutes/timeline/resume/slides/laws/paper/book/outline/transcript/rst/asciidoc/latex/org/wiki/html/markdown_table/markdown_frontmatter/markdown/json/plain text)."
        elif s == "manuscript":
            available = True
            notes = "Preset for manuscript-like documents (git_commit_log/diff/patch/subtitles/logs/stacktrace/http_trace/terraform_plan/xml/junit_xml/sitemap_xml/maven_pom/xml_feed/openapi/github_actions/docker_compose/gitlab_ci/ansible_playbook/yaml/toml/sql/terraform/nginx/dockerfile/makefile/kv-config/jsonl/graphql/proto/api/changelog/csv/spreadsheet/chat/email/jira/postmortem/qa/qa_markdown/prd/sop/glossary/meeting_minutes/timeline/resume/slides/laws/paper/book/outline/transcript/rst/asciidoc/latex/org/wiki/html/markdown_table/markdown_frontmatter/markdown/...)."
        elif s == "outline":
            available = True
            notes = "Numbered-outline aware chunking (keeps section heading context)."
        elif s == "transcript":
            available = True
            notes = "Transcript/dialogue aware chunking (keeps speaker turns together)."
        elif s == "qa_pairs":
            available = True
            notes = "FAQ / Q&A aware chunking (keeps Q/A pairs together)."
        elif s == "paper":
            available = True
            notes = "Academic paper/report aware chunking (splits by common paper sections)."
        elif s == "book_structured":
            available = True
            notes = "Book chapter/part aware chunking (keeps chapter context)."
        elif s == "laws_structured":
            available = True
            notes = "Legal/policy aware chunking (splits by articles/clauses)."
        elif s == "email_thread":
            available = True
            notes = "Email thread aware chunking (keeps whole messages together)."
        elif s == "sop_steps":
            available = True
            notes = "SOP/procedure aware chunking (splits by Step/步骤 headings)."
        elif s == "glossary":
            available = True
            notes = "Glossary/dictionary aware chunking (splits by term-definition entries)."
        elif s == "resume_structured":
            available = True
            notes = "Resume/CV section-aware chunking (splits by common resume headings)."
        elif s == "presentation_slides":
            available = True
            notes = "Slide-aware chunking (splits by separators/markers like '---' or 'Slide 1')."
        elif s == "csv_rows":
            available = True
            notes = "CSV row-aware chunking (groups 'row N:' blocks; best with CsvParser output)."
        elif s == "spreadsheet_sheet":
            available = True
            notes = "Spreadsheet sheet-aware chunking (splits by '## Sheet:' sections; best with ExcelParser output)."
        elif s == "markdown_table":
            available = True
            notes = "Markdown table-aware chunking (avoids splitting rows; splits large tables at row boundaries)."
        elif s == "chat_history":
            available = True
            notes = "Timestamped chat history chunking (keeps whole messages together with message-level overlap)."
        elif s == "changelog":
            available = True
            notes = "Changelog/release-notes aware chunking (splits by release headings like '## [1.2.3] - 2024-01-01')."
        elif s == "log_events":
            available = True
            notes = "Log-events aware chunking (keeps multi-line log entries together; entry-level overlap)."
        elif s == "subtitles":
            available = True
            notes = "Subtitles aware chunking (SRT/VTT-like; splits by timecode cues)."
        elif s == "api_reference":
            available = True
            notes = "API reference aware chunking (splits by endpoint signatures like 'GET /path')."
        elif s == "diff_patch":
            available = True
            notes = "Diff/patch aware chunking (splits by file blocks and @@ hunks)."
        elif s == "git_commit_log":
            available = True
            notes = "Git commit-log aware chunking (splits by 'commit <sha>' blocks; preserves commit context even with patches)."
        elif s == "kv_config":
            available = True
            notes = "Key-value config aware chunking (groups KEY=VALUE entries; supports INI sections)."
        elif s == "qa_markdown":
            available = True
            notes = "Markdown Q/A aware chunking (supports bullets/headings like '**Q:**' / '### Q:')."
        elif s == "meeting_minutes":
            available = True
            notes = "Meeting-minutes aware chunking (splits by common sections like agenda/actions/decisions)."
        elif s == "timeline_events":
            available = True
            notes = "Timeline/date-event aware chunking (keeps dated events together)."
        elif s == "html_sections":
            available = True
            notes = "HTML heading-aware chunking (splits by <h1>-<h6> tags)."
        elif s == "rst_sections":
            available = True
            notes = "reStructuredText section-aware chunking (splits by underlined headings)."
        elif s == "asciidoc_sections":
            available = True
            notes = "AsciiDoc section-aware chunking (splits by '=' heading lines)."
        elif s == "latex_sections":
            available = True
            notes = "LaTeX section-aware chunking (splits by \\section/\\chapter commands)."
        elif s == "orgmode_sections":
            available = True
            notes = "Org-mode section-aware chunking (splits by '*' heading lines)."
        elif s == "mediawiki_sections":
            available = True
            notes = "MediaWiki section-aware chunking (splits by '== Heading ==' lines)."
        elif s == "yaml_manifest":
            available = True
            notes = "YAML manifest aware chunking (splits by '---' documents; extracts kind/name when present)."
        elif s == "toml_config":
            available = True
            notes = "TOML config aware chunking (splits by [tables] and groups key/value entries)."
        elif s == "sql_schema":
            available = True
            notes = "SQL schema/DDL aware chunking (splits by CREATE/ALTER statements)."
        elif s == "stacktrace":
            available = True
            notes = "Stacktrace aware chunking (groups traceback blocks; for timestamped logs prefer log_events)."
        elif s == "http_trace":
            available = True
            notes = "HTTP trace aware chunking (splits by HTTP request blocks; keeps request+response together)."
        elif s == "terraform_plan":
            available = True
            notes = "Terraform plan output aware chunking (splits by '# ... will be ...' change headers)."
        elif s == "xml_feed":
            available = True
            notes = "XML feed (RSS/Atom) item-aware chunking (splits by <item>/<entry> blocks)."
        elif s == "junit_xml":
            available = True
            notes = "JUnit XML report aware chunking (splits by <testcase> blocks; preserves offsets)."
        elif s == "sitemap_xml":
            available = True
            notes = "Sitemap XML aware chunking (splits by <url>/<sitemap> entry blocks)."
        elif s == "maven_pom":
            available = True
            notes = "Maven POM XML aware chunking (chunks <dependency>/<plugin> records; preserves offsets)."
        elif s == "openapi_spec":
            available = True
            notes = "OpenAPI/Swagger spec aware chunking (splits by per-path blocks under `paths:`)."
        elif s == "github_actions":
            available = True
            notes = "GitHub Actions workflow aware chunking (splits by job blocks under `jobs:`)."
        elif s == "docker_compose":
            available = True
            notes = "Docker Compose YAML aware chunking (splits by service blocks under `services:`)."
        elif s == "gitlab_ci":
            available = True
            notes = "GitLab CI YAML aware chunking (splits by top-level job/config blocks)."
        elif s == "ansible_playbook":
            available = True
            notes = "Ansible playbook aware chunking (splits by top-level plays; preserves offsets)."
        elif s == "dockerfile":
            available = True
            notes = "Dockerfile aware chunking (splits by FROM stages and instruction blocks)."
        elif s == "makefile":
            available = True
            notes = "Makefile aware chunking (splits by target blocks and recipes)."
        elif s == "nginx_config":
            available = True
            notes = "Nginx config aware chunking (splits by server blocks; brace-aware)."
        elif s == "terraform_hcl":
            available = True
            notes = "Terraform/HCL block-aware chunking (splits by resource/module/variable blocks; brace-aware)."
        elif s == "graphql_schema":
            available = True
            notes = "GraphQL schema aware chunking (splits by top-level type/input/enum/interface/union/scalar/directive/schema definitions)."
        elif s == "proto_schema":
            available = True
            notes = "Protocol Buffers schema aware chunking (splits by message/enum/service blocks; brace-aware)."
        elif s == "jira_ticket":
            available = True
            notes = "Jira/issue-ticket aware chunking (splits by common fields like Summary/Description/Steps/Expected/Actual)."
        elif s == "prd_spec":
            available = True
            notes = "PRD/spec aware chunking (splits by common sections like Background/Goals/Scope/Requirements/Acceptance/Risks)."
        elif s == "postmortem_report":
            available = True
            notes = "Incident postmortem/RCA aware chunking (splits by common sections like Summary/Impact/Timeline/Root Cause/Action Items)."
        elif s == "jsonl_records":
            available = True
            notes = "JSONL/NDJSON record-aware chunking (groups whole JSON records per line; preserves offsets)."
        elif s == "markdown_frontmatter":
            available = True
            notes = "Markdown frontmatter aware chunking (keeps YAML frontmatter, then chunks the body)."
        elif s == "sentence_window":
            available = True
            notes = "Sentence window chunking with sentence-level overlap."
        if s.startswith("llama_index"):
            if not bool(getattr(settings, "LLAMA_INDEX_ENABLED", False)):
                available = False
                notes = "Set LLAMA_INDEX_ENABLED=true."
            else:
                ok, err = _check_python_import("llama_index.core")
                available = ok
                if not ok:
                    notes = f"llama-index-core not installed: {err}"
        elif s in chunker_factory.RAGFLOW_STRATEGIES:
            available = True
            notes = "RAGFlow integrated pipeline (parse+chunk)."
        elif s == "markdown":
            available = True
            notes = "Alias of markdown_header."

        chunk_strategies.append(ChunkStrategyInfo(name=s, available=bool(available), notes=notes))

    return PipelineCapabilitiesResponse(
        default_parser_backend=default_parser_backend,
        default_chunk_strategy=default_chunk_strategy,
        pdf_backends=pdf_backends,
        chunk_strategies=chunk_strategies,
    )


@router.get("/governance-profiles", response_model=GovernanceProfileListResponse)
async def list_governance_profiles(
    q: str | None = None,
    include_builtin: bool = True,
    limit: int = 200,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    List governance profiles (built-in + tenant custom profiles).

    Notes:
    - Built-in profiles are shipped in code (read-only).
    - Custom profiles are stored in DB (tenant-scoped).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = (q or "").strip().lower()
    items: list[GovernanceProfileSummary] = []
    builtin_count = 0

    if include_builtin:
        for p in _BUILTIN_GOVERNANCE_PROFILES:
            if query and query not in (p.name.lower() + " " + p.description.lower()):
                continue
            items.append(
                GovernanceProfileSummary(
                    id=None,
                    key=p.key,
                    name=p.name,
                    description=p.description,
                    is_system=True,
                )
            )
        builtin_count = len(items)

    q_db = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    if query:
        like = f"%{query}%"
        # Avoid depending on database-specific full-text features.
        q_db = q_db.filter(
            (DBGovernanceProfile.name.ilike(like))
            | (DBGovernanceProfile.description.ilike(like))
            | (DBGovernanceProfile.key.ilike(like))
        )

    total_custom = int(q_db.count() or 0)
    rows = q_db.order_by(DBGovernanceProfile.updated_at.desc()).limit(min(int(limit or 200), 200)).all()
    items.extend([_profile_summary_from_row(r) for r in rows])

    return GovernanceProfileListResponse(total=(builtin_count + total_custom), items=items)


@router.post("/governance-profiles", response_model=GovernanceProfileOut, status_code=201)
async def create_governance_profile(
    body: GovernanceProfileCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    name = str(body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    try:
        key = validate_profile_key(body.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if key:
        exists = (
            db.query(DBGovernanceProfile.id)
            .filter(DBGovernanceProfile.tenant_id == tenant_id, DBGovernanceProfile.key == key)
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="profile key already exists")

    try:
        payload = validate_and_normalize_payload(body.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    row = DBGovernanceProfile(
        tenant_id=tenant_id,
        key=key,
        name=name[:200],
        description=(str(body.description).strip()[:2000] if body.description is not None else None),
        is_system=False,
        payload=payload.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _profile_out_from_row(row)


@router.get("/governance-profiles/{profile_ref}", response_model=GovernanceProfileOut)
async def get_governance_profile(
    profile_ref: str,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    return _resolve_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref)


@router.patch("/governance-profiles/{profile_ref}", response_model=GovernanceProfileOut)
async def update_governance_profile(
    profile_ref: str,
    body: GovernanceProfileUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    ref = str(profile_ref or "").strip()
    if ref in _BUILTIN_GOVERNANCE_BY_KEY:
        raise HTTPException(status_code=403, detail="built-in profiles are read-only")

    # Resolve custom profile row by UUID or key.
    try:
        ref_uuid = UUID(ref)
    except Exception:
        ref_uuid = None

    q = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    row = q.filter(DBGovernanceProfile.id == ref_uuid).first() if ref_uuid else q.filter(DBGovernanceProfile.key == ref).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Governance profile not found")

    if body.name is not None:
        name = str(body.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name must not be empty")
        row.name = name[:200]

    if body.description is not None:
        desc = str(body.description or "").strip()
        row.description = desc[:2000] if desc else None

    if body.payload is not None:
        try:
            payload = validate_and_normalize_payload(body.payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row.payload = payload.model_dump()

    db.commit()
    db.refresh(row)
    return _profile_out_from_row(row)


@router.delete("/governance-profiles/{profile_ref}", status_code=204)
async def delete_governance_profile(
    profile_ref: str,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    ref = str(profile_ref or "").strip()
    if ref in _BUILTIN_GOVERNANCE_BY_KEY:
        raise HTTPException(status_code=403, detail="built-in profiles are read-only")

    try:
        ref_uuid = UUID(ref)
    except Exception:
        ref_uuid = None

    q = db.query(DBGovernanceProfile).filter(DBGovernanceProfile.tenant_id == tenant_id)
    row = q.filter(DBGovernanceProfile.id == ref_uuid).first() if ref_uuid else q.filter(DBGovernanceProfile.key == ref).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Governance profile not found")

    db.delete(row)
    db.commit()
    return None


@router.post("/governance-profiles/import", response_model=GovernanceProfileImportResponse)
async def import_governance_profiles(
    file: UploadFile = File(...),
    overwrite: bool = Form(default=False),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Import governance profile scripts (JSON).

    Security:
    - Only declarative JSON is accepted (no executable code).
    - Strong validation on regex rules and option keys is applied server-side.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    max_bytes = 256 * 1024
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Profile script too large (max={max_bytes} bytes)")

    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    if isinstance(data, dict) and isinstance(data.get("profiles"), list):
        raw_profiles = data.get("profiles") or []
    else:
        raw_profiles = [data]

    created = 0
    updated = 0
    out_items: list[GovernanceProfileSummary] = []

    for item in raw_profiles:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Invalid profile item (expected object)")

        unknown_item_keys = set(item.keys()) - {"name", "description", "key", "payload"}
        if unknown_item_keys:
            unknown_sorted = ", ".join(sorted(map(str, unknown_item_keys))[:20])
            raise HTTPException(status_code=400, detail=f"Unknown profile fields: {unknown_sorted}")

        name = str(item.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Profile name is required")

        raw_key = item.get("key")
        try:
            key = validate_profile_key(raw_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        payload_raw = item.get("payload")
        if not isinstance(payload_raw, dict):
            raise HTTPException(status_code=400, detail="payload is required and must be an object")

        unknown_payload_keys = set(payload_raw.keys()) - {"version", "input_formats", "pipeline_patch", "regex_rules"}
        if unknown_payload_keys:
            unknown_sorted = ", ".join(sorted(map(str, unknown_payload_keys))[:20])
            raise HTTPException(status_code=400, detail=f"Unknown payload fields: {unknown_sorted}")

        try:
            payload = GovernanceProfilePayload(**payload_raw)
            payload = validate_and_normalize_payload(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid payload: {str(exc)[:200]}") from exc

        description = item.get("description")
        desc = str(description or "").strip()[:2000] if description is not None else None

        existing = None
        if key:
            existing = (
                db.query(DBGovernanceProfile)
                .filter(DBGovernanceProfile.tenant_id == tenant_id, DBGovernanceProfile.key == key)
                .first()
            )

        if existing is not None:
            if not overwrite:
                raise HTTPException(status_code=409, detail=f"Profile key already exists: {key}")
            existing.name = name[:200]
            existing.description = desc
            existing.payload = payload.model_dump()
            updated += 1
            out_items.append(_profile_summary_from_row(existing))
        else:
            row = DBGovernanceProfile(
                tenant_id=tenant_id,
                key=key,
                name=name[:200],
                description=desc,
                is_system=False,
                payload=payload.model_dump(),
            )
            db.add(row)
            db.flush()
            created += 1
            out_items.append(_profile_summary_from_row(row))

    db.commit()
    return GovernanceProfileImportResponse(created=created, updated=updated, items=out_items)


@router.get("/governance-profiles/{profile_ref}/export")
async def export_governance_profile(
    profile_ref: str,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    DatasetService.ensure_member(db, tenant_id, account_id)
    profile = _resolve_profile_ref(db=db, tenant_id=tenant_id, profile_ref=profile_ref)

    payload = profile.payload.model_dump()
    export_obj = {
        "name": profile.name,
        "description": profile.description,
        "key": profile.key,
        "payload": payload,
    }

    # Best-effort safe filename.
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(profile.key or "profile"))[:64]
    filename = f"{safe_key}.governance-profile.json"
    content = json.dumps(export_obj, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )


@router.post("/parse-preview", response_model=ParsePreviewResponse)
async def parse_preview(
    request: Request,
    file: UploadFile = File(...),
    parser_backend: str | None = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Parse a file into a Markdown preview without persisting it; extract inline images to uploads/{tenant}/images.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {settings.allowed_extensions_list}",
        )

    # Save to a temporary path.
    preview_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    run_dir = preview_dir / uuid.uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_path = run_dir / f"input{file_ext}"
    try:
        await save_upload_file(file, temp_path, max_bytes=settings.MAX_FILE_SIZE)

        result = await run_subprocess_worker(
            tenant_id=tenant_id,
            payload={
                "action": "pipeline_parse_preview",
                "tenant_id": str(tenant_id),
                "file_path": str(temp_path),
                "parser_backend": parser_backend,
            },
            disconnect_check=request.is_disconnected,
            timeout_sec=float(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30),
        )
        return result
    except SubprocessCancelled:
        raise HTTPException(status_code=499, detail="Client closed request")
    except SubprocessWorkerError as e:
        err_type = (e.details or {}).get("type")
        if err_type == "ValueError":
            raise HTTPException(status_code=400, detail=str(e))
        raise HTTPException(status_code=500, detail="Failed to parse preview")
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@router.post("/chunk-preview", response_model=ChunkPreviewResponse)
async def chunk_preview(
    body: ChunkPreviewRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Perform hierarchical chunking for Markdown text and return highlight offsets.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    chunks = hierarchical_chunk_markdown(body.markdown)
    return ChunkPreviewResponse(**chunks)


@router.post("/clean-preview", response_model=CleanPreviewResponse)
async def clean_preview(
    body: CleanPreviewRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Preview governance-style cleaning for Markdown (no persistence) to compare before/after.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    raw_input = body.markdown or ""

    input_text = raw_input
    if body.input_format == "html":
        html = raw_input
        # Optional image stripping before XPath extraction.
        if str(body.remove_images or "none").strip().lower() in {"decorative", "all"}:
            html = strip_images(html, mode=str(body.remove_images).strip().lower()).text  # type: ignore[arg-type]
        extracted = extract_text_from_html(html, xpath=body.html_xpath)
        if body.html_xpath and extracted.xpath_error and extracted.xpath_error.startswith("xpath_failed:"):
            raise HTTPException(status_code=400, detail=f"Invalid XPath: {extracted.xpath_error}")
        input_text = extracted.text or ""

    frontmatter: dict | None = None
    title: str | None = None
    tags: list[str] | None = None
    if body.extract_frontmatter or body.strip_frontmatter:
        try:
            fm = extract_markdown_frontmatter(input_text, strip=bool(body.strip_frontmatter))
        except Exception:
            fm = None
        if fm is not None:
            data = getattr(fm, "data", None)
            if isinstance(data, dict) and data:
                frontmatter = dict(data)
                raw_title = frontmatter.get("title")
                if isinstance(raw_title, str) and raw_title.strip():
                    title = raw_title.strip()[:200]
                raw_tags = (
                    frontmatter.get("tags")
                    or frontmatter.get("tag")
                    or frontmatter.get("categories")
                    or frontmatter.get("category")
                    or frontmatter.get("keywords")
                )
                if isinstance(raw_tags, list):
                    cleaned: list[str] = []
                    seen: set[str] = set()
                    for item in raw_tags:
                        if item is None:
                            continue
                        s = str(item).strip()
                        if not s:
                            continue
                        key = s.casefold()
                        if key in seen:
                            continue
                        seen.add(key)
                        cleaned.append(s[:64])
                    if cleaned:
                        tags = cleaned[:50]
                elif isinstance(raw_tags, str) and raw_tags.strip():
                    parts = [p.strip() for p in raw_tags.replace(";", ",").split(",") if p.strip()]
                    if parts:
                        tags = parts[:50]

            if body.strip_frontmatter:
                input_text = getattr(fm, "stripped_text", input_text) or ""

    baseline_text = input_text or ""

    analysis_opts = {
        "remove_control_chars": bool(body.remove_control_chars),
        "unwrap_lines": bool(body.unwrap_lines),
        "remove_common_lines": bool(body.remove_common_lines),
        "remove_boilerplate": bool(body.remove_boilerplate),
        "normalize_tables": bool(body.normalize_tables),
        "normalize_urls": bool(body.normalize_urls),
        "normalize_urls_strip_tracking": bool(body.normalize_urls_strip_tracking),
        "remove_images": str(body.remove_images or "none"),
        "drop_outline_only": bool(body.drop_outline_only),
        "drop_outline_min_content_chars": int(body.drop_outline_min_content_chars or 0),
        "drop_outline_max_heading_ratio": float(body.drop_outline_max_heading_ratio or 0.0),
        "drop_low_density": bool(body.drop_low_density),
        "drop_low_density_threshold": float(body.drop_low_density_threshold or 0.0),
    }

    def _analyze(after_text: str) -> tuple[list[GovernanceIssue], dict[str, object]]:
        issues, patch = analyze_governance(
            baseline_text,
            after_text,
            input_format=str(body.input_format or "markdown"),
            options=analysis_opts,
        )
        out: list[GovernanceIssue] = []
        for it in issues:
            out.append(
                GovernanceIssue(
                    code=str(it.code),
                    severity=it.severity,  # type: ignore[arg-type]
                    message=str(it.message),
                    count=int(getattr(it, "count", 0) or 0),
                    samples=list(getattr(it, "samples", None) or []),
                    suggested_pipeline_patch=dict(getattr(it, "suggested_pipeline_patch", None) or {}),
                )
            )
        return out, dict(patch or {})

    custom_rules = [RegexRule(pattern=r.pattern, repl=r.repl, flags=r.flags) for r in (body.rules or [])]
    base_rules = list(DEFAULT_MARKDOWN_RULES) if body.use_default_rules else []
    rules = base_rules + custom_rules
    common_lines = (
        build_repeated_line_signatures(
            baseline_text,
            min_occurrences=body.common_lines_min_occurrences,
            max_line_length=body.unwrap_max_line_length,
        )
        if body.remove_common_lines
        else None
    )
    result = clean_markdown(
        baseline_text,
        rules=rules,
        normalize_line_endings=body.normalize_line_endings,
        trim_trailing_spaces=body.trim_trailing_spaces,
        collapse_blank_lines=body.collapse_blank_lines,
        max_blank_lines=body.max_blank_lines,
        remove_control_chars=body.remove_control_chars,
        remove_toc_lines=body.remove_toc_lines,
        remove_noise_lines=body.remove_noise_lines,
        unwrap_lines=body.unwrap_lines,
        remove_common_lines=body.remove_common_lines,
        common_lines=common_lines,
        unwrap_max_line_length=body.unwrap_max_line_length,
        noise_min_chars=body.noise_min_chars,
        noise_ratio_threshold=body.noise_ratio_threshold,
    )

    text = result.markdown

    if body.normalize_tables:
        text = normalize_markdown_tables(text).text

    if body.strip_code_line_numbers:
        text = strip_fenced_code_line_numbers(text).text

    if body.remove_boilerplate:
        text = remove_markdown_boilerplate(text).text

    if str(body.remove_images or "none").strip().lower() in {"decorative", "all"}:
        text = strip_images(text, mode=str(body.remove_images).strip().lower()).text  # type: ignore[arg-type]

    pii_hits: dict[str, int] | None = None
    secrets_hits: dict[str, int] | None = None
    if body.pii_anonymize:
        pii = anonymize_pii(text, enabled=True, mode=str(body.pii_mode or "mask"), mask=str(body.pii_mask or "[REDACTED]"))  # type: ignore[arg-type]
        text = pii.text
        pii_hits = pii.hits or {}

    if body.secrets_redact:
        sec = redact_secrets(text, enabled=True, mode=str(body.secrets_mode or "mask"), mask=str(body.secrets_mask or "[SECRET]"))  # type: ignore[arg-type]
        text = sec.text
        secrets_hits = sec.hits or {}

    paragraphs_dropped = 0
    references_removed_lines = 0
    urls_changed = 0

    if body.drop_duplicate_paragraphs:
        try:
            para = drop_duplicate_paragraphs(
                text,
                min_occurrences=int(body.drop_duplicate_paragraphs_min_occurrences or 0),
                min_paragraph_chars=int(body.drop_duplicate_paragraphs_min_chars or 0),
                max_paragraph_chars=int(body.drop_duplicate_paragraphs_max_chars or 0),
            )
            text = para.text
            paragraphs_dropped = int(getattr(para, "paragraphs_dropped", 0) or 0)
        except Exception:
            pass

    if body.trim_references:
        try:
            ref = trim_references_section(text)
            text = ref.text
            references_removed_lines = int(getattr(ref, "removed_lines", 0) or 0)
        except Exception:
            pass

    if body.normalize_urls:
        try:
            url = normalize_urls(text, strip_tracking=bool(body.normalize_urls_strip_tracking))
            text = url.text
            urls_changed = int(getattr(url, "urls_changed", 0) or 0)
        except Exception:
            pass

    if body.drop_outline_only:
        decision = drop_if_outline_only(
            text,
            min_content_chars=int(body.drop_outline_min_content_chars or 0),
            max_heading_ratio=float(body.drop_outline_max_heading_ratio or 0.0),
        )
        if decision.dropped:
            added, removed, changed_lines = _line_diff_stats(baseline_text, "")
            diff_unified, diff_truncated = (None, False)
            if body.include_diff:
                diff_unified, diff_truncated = _unified_diff_text(baseline_text, "", max_lines=body.diff_max_lines)
            issues_out, suggested_patch = _analyze("")
            return CleanPreviewResponse(
                markdown="",
                applied_rules=result.applied_rules,
                changed=True,
                dropped=True,
                drop_reason=decision.reason or "outline_only",
                pii_hits=pii_hits,
                secrets_hits=secrets_hits,
                frontmatter=frontmatter,
                title=title,
                tags=tags,
                urls_changed=int(urls_changed),
                paragraphs_dropped=int(paragraphs_dropped),
                references_removed_lines=int(references_removed_lines),
                input_chars=len(baseline_text),
                output_chars=0,
                input_lines=len((baseline_text or "").splitlines()),
                output_lines=0,
                added_lines=added,
                removed_lines=removed,
                changed_lines=changed_lines,
                diff_unified=diff_unified,
                diff_truncated=bool(diff_truncated),
                issues=issues_out,
                suggested_pipeline_patch=suggested_patch,
            )

    if body.drop_low_density:
        decision = drop_if_low_density(text, threshold=float(body.drop_low_density_threshold or 0.0))
        if decision.dropped:
            added, removed, changed_lines = _line_diff_stats(baseline_text, "")
            diff_unified, diff_truncated = (None, False)
            if body.include_diff:
                diff_unified, diff_truncated = _unified_diff_text(baseline_text, "", max_lines=body.diff_max_lines)
            issues_out, suggested_patch = _analyze("")
            return CleanPreviewResponse(
                markdown="",
                applied_rules=result.applied_rules,
                changed=True,
                dropped=True,
                drop_reason=decision.reason or "low_density",
                pii_hits=pii_hits,
                secrets_hits=secrets_hits,
                frontmatter=frontmatter,
                title=title,
                tags=tags,
                urls_changed=int(urls_changed),
                paragraphs_dropped=int(paragraphs_dropped),
                references_removed_lines=int(references_removed_lines),
                input_chars=len(baseline_text),
                output_chars=0,
                input_lines=len((baseline_text or "").splitlines()),
                output_lines=0,
                added_lines=added,
                removed_lines=removed,
                changed_lines=changed_lines,
                diff_unified=diff_unified,
                diff_truncated=bool(diff_truncated),
                issues=issues_out,
                suggested_pipeline_patch=suggested_patch,
            )

    if title is None:
        try:
            title = extract_markdown_title(text)
        except Exception:
            title = None

    language: str | None = None
    language_confidence: float | None = None
    if body.detect_language:
        try:
            lang = detect_language(text, min_chars=int(body.language_min_chars or 0))
            language = str(getattr(lang, "language", "") or "").strip() or None
            language_confidence = float(getattr(lang, "confidence", 0.0) or 0.0)
        except Exception:
            language = None
            language_confidence = None

    keywords: list[str] | None = None
    if body.extract_keywords:
        try:
            max_chars = max(0, int(body.keywords_max_chars or 0))
            snippet = text[:max_chars] if max_chars > 0 else text
            kws = extract_keywords_preview(
                snippet,
                provider=str(body.keywords_provider or "auto"),
                top_k=int(body.keywords_top_k or 10),
            )
            keywords = list(kws) if kws else None
        except Exception:
            keywords = None

    diff_unified, diff_truncated = (None, False)
    if body.include_diff:
        diff_unified, diff_truncated = _unified_diff_text(baseline_text, text, max_lines=body.diff_max_lines)
    added, removed, changed_lines = _line_diff_stats(baseline_text, text)
    issues_out, suggested_patch = _analyze(text)
    return CleanPreviewResponse(
        markdown=text,
        applied_rules=result.applied_rules,
        changed=bool(text != baseline_text),
        dropped=False,
        drop_reason=None,
        pii_hits=pii_hits,
        secrets_hits=secrets_hits,
        frontmatter=frontmatter,
        title=title,
        tags=tags,
        language=language,
        language_confidence=language_confidence,
        keywords=keywords,
        urls_changed=int(urls_changed),
        paragraphs_dropped=int(paragraphs_dropped),
        references_removed_lines=int(references_removed_lines),
        input_chars=len(baseline_text),
        output_chars=len(text or ""),
        input_lines=len((baseline_text or "").splitlines()),
        output_lines=len((text or "").splitlines()),
        added_lines=added,
        removed_lines=removed,
        changed_lines=changed_lines,
        diff_unified=diff_unified,
        diff_truncated=bool(diff_truncated),
        issues=issues_out,
        suggested_pipeline_patch=suggested_patch,
    )


@router.post("/governance-analyze", response_model=GovernanceAnalyzeResponse)
async def governance_analyze(
    body: GovernanceAnalyzeRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Analyze a text for governance issues without performing cleaning/persistence.

    This is intended for "quality check" UI flows to recommend治理配置/预设。
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    raw_input = body.markdown or ""
    input_text = raw_input
    if body.input_format == "html":
        html = raw_input
        if str(body.remove_images or "none").strip().lower() in {"decorative", "all"}:
            html = strip_images(html, mode=str(body.remove_images).strip().lower()).text  # type: ignore[arg-type]
        extracted = extract_text_from_html(html, xpath=body.html_xpath)
        if body.html_xpath and extracted.xpath_error and extracted.xpath_error.startswith("xpath_failed:"):
            raise HTTPException(status_code=400, detail=f"Invalid XPath: {extracted.xpath_error}")
        input_text = extracted.text or ""

    analysis_opts = {
        "remove_control_chars": bool(body.remove_control_chars),
        "unwrap_lines": bool(body.unwrap_lines),
        "remove_common_lines": bool(body.remove_common_lines),
        "remove_boilerplate": bool(body.remove_boilerplate),
        "normalize_tables": bool(body.normalize_tables),
        "normalize_urls": bool(body.normalize_urls),
        "normalize_urls_strip_tracking": bool(body.normalize_urls_strip_tracking),
        "remove_images": str(body.remove_images or "none"),
        "drop_outline_only": bool(body.drop_outline_only),
        "drop_outline_min_content_chars": int(body.drop_outline_min_content_chars or 0),
        "drop_outline_max_heading_ratio": float(body.drop_outline_max_heading_ratio or 0.0),
        "drop_low_density": bool(body.drop_low_density),
        "drop_low_density_threshold": float(body.drop_low_density_threshold or 0.0),
    }

    issues, patch = analyze_governance(
        input_text or "",
        "",
        input_format=str(body.input_format or "markdown"),
        options=analysis_opts,
    )
    out_issues: list[GovernanceIssue] = []
    for it in issues:
        out_issues.append(
            GovernanceIssue(
                code=str(it.code),
                severity=it.severity,  # type: ignore[arg-type]
                message=str(it.message),
                count=int(getattr(it, "count", 0) or 0),
                samples=list(getattr(it, "samples", None) or []),
                suggested_pipeline_patch=dict(getattr(it, "suggested_pipeline_patch", None) or {}),
            )
        )

    base = input_text or ""
    return GovernanceAnalyzeResponse(
        input_chars=len(base),
        input_lines=len(base.splitlines()),
        issues=out_issues,
        suggested_pipeline_patch=dict(patch or {}),
    )


@router.get("/clean-rules", response_model=CleanRulesResponse)
async def list_clean_rules(
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Return default governance rules for UI selection/editing.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    return CleanRulesResponse(
        rules=[RegexRuleModel(pattern=r.pattern, repl=r.repl, flags=r.flags) for r in DEFAULT_MARKDOWN_RULES]
    )


@router.post("/extract-keywords", response_model=KeywordExtractResponse)
async def extract_keywords(
    body: KeywordExtractRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Extract keywords (for governance/annotation/classification).

    Supported providers:
    - provider=auto (prefer HanLP, fallback to jieba)
    - provider=jieba / jieba_tfidf (default)
    - provider=jieba_textrank
    - provider=hanlp (optional dependency; requires `hanlp` and `HANLP_TOKENIZER_MODEL`)
    - provider=simple (lightweight regex tokenization + term frequency)
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    from app.rag.preprocessing.keyword import (
        KeywordProviderUnavailable,
        UnsupportedKeywordProvider,
        extract_keywords as extract_keywords_fn,
    )

    provider = (body.provider or "jieba").lower()
    try:
        keywords = extract_keywords_fn(body.text or "", provider=provider, top_k=int(body.top_k))
        return KeywordExtractResponse(provider=provider, keywords=keywords)
    except KeywordProviderUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except UnsupportedKeywordProvider as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Keyword extraction failed: {str(exc)}") from exc


@router.post("/llm-clean-preview", response_model=LLMCleanPreviewResponse)
async def llm_clean_preview(
    body: LLMCleanPreviewRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Use an LLM to preview governance-style cleaning for Markdown (no persistence).

    Notes:
    - This endpoint calls an LLM (requires `LLM_API_KEY/LLM_API_BASE/LLM_MODEL`).
    - PromptTemplate can override the cleaning strategy via `prompt_template_id` / `template_key` / `ab_experiment_key`.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    markdown = body.markdown or ""
    if len(markdown) > int(body.max_chars):
        raise HTTPException(
            status_code=413,
            detail=f"Markdown too large for LLM preview (len={len(markdown)} > max_chars={body.max_chars}).",
        )

    system_prompt = (
        "You are a 'Markdown data governance cleaner'.\n"
        "Goal: Clean up noise and formatting issues from parsing/copying, but do not change semantics or fabricate content.\n"
        "Requirements:\n"
        "1) Preserve heading/list/table/code block structure; do not modify code block content.\n"
        "2) Remove obvious headers/footers/page numbers/TOC markers/repeated short lines/control characters/zero-width characters.\n"
        "3) Normalize whitespace: merge excess blank lines, remove trailing spaces, merge 'soft line breaks' when necessary.\n"
        "4) Do not translate or rewrite; only clean and normalize.\n"
        "Output: Return strict JSON with fields: markdown/changes/warnings.\n"
    )
    selected_prompt_template_id: str | None = None
    selected_prompt_template_key: str | None = None
    selected_prompt_ab_experiment_key: str | None = None
    selected_prompt_ab_variant: str | None = None

    if body.prompt_template_id or body.template_key or body.ab_experiment_key:
        chosen = resolve_prompt_template(
            db=db,
            tenant_id=tenant_id,
            prompt_template_id=body.prompt_template_id,
            template_key=body.template_key,
            ab_experiment_key=body.ab_experiment_key,
            ab_user_key=body.ab_user_key or account_id,
        )

        if not chosen:
            raise HTTPException(status_code=404, detail="PromptTemplate not found or inactive")

        system_prompt = str(chosen.content or "").strip() or system_prompt
        selected_prompt_template_id = str(chosen.id)
        selected_prompt_template_key = getattr(chosen, "template_key", None)
        selected_prompt_ab_experiment_key = getattr(chosen, "ab_experiment_key", None)
        selected_prompt_ab_variant = getattr(chosen, "ab_variant", None)
        chosen.usage_count += 1
        db.commit()

    model_config = {}
    if body.model:
        model_config["model"] = body.model
    if body.temperature is not None:
        model_config["temperature"] = body.temperature

    try:
        llm = await create_llm_client(scenario="governance_cleaning", model_config=model_config or None)
        resp = await llm.chat_with_schema(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=system_prompt),
                LLMMessage(
                    role=LLMRole.HUMAN,
                    content=f"Input Markdown:\n```markdown\n{markdown}\n```",
                ),
            ],
            response_schema={
                "markdown": "string",
                "changes": ["string"],
                "warnings": ["string"],
            },
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM request failed: {str(exc)[:200]}") from exc

    warnings: list[str] = []
    cleaned = ""
    if isinstance(resp, dict):
        val = resp.get("markdown")
        if isinstance(val, str):
            cleaned = val
        else:
            raw = resp.get("raw")
            if isinstance(raw, str) and raw.strip():
                cleaned = raw.strip()
                warnings.append("LLM did not return JSON schema; falling back to raw text.")

        warn_val = resp.get("warnings")
        if isinstance(warn_val, list):
            warnings.extend([str(w).strip() for w in warn_val if str(w).strip()])

    if not cleaned.strip():
        cleaned = markdown
        warnings.append("LLM returned empty; falling back to original text.")

    return LLMCleanPreviewResponse(
        markdown=cleaned,
        changed=(cleaned != markdown),
        model_used=body.model or settings.LLM_MODEL,
        prompt_template_id=selected_prompt_template_id,
        template_key=selected_prompt_template_key,
        ab_experiment_key=selected_prompt_ab_experiment_key,
        ab_variant=selected_prompt_ab_variant,
        warnings=warnings,
    )



@router.post("/upload-zip-with-images", response_model=ZipWithImagesResponse)
async def upload_zip_with_images(
    file: UploadFile = File(...),
    dataset_id: str = Form(...),
    document_id: str | None = Form(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Upload a ZIP that contains Markdown + images.

    Auto processing:
    1. Unzip the archive
    2. Upload all images to MinIO
    3. Replace Markdown image refs with MinIO URLs
    4. Return the rewritten Markdown and image list

    Args:
        file: ZIP file (Markdown + images)
        dataset_id: Dataset ID (used for MinIO paths)
        document_id: Optional document ID (defaults to file name)

    Returns:
        {
            "markdown": "rewritten Markdown",
            "images": [{"img_id": "...", "url": "...", "original_path": "..."}],
            "image_count": count
        }
    """
    if not settings.MINIO_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="MinIO is disabled; cannot process image uploads. Set MINIO_ENABLED=true"
        )

    # Validate file type.
    if not file.filename.endswith('.zip'):
        raise HTTPException(
            status_code=400,
            detail="Only ZIP format files are supported"
        )

    try:
        dataset_uuid = UUID(str(dataset_id))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid dataset_id")
    dataset = DatasetService.get_dataset(db, tenant_id, dataset_uuid)
    DatasetService.assert_dataset_writable(db, dataset, account_id)
    
    # Save to a temporary file.
    temp_dir = Path(settings.UPLOAD_DIR) / str(tenant_id) / "temp_zip"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    temp_zip_path = temp_dir / f"{uuid.uuid4()}.zip"
    
    try:
        # Write to a temporary file (streamed, size-limited).
        await save_upload_file(file, temp_zip_path, max_bytes=settings.MAX_FILE_SIZE)
        
        # Process ZIP: extract images and upload to MinIO.
        doc_id = document_id or file.filename.rsplit('.', 1)[0]
        result = zip_image_processor.process_zip_with_images(
            zip_path=temp_zip_path,
            tenant_id=str(tenant_id),
            dataset_id=dataset_id,
            document_id=doc_id
        )
        
        return {
            "markdown": result["markdown"],
            "images": result["images"],
            "image_count": result["image_count"],
            "dataset_id": dataset_id,
            "document_id": doc_id,
        }
        
    except HTTPException:
        raise
    except (ValueError, zipfile.BadZipFile) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid ZIP format/content: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ZIP processing failed: {str(e)}"
        )
    finally:
        # Clean up temporary files.
        try:
            if temp_zip_path.exists():
                temp_zip_path.unlink()
        except Exception:
            pass
