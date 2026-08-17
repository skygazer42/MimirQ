"""
Auto chunking strategy.

Selects an appropriate chunker per-document based on metadata + lightweight
content heuristics.
"""

import json
import re

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies.ansible_playbook import AnsiblePlaybookChunker, looks_like_ansible_playbook
from app.rag.chunking.strategies.api_reference import APIReferenceChunker, looks_like_api_reference
from app.rag.chunking.strategies.asciidoc_sections import AsciiDocSectionsChunker, looks_like_asciidoc
from app.rag.chunking.strategies.book_structured import BookStructuredChunker, looks_like_book
from app.rag.chunking.strategies.changelog import ChangelogChunker, looks_like_changelog
from app.rag.chunking.strategies.chat_history import ChatHistoryChunker, looks_like_chat_history
from app.rag.chunking.strategies.csv_rows import CsvRowsChunker, looks_like_csv_rows
from app.rag.chunking.strategies.diff_patch import DiffPatchChunker, looks_like_diff_patch
from app.rag.chunking.strategies.docker_compose import DockerComposeChunker, looks_like_docker_compose
from app.rag.chunking.strategies.dockerfile import DockerfileChunker, looks_like_dockerfile
from app.rag.chunking.strategies.email_thread import EmailThreadChunker, looks_like_email_thread
from app.rag.chunking.strategies.git_commit_log import GitCommitLogChunker, looks_like_git_commit_log
from app.rag.chunking.strategies.github_actions import GitHubActionsChunker, looks_like_github_actions_workflow
from app.rag.chunking.strategies.gitlab_ci import GitLabCIChunker, looks_like_gitlab_ci
from app.rag.chunking.strategies.glossary import GlossaryChunker, looks_like_glossary
from app.rag.chunking.strategies.graphql_schema import GraphQLSchemaChunker, looks_like_graphql_schema
from app.rag.chunking.strategies.html_sections import HTMLSectionsChunker, looks_like_html_sections
from app.rag.chunking.strategies.http_trace import HTTPTraceChunker, looks_like_http_trace
from app.rag.chunking.strategies.jira_ticket import JiraTicketChunker, looks_like_jira_ticket
from app.rag.chunking.strategies.json_code import JSONChunker
from app.rag.chunking.strategies.jsonl_records import JsonlRecordsChunker, looks_like_jsonl_records
from app.rag.chunking.strategies.junit_xml import JUnitXMLChunker, looks_like_junit_xml
from app.rag.chunking.strategies.kv_config import KVConfigChunker, looks_like_kv_config
from app.rag.chunking.strategies.latex_sections import LatexSectionsChunker, looks_like_latex_sections
from app.rag.chunking.strategies.laws_structured import LawsStructuredChunker, looks_like_laws
from app.rag.chunking.strategies.log_events import LogEventsChunker, looks_like_log_events
from app.rag.chunking.strategies.makefile import MakefileChunker, looks_like_makefile
from app.rag.chunking.strategies.markdown import MarkdownAwareChunker
from app.rag.chunking.strategies.markdown_frontmatter import MarkdownFrontmatterChunker, looks_like_markdown_frontmatter
from app.rag.chunking.strategies.markdown_table import MarkdownTableChunker, looks_like_markdown_table
from app.rag.chunking.strategies.maven_pom import MavenPOMChunker, looks_like_maven_pom
from app.rag.chunking.strategies.mediawiki_sections import MediaWikiSectionsChunker, looks_like_mediawiki
from app.rag.chunking.strategies.meeting_minutes import MeetingMinutesChunker, looks_like_meeting_minutes
from app.rag.chunking.strategies.nginx_config import NginxConfigChunker, looks_like_nginx_config
from app.rag.chunking.strategies.openapi_spec import OpenAPISpecChunker, looks_like_openapi_spec
from app.rag.chunking.strategies.orgmode_sections import OrgModeSectionsChunker, looks_like_orgmode
from app.rag.chunking.strategies.outline import OutlineChunker, looks_like_outline
from app.rag.chunking.strategies.paper import PaperChunker, looks_like_paper
from app.rag.chunking.strategies.policy_manual_structured import (
    PolicyManualStructuredChunker,
    looks_like_policy_manual,
)
from app.rag.chunking.strategies.postmortem_report import PostmortemReportChunker, looks_like_postmortem_report
from app.rag.chunking.strategies.prd_spec import PRDSpecChunker, looks_like_prd_spec
from app.rag.chunking.strategies.presentation_slides import PresentationSlidesChunker, looks_like_presentation
from app.rag.chunking.strategies.proto_schema import ProtoSchemaChunker, looks_like_proto_schema
from app.rag.chunking.strategies.qa_markdown import QAMarkdownChunker, looks_like_qa_markdown
from app.rag.chunking.strategies.qa_pairs import QAPairsChunker, looks_like_qa_pairs
from app.rag.chunking.strategies.recursive import LangChainRecursiveChunker
from app.rag.chunking.strategies.resume_structured import ResumeStructuredChunker, looks_like_resume
from app.rag.chunking.strategies.rst_sections import RSTSectionsChunker, looks_like_rst_sections
from app.rag.chunking.strategies.semantic import SemanticSentenceChunker
from app.rag.chunking.strategies.sitemap_xml import SitemapXMLChunker, looks_like_sitemap_xml
from app.rag.chunking.strategies.sop_steps import SOPStepsChunker, looks_like_sop
from app.rag.chunking.strategies.spreadsheet_sheet import SpreadsheetSheetChunker, looks_like_spreadsheet
from app.rag.chunking.strategies.sql_schema import SqlSchemaChunker, looks_like_sql_schema
from app.rag.chunking.strategies.stacktrace import StackTraceChunker, looks_like_stacktrace
from app.rag.chunking.strategies.subtitles import SubtitlesChunker, looks_like_subtitles
from app.rag.chunking.strategies.terraform_hcl import TerraformHCLChunker, looks_like_terraform_hcl
from app.rag.chunking.strategies.terraform_plan import TerraformPlanChunker, looks_like_terraform_plan
from app.rag.chunking.strategies.timeline_events import TimelineEventsChunker, looks_like_timeline_events
from app.rag.chunking.strategies.toml_config import TOMLConfigChunker, looks_like_toml_config
from app.rag.chunking.strategies.transcript import TranscriptChunker, looks_like_transcript
from app.rag.chunking.strategies.xml_feed import XMLFeedChunker, looks_like_xml_feed
from app.rag.chunking.strategies.yaml_manifest import YAMLManifestChunker, looks_like_yaml_manifest


def _clamp_int(v: int, lo: int, hi: int) -> int:
    return max(int(lo), min(int(v), int(hi)))


def _density_metrics(text: str, *, sample_chars: int = 50_000) -> dict[str, float]:
    """
    Compute simple text density metrics (bounded) for adaptive chunk sizing.

    These metrics are intentionally lightweight and deterministic.
    """
    raw = str(text or "")
    sample = raw[: max(0, int(sample_chars or 0))] if sample_chars else raw
    n = len(sample)
    if n <= 0:
        return {"sample_chars": 0.0, "line_count": 0.0, "avg_line_len": 0.0, "non_ws_ratio": 0.0}

    line_count = float(sample.count("\n") + 1)
    avg_line_len = float(n) / max(1.0, line_count)
    ws = 0
    # Avoid importing regex-heavy helpers; a tight loop is fine for bounded samples.
    for ch in sample:
        if ch.isspace():
            ws += 1
    non_ws_ratio = float(n - ws) / float(n)
    return {
        "sample_chars": float(n),
        "line_count": float(line_count),
        "avg_line_len": float(avg_line_len),
        "non_ws_ratio": float(non_ws_ratio),
    }


def _adaptive_chunk_params(
    *,
    base_size: int,
    base_overlap: int,
    file_type: str,
    selected: str,
    text: str,
) -> tuple[int, int, str, dict[str, float]]:
    """
    Decide adaptive chunk_size/chunk_overlap based on doc type + density metrics.

    This is conservative: it only adjusts sizes within bounded ranges.
    """
    bs = max(1, int(base_size or 1))
    bo = max(0, int(base_overlap or 0))

    metrics = _density_metrics(text)
    avg_line_len = float(metrics.get("avg_line_len") or 0.0)
    line_count = float(metrics.get("line_count") or 0.0)

    # Start from defaults.
    size = bs
    reason = "base"

    # Doc-type nudges (coarse).
    ft = str(file_type or "").strip().lower()
    sel = str(selected or "").strip().lower()
    if ft in {"pdf"} and sel in {"langchain_recursive", "semantic_sentence", "markdown_aware"}:
        # PDFs often have hard line breaks; slightly larger chunks help preserve paragraph context.
        size = int(round(bs * 1.1))
        reason = "file_type_pdf"

    # Density-based adjustments (dominant).
    # Long lines + few breaks => dense blocks; reduce size.
    if avg_line_len >= 140:
        size = int(round(bs * 0.8))
        reason = "dense_long_lines"
    # Many short lines => sparse layout; increase size.
    elif avg_line_len <= 30 and line_count >= 80:
        size = int(round(bs * 1.3))
        reason = "sparse_short_lines"

    # Clamp to safe bounds; keep within the docs-recommended range.
    size = _clamp_int(size, 400, 1800)

    # Keep overlap ratio stable relative to base settings.
    ratio = float(bo) / float(bs) if bs > 0 else 0.2
    overlap = int(round(float(size) * ratio))
    overlap = _clamp_int(overlap, 0, max(0, size - 1))

    # Some strategies don't want overlap (e.g. JSON).
    if sel == "json":
        overlap = 0

    return int(size), int(overlap), str(reason), metrics


_MD_HINT_RES = (
    re.compile(r"(?m)^\s*#{1,6}\s+"),
    re.compile(r"\[[^\]]+\]\([^)]+\)"),
    re.compile(r"(?m)^\s*```"),
    re.compile(r"(?m)^\s*[-*+]\s+"),
)


def _looks_like_markdown(text: str) -> bool:
    if not text or len(text) < 20:
        return False
    return any(p.search(text) for p in _MD_HINT_RES)


def _looks_like_json(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
        return True
    except Exception:
        return False


class AutoChunker(BaseChunker):
    """
    Smart, lightweight chunker selection.

    Strategy selection (per Document):
    - CSV (row-oriented) -> csv_rows
    - Spreadsheet (sheet headings) -> spreadsheet_sheet
    - Git commit logs -> git_commit_log (splits by commit headers)
    - Diff/patch -> diff_patch (splits by file/hunk)
    - Subtitles -> subtitles (splits by cue timecodes)
    - Logs -> log_events (keeps log entries together)
    - Stacktraces -> stacktrace (groups traceback blocks)
    - HTTP traces -> http_trace (splits by HTTP request blocks)
    - Terraform plan output -> terraform_plan (splits by change headers)
    - JUnit XML reports -> junit_xml (splits by <testcase> blocks)
    - Sitemap XML -> sitemap_xml (splits by <url>/<sitemap> entries)
    - Maven POM -> maven_pom (splits by <dependency>/<plugin> records)
    - XML feeds (RSS/Atom) -> xml_feed (splits by item/entry blocks)
    - OpenAPI/Swagger specs -> openapi_spec (splits by paths)
    - GitHub Actions workflows -> github_actions (splits by jobs)
    - Docker Compose -> docker_compose (splits by services)
    - GitLab CI -> gitlab_ci (splits by top-level blocks)
    - Ansible playbooks -> ansible_playbook (splits by plays)
    - YAML manifests -> yaml_manifest (splits by --- docs)
    - TOML config -> toml_config (splits by [tables])
    - JSONL/NDJSON records -> jsonl_records (groups whole records)
    - GraphQL schemas -> graphql_schema (splits by type/input/enum)
    - Protocol Buffers schemas -> proto_schema (splits by message/enum/service)
    - Terraform/HCL -> terraform_hcl (splits by blocks)
    - Nginx config -> nginx_config (splits by server blocks)
    - Dockerfile -> dockerfile (splits by stages/instructions)
    - Makefile -> makefile (splits by target blocks)
    - SQL schema -> sql_schema (splits by DDL statements)
    - Key-value config -> kv_config
    - API reference -> api_reference (splits by endpoints)
    - Changelog -> changelog (splits by releases)
    - Email thread -> email_thread (keeps messages together)
    - Timestamped chat history -> chat_history (keeps messages together)
    - Q/A pairs -> qa_pairs (keeps pairs together)
    - Markdown Q/A -> qa_markdown (bullets/headings)
    - SOP/procedure -> sop_steps (keeps steps together)
    - Glossary -> glossary (keeps entries together)
    - Postmortem/RCA reports -> postmortem_report (splits by RCA sections)
    - Resume/CV -> resume_structured (splits by common sections)
    - Slides/deck -> presentation_slides (splits by slide separators)
    - Meeting minutes -> meeting_minutes (splits by agenda/actions/decisions)
    - Legal doc -> laws_structured (clause-aware)
    - Book-like -> book_structured (chapter-aware)
    - Paper-like -> paper (section-aware)
    - Outline-like -> outline (numbered headings)
    - Transcript-like -> transcript (keeps speaker turns together)
    - Timeline events -> timeline_events (keeps events together)
    - Jira tickets -> jira_ticket (splits by common ticket fields)
    - PRD/spec -> prd_spec (splits by common PRD sections)
    - HTML headings -> html_sections (splits by <h1>-<h6>)
    - reStructuredText -> rst_sections (splits by underlined headings)
    - AsciiDoc -> asciidoc_sections (splits by = headings)
    - LaTeX -> latex_sections (splits by \\section commands)
    - Org-mode -> orgmode_sections (splits by * headings)
    - MediaWiki -> mediawiki_sections (splits by == headings)
    - Markdown tables -> markdown_table (avoids splitting rows)
    - Markdown frontmatter -> markdown_frontmatter (keeps YAML frontmatter together)
    - Markdown-ish content -> markdown_aware (structure-friendly)
    - Valid JSON content -> json (structure-friendly, overlap=0)
    - Long plain text -> semantic_sentence (better boundary alignment)
    - Default -> langchain_recursive (general purpose)
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_recursive = LangChainRecursiveChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._markdown = MarkdownAwareChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._semantic = SemanticSentenceChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._outline = OutlineChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._transcript = TranscriptChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._qa_pairs = QAPairsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._paper = PaperChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._email_thread = EmailThreadChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._laws = LawsStructuredChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._policy_manual = PolicyManualStructuredChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._book = BookStructuredChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._sop = SOPStepsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._glossary = GlossaryChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._resume = ResumeStructuredChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._slides = PresentationSlidesChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._csv_rows = CsvRowsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._spreadsheet = SpreadsheetSheetChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._markdown_table = MarkdownTableChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._chat = ChatHistoryChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._diff = DiffPatchChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._subtitles = SubtitlesChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._log_events = LogEventsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._kv_config = KVConfigChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._api = APIReferenceChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._changelog = ChangelogChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._qa_md = QAMarkdownChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._minutes = MeetingMinutesChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._timeline = TimelineEventsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._stacktrace = StackTraceChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._yaml = YAMLManifestChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._toml = TOMLConfigChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._sql = SqlSchemaChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._dockerfile = DockerfileChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._makefile = MakefileChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._nginx = NginxConfigChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._jira = JiraTicketChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._prd = PRDSpecChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._html = HTMLSectionsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._rst = RSTSectionsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._asciidoc = AsciiDocSectionsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._latex = LatexSectionsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._orgmode = OrgModeSectionsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._mediawiki = MediaWikiSectionsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._git_commit_log = GitCommitLogChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._jsonl = JsonlRecordsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._xml_feed = XMLFeedChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._openapi = OpenAPISpecChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._graphql = GraphQLSchemaChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._proto = ProtoSchemaChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._terraform = TerraformHCLChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._postmortem = PostmortemReportChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._docker_compose = DockerComposeChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._github_actions = GitHubActionsChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._gitlab_ci = GitLabCIChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._ansible = AnsiblePlaybookChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._markdown_frontmatter = MarkdownFrontmatterChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._http_trace = HTTPTraceChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._junit_xml = JUnitXMLChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._sitemap_xml = SitemapXMLChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._maven_pom = MavenPOMChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        self._terraform_plan = TerraformPlanChunker(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def _select(self, doc: Document) -> tuple[BaseChunker, str]:
        meta = doc.metadata or {}
        file_type = str(meta.get("file_type", "") or "").strip().lower()
        text = doc.page_content or ""

        def _json_case() -> bool:
            return file_type in {"json"} or _looks_like_json(text)

        def _build_json_chunker() -> BaseChunker:
            # JSON overlap is usually counterproductive; keep it at 0.
            return JSONChunker(chunk_size=self.chunk_size, chunk_overlap=0)

        cases = [
            (_json_case, _build_json_chunker, "json"),
            (
                lambda: file_type in {"jsonl", "ndjson"} or looks_like_jsonl_records(text),
                lambda: self._jsonl,
                "jsonl_records",
            ),
            (lambda: looks_like_maven_pom(text), lambda: self._maven_pom, "maven_pom"),
            (lambda: looks_like_junit_xml(text), lambda: self._junit_xml, "junit_xml"),
            (lambda: looks_like_sitemap_xml(text), lambda: self._sitemap_xml, "sitemap_xml"),
            (lambda: file_type in {"rss", "atom"} or looks_like_xml_feed(text), lambda: self._xml_feed, "xml_feed"),
            (
                lambda: file_type in {"graphql", "gql"} or looks_like_graphql_schema(text),
                lambda: self._graphql,
                "graphql_schema",
            ),
            (lambda: file_type in {"proto"} or looks_like_proto_schema(text), lambda: self._proto, "proto_schema"),
            (
                lambda: file_type in {"tf", "hcl"} or looks_like_terraform_hcl(text),
                lambda: self._terraform,
                "terraform_hcl",
            ),
            (lambda: file_type == "csv" and looks_like_csv_rows(text), lambda: self._csv_rows, "csv_rows"),
            (
                lambda: file_type == "csv" and looks_like_markdown_table(text),
                lambda: self._markdown_table,
                "markdown_table",
            ),
            (
                lambda: file_type in {"xlsx", "xls"} and looks_like_spreadsheet(text),
                lambda: self._spreadsheet,
                "spreadsheet_sheet",
            ),
            (
                lambda: file_type in {"xlsx", "xls"} and looks_like_markdown_table(text),
                lambda: self._markdown_table,
                "markdown_table",
            ),
            (lambda: looks_like_git_commit_log(text), lambda: self._git_commit_log, "git_commit_log"),
            (lambda: looks_like_diff_patch(text), lambda: self._diff, "diff_patch"),
            (lambda: looks_like_subtitles(text), lambda: self._subtitles, "subtitles"),
            (lambda: looks_like_log_events(text), lambda: self._log_events, "log_events"),
            (lambda: looks_like_stacktrace(text), lambda: self._stacktrace, "stacktrace"),
            (lambda: looks_like_http_trace(text), lambda: self._http_trace, "http_trace"),
            (lambda: looks_like_terraform_plan(text), lambda: self._terraform_plan, "terraform_plan"),
            (lambda: looks_like_openapi_spec(text), lambda: self._openapi, "openapi_spec"),
            (
                lambda: file_type in {"yaml", "yml"} and looks_like_github_actions_workflow(text),
                lambda: self._github_actions,
                "github_actions",
            ),
            (
                lambda: file_type in {"yaml", "yml"} and looks_like_docker_compose(text),
                lambda: self._docker_compose,
                "docker_compose",
            ),
            (lambda: file_type in {"yaml", "yml"} and looks_like_gitlab_ci(text), lambda: self._gitlab_ci, "gitlab_ci"),
            (
                lambda: file_type in {"yaml", "yml"} and looks_like_ansible_playbook(text),
                lambda: self._ansible,
                "ansible_playbook",
            ),
            (
                lambda: file_type in {"yaml", "yml"} or looks_like_yaml_manifest(text),
                lambda: self._yaml,
                "yaml_manifest",
            ),
            (lambda: file_type in {"toml"} or looks_like_toml_config(text), lambda: self._toml, "toml_config"),
            (lambda: file_type in {"sql"} or looks_like_sql_schema(text), lambda: self._sql, "sql_schema"),
            (lambda: looks_like_nginx_config(text), lambda: self._nginx, "nginx_config"),
            (lambda: looks_like_dockerfile(text), lambda: self._dockerfile, "dockerfile"),
            (lambda: file_type in {"mk"} or looks_like_makefile(text), lambda: self._makefile, "makefile"),
            (lambda: looks_like_kv_config(text), lambda: self._kv_config, "kv_config"),
            (lambda: looks_like_api_reference(text), lambda: self._api, "api_reference"),
            (lambda: looks_like_changelog(text), lambda: self._changelog, "changelog"),
            (lambda: looks_like_email_thread(text), lambda: self._email_thread, "email_thread"),
            (lambda: looks_like_chat_history(text), lambda: self._chat, "chat_history"),
            (lambda: looks_like_jira_ticket(text), lambda: self._jira, "jira_ticket"),
            (lambda: looks_like_postmortem_report(text), lambda: self._postmortem, "postmortem_report"),
            (lambda: looks_like_qa_pairs(text), lambda: self._qa_pairs, "qa_pairs"),
            (lambda: looks_like_qa_markdown(text), lambda: self._qa_md, "qa_markdown"),
            (lambda: looks_like_sop(text), lambda: self._sop, "sop_steps"),
            (lambda: looks_like_glossary(text), lambda: self._glossary, "glossary"),
            (lambda: looks_like_meeting_minutes(text), lambda: self._minutes, "meeting_minutes"),
            (lambda: looks_like_timeline_events(text), lambda: self._timeline, "timeline_events"),
            (lambda: looks_like_prd_spec(text), lambda: self._prd, "prd_spec"),
            (lambda: looks_like_resume(text), lambda: self._resume, "resume_structured"),
            (lambda: looks_like_presentation(text), lambda: self._slides, "presentation_slides"),
            (lambda: looks_like_policy_manual(text), lambda: self._policy_manual, "policy_manual_structured"),
            (lambda: looks_like_laws(text), lambda: self._laws, "laws_structured"),
            (lambda: looks_like_paper(text), lambda: self._paper, "paper"),
            (lambda: looks_like_book(text), lambda: self._book, "book_structured"),
            (lambda: file_type in {"rst"} or looks_like_rst_sections(text), lambda: self._rst, "rst_sections"),
            (
                lambda: file_type in {"adoc", "asciidoc"} or looks_like_asciidoc(text),
                lambda: self._asciidoc,
                "asciidoc_sections",
            ),
            (
                lambda: file_type in {"tex", "latex"} or looks_like_latex_sections(text),
                lambda: self._latex,
                "latex_sections",
            ),
            (lambda: file_type in {"org"} or looks_like_orgmode(text), lambda: self._orgmode, "orgmode_sections"),
            (lambda: looks_like_mediawiki(text), lambda: self._mediawiki, "mediawiki_sections"),
            (lambda: looks_like_html_sections(text), lambda: self._html, "html_sections"),
            (lambda: looks_like_markdown_table(text), lambda: self._markdown_table, "markdown_table"),
            (lambda: looks_like_outline(text), lambda: self._outline, "outline"),
            (
                lambda: file_type in {"md", "markdown"} and looks_like_markdown_frontmatter(text),
                lambda: self._markdown_frontmatter,
                "markdown_frontmatter",
            ),
            (
                lambda: file_type in {"md", "markdown"} or _looks_like_markdown(text),
                lambda: self._markdown,
                "markdown_aware",
            ),
            (lambda: looks_like_transcript(text), lambda: self._transcript, "transcript"),
        ]

        for predicate, builder, selected in cases:
            if predicate():
                return builder(), selected

        # If the document is long enough, sentence-aware splitting tends to
        # reduce broken sentences and improves retrieval.
        if len(text) >= max(self.chunk_size * 2, 1200):
            return self._semantic, "semantic_sentence"

        return self._fallback_recursive, "langchain_recursive"

    def split_documents(self, documents: list[Document]) -> list[Document]:
        chunks: list[Document] = []
        for doc in documents:
            chunker, selected = self._select(doc)
            meta_in = doc.metadata or {}
            file_type = str(meta_in.get("file_type", "") or "").strip().lower()
            text = doc.page_content or ""

            eff_size, eff_overlap, reason, metrics = _adaptive_chunk_params(
                base_size=self.chunk_size,
                base_overlap=self.chunk_overlap,
                file_type=file_type,
                selected=selected,
                text=text,
            )

            # Only re-instantiate for strategies where chunk_size/overlap are meaningful knobs.
            #
            # Many structured chunkers (csv_rows, diff_patch, etc) already define strong boundaries and
            # use chunk_size only as a guardrail, so changing it per-doc tends not to improve quality.
            chunker_used: BaseChunker = chunker
            if selected == "langchain_recursive":
                chunker_used = LangChainRecursiveChunker(chunk_size=eff_size, chunk_overlap=eff_overlap)
            elif selected == "semantic_sentence":
                chunker_used = SemanticSentenceChunker(chunk_size=eff_size, chunk_overlap=eff_overlap)
            elif selected == "markdown_aware":
                chunker_used = MarkdownAwareChunker(chunk_size=eff_size, chunk_overlap=eff_overlap)
            elif selected == "outline":
                chunker_used = OutlineChunker(chunk_size=eff_size, chunk_overlap=eff_overlap)
            elif selected == "transcript":
                chunker_used = TranscriptChunker(chunk_size=eff_size, chunk_overlap=eff_overlap)

            produced = chunker_used.split_documents([doc])
            for item in produced:
                meta = dict(item.metadata or {})
                meta["chunk_strategy_auto"] = True
                meta.setdefault("chunk_strategy_selected", selected)
                meta["chunk_size_base"] = int(self.chunk_size)
                meta["chunk_overlap_base"] = int(self.chunk_overlap)
                meta["chunk_size_effective"] = int(eff_size)
                meta["chunk_overlap_effective"] = int(eff_overlap)
                meta["adaptive_chunk_reason"] = str(reason)
                meta["adaptive_density"] = metrics
                item.metadata = meta
            chunks.extend(produced)
        return chunks
