"""
Manuscript preset chunking strategy.

This is a convenience preset for "mixed" textual documents (文稿/讲稿/手稿/报告),
where the best chunking method depends on the content shape:
- Git commit logs -> git_commit_log
- Diff/patch -> diff_patch
- Subtitles -> subtitles
- Logs -> log_events
- Stacktraces -> stacktrace
- HTTP traces -> http_trace
- Terraform plan output -> terraform_plan
- JUnit XML reports -> junit_xml
- Sitemap XML -> sitemap_xml
- Maven POM -> maven_pom
- XML feeds (RSS/Atom) -> xml_feed
- OpenAPI/Swagger specs -> openapi_spec
- GitHub Actions workflows -> github_actions
- Docker Compose -> docker_compose
- GitLab CI -> gitlab_ci
- Ansible playbooks -> ansible_playbook
- YAML manifests -> yaml_manifest
- TOML config -> toml_config
- JSONL/NDJSON -> jsonl_records
- GraphQL schema -> graphql_schema
- Protocol Buffers -> proto_schema
- Terraform/HCL -> terraform_hcl
- Nginx config -> nginx_config
- Dockerfile -> dockerfile
- Makefile -> makefile
- SQL schema -> sql_schema
- Key-value config -> kv_config
- API reference -> api_reference
- Changelog -> changelog
- Email threads -> email_thread
- QA pairs / FAQ -> qa_pairs
- Markdown Q/A -> qa_markdown
- SOP / procedures -> sop_steps
- Glossary -> glossary
- Timestamped chat logs -> chat_history
- Meeting minutes -> meeting_minutes
- Timeline events -> timeline_events
- Jira tickets -> jira_ticket
- PRD/spec -> prd_spec
- Incident postmortem/RCA -> postmortem_report
- HTML headings -> html_sections
- reStructuredText -> rst_sections
- AsciiDoc -> asciidoc_sections
- LaTeX -> latex_sections
- Org-mode -> orgmode_sections
- MediaWiki -> mediawiki_sections
- Interviews / dialogue -> transcript
- Legal/policy docs -> laws_structured
- Papers / reports -> paper
- Book-like docs -> book_structured
- Numbered outlines / manuals -> outline
- Resume/CV -> resume_structured
- Slides/deck -> presentation_slides
- CSV rows -> csv_rows
- Spreadsheets -> spreadsheet_sheet
- Markdown tables -> markdown_table
- Markdown frontmatter -> markdown_frontmatter
- Markdown -> markdown_aware
- Otherwise -> semantic_sentence or langchain_recursive
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


Selection = tuple[BaseChunker, str]


class ManuscriptChunker(BaseChunker):
    """
    Content-aware preset for manuscript-like documents.
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

    def _select_structured_payloads(self, *, file_type: str, text: str) -> Selection | None:
        if file_type in {"json"} or _looks_like_json(text):
            return JSONChunker(chunk_size=self.chunk_size, chunk_overlap=0), "json"

        if file_type in {"jsonl", "ndjson"} or looks_like_jsonl_records(text):
            return self._jsonl, "jsonl_records"

        if looks_like_maven_pom(text):
            return self._maven_pom, "maven_pom"

        if looks_like_junit_xml(text):
            return self._junit_xml, "junit_xml"

        if looks_like_sitemap_xml(text):
            return self._sitemap_xml, "sitemap_xml"

        if file_type in {"rss", "atom"} or looks_like_xml_feed(text):
            return self._xml_feed, "xml_feed"

        if file_type in {"graphql", "gql"} or looks_like_graphql_schema(text):
            return self._graphql, "graphql_schema"

        if file_type in {"proto"} or looks_like_proto_schema(text):
            return self._proto, "proto_schema"

        if file_type in {"tf", "hcl"} or looks_like_terraform_hcl(text):
            return self._terraform, "terraform_hcl"

        return None

    def _select_tabular_payloads(self, *, file_type: str, text: str) -> Selection | None:
        if file_type == "csv":
            if looks_like_csv_rows(text):
                return self._csv_rows, "csv_rows"
            if looks_like_markdown_table(text):
                return self._markdown_table, "markdown_table"

        if file_type in {"xlsx", "xls"}:
            if looks_like_spreadsheet(text):
                return self._spreadsheet, "spreadsheet_sheet"
            if looks_like_markdown_table(text):
                return self._markdown_table, "markdown_table"

        return None

    def _select_trace_and_spec_documents(self, *, file_type: str, text: str) -> Selection | None:
        _ = file_type
        if looks_like_git_commit_log(text):
            return self._git_commit_log, "git_commit_log"

        if looks_like_diff_patch(text):
            return self._diff, "diff_patch"

        if looks_like_subtitles(text):
            return self._subtitles, "subtitles"

        if looks_like_log_events(text):
            return self._log_events, "log_events"

        if looks_like_stacktrace(text):
            return self._stacktrace, "stacktrace"

        if looks_like_http_trace(text):
            return self._http_trace, "http_trace"

        if looks_like_terraform_plan(text):
            return self._terraform_plan, "terraform_plan"

        if looks_like_openapi_spec(text):
            return self._openapi, "openapi_spec"

        return None

    def _select_yaml_documents(self, *, file_type: str, text: str) -> Selection | None:
        if file_type in {"yaml", "yml"} and looks_like_github_actions_workflow(text):
            return self._github_actions, "github_actions"

        if file_type in {"yaml", "yml"} and looks_like_docker_compose(text):
            return self._docker_compose, "docker_compose"

        if file_type in {"yaml", "yml"} and looks_like_gitlab_ci(text):
            return self._gitlab_ci, "gitlab_ci"

        if file_type in {"yaml", "yml"} and looks_like_ansible_playbook(text):
            return self._ansible, "ansible_playbook"

        if file_type in {"yaml", "yml"} or looks_like_yaml_manifest(text):
            return self._yaml, "yaml_manifest"

        return None

    def _select_config_documents(self, *, file_type: str, text: str) -> Selection | None:
        if file_type in {"toml"} or looks_like_toml_config(text):
            return self._toml, "toml_config"

        if file_type in {"sql"} or looks_like_sql_schema(text):
            return self._sql, "sql_schema"

        if looks_like_nginx_config(text):
            return self._nginx, "nginx_config"

        if looks_like_dockerfile(text):
            return self._dockerfile, "dockerfile"

        if file_type in {"mk"} or looks_like_makefile(text):
            return self._makefile, "makefile"

        if looks_like_kv_config(text):
            return self._kv_config, "kv_config"

        return None

    def _select_reference_and_ticket_documents(self, *, file_type: str, text: str) -> Selection | None:
        _ = file_type
        if looks_like_api_reference(text):
            return self._api, "api_reference"

        if looks_like_changelog(text):
            return self._changelog, "changelog"

        if looks_like_email_thread(text):
            return self._email_thread, "email_thread"

        if looks_like_chat_history(text):
            return self._chat, "chat_history"

        if looks_like_jira_ticket(text):
            return self._jira, "jira_ticket"

        return None

    def _select_process_documents(self, *, file_type: str, text: str) -> Selection | None:
        _ = file_type
        if looks_like_postmortem_report(text):
            return self._postmortem, "postmortem_report"

        if looks_like_qa_pairs(text):
            return self._qa_pairs, "qa_pairs"

        if looks_like_qa_markdown(text):
            return self._qa_md, "qa_markdown"

        if looks_like_sop(text):
            return self._sop, "sop_steps"

        if looks_like_glossary(text):
            return self._glossary, "glossary"

        if looks_like_meeting_minutes(text):
            return self._minutes, "meeting_minutes"

        if looks_like_timeline_events(text):
            return self._timeline, "timeline_events"

        if looks_like_prd_spec(text):
            return self._prd, "prd_spec"

        return None

    def _select_longform_documents(self, *, file_type: str, text: str) -> Selection | None:
        _ = file_type
        if looks_like_resume(text):
            return self._resume, "resume_structured"

        if looks_like_presentation(text):
            return self._slides, "presentation_slides"

        if looks_like_laws(text):
            return self._laws, "laws_structured"

        if looks_like_paper(text):
            return self._paper, "paper"

        if looks_like_book(text):
            return self._book, "book_structured"

        return None

    def _select_sectioned_documents(self, *, file_type: str, text: str) -> Selection | None:
        if file_type in {"rst"} or looks_like_rst_sections(text):
            return self._rst, "rst_sections"

        if file_type in {"adoc", "asciidoc"} or looks_like_asciidoc(text):
            return self._asciidoc, "asciidoc_sections"

        if file_type in {"tex", "latex"} or looks_like_latex_sections(text):
            return self._latex, "latex_sections"

        if file_type in {"org"} or looks_like_orgmode(text):
            return self._orgmode, "orgmode_sections"

        if looks_like_mediawiki(text):
            return self._mediawiki, "mediawiki_sections"

        if looks_like_html_sections(text):
            return self._html, "html_sections"

        if looks_like_outline(text):
            return self._outline, "outline"

        if looks_like_transcript(text):
            return self._transcript, "transcript"

        return None

    def _select_markdown_or_fallback(self, *, file_type: str, text: str) -> Selection:
        if looks_like_markdown_table(text):
            return self._markdown_table, "markdown_table"

        if file_type in {"md", "markdown"} and looks_like_markdown_frontmatter(text):
            return self._markdown_frontmatter, "markdown_frontmatter"

        if file_type in {"md", "markdown"} or _looks_like_markdown(text):
            return self._markdown, "markdown_aware"

        if len(text) >= max(self.chunk_size * 2, 1200):
            return self._semantic, "semantic_sentence"

        return self._fallback_recursive, "langchain_recursive"

    def _select(self, doc: Document) -> tuple[BaseChunker, str]:
        meta = doc.metadata or {}
        file_type = str(meta.get("file_type", "") or "").strip().lower()
        text = doc.page_content or ""

        for selector in (
            self._select_structured_payloads,
            self._select_tabular_payloads,
            self._select_trace_and_spec_documents,
            self._select_yaml_documents,
            self._select_config_documents,
            self._select_reference_and_ticket_documents,
            self._select_process_documents,
            self._select_longform_documents,
            self._select_sectioned_documents,
        ):
            selected = selector(file_type=file_type, text=text)
            if selected is not None:
                return selected

        return self._select_markdown_or_fallback(file_type=file_type, text=text)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        chunks: list[Document] = []
        for doc in documents:
            chunker, selected = self._select(doc)
            produced = chunker.split_documents([doc])
            for item in produced:
                meta = dict(item.metadata or {})
                meta["chunk_strategy_preset"] = "manuscript"
                meta.setdefault("chunk_strategy_selected", selected)
                item.metadata = meta
            chunks.extend(produced)
        return chunks
