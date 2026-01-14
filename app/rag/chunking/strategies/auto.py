"""
Auto chunking strategy.

Selects an appropriate chunker per-document based on metadata + lightweight
content heuristics.
"""


import json
import re
from typing import List

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies.api_reference import APIReferenceChunker, looks_like_api_reference
from app.rag.chunking.strategies.book_structured import BookStructuredChunker, looks_like_book
from app.rag.chunking.strategies.chat_history import ChatHistoryChunker, looks_like_chat_history
from app.rag.chunking.strategies.changelog import ChangelogChunker, looks_like_changelog
from app.rag.chunking.strategies.csv_rows import CsvRowsChunker, looks_like_csv_rows
from app.rag.chunking.strategies.diff_patch import DiffPatchChunker, looks_like_diff_patch
from app.rag.chunking.strategies.email_thread import EmailThreadChunker, looks_like_email_thread
from app.rag.chunking.strategies.glossary import GlossaryChunker, looks_like_glossary
from app.rag.chunking.strategies.json_code import JSONChunker
from app.rag.chunking.strategies.kv_config import KVConfigChunker, looks_like_kv_config
from app.rag.chunking.strategies.laws_structured import LawsStructuredChunker, looks_like_laws
from app.rag.chunking.strategies.log_events import LogEventsChunker, looks_like_log_events
from app.rag.chunking.strategies.markdown import MarkdownAwareChunker
from app.rag.chunking.strategies.markdown_table import MarkdownTableChunker, looks_like_markdown_table
from app.rag.chunking.strategies.meeting_minutes import MeetingMinutesChunker, looks_like_meeting_minutes
from app.rag.chunking.strategies.outline import OutlineChunker, looks_like_outline
from app.rag.chunking.strategies.paper import PaperChunker, looks_like_paper
from app.rag.chunking.strategies.presentation_slides import PresentationSlidesChunker, looks_like_presentation
from app.rag.chunking.strategies.qa_pairs import QAPairsChunker, looks_like_qa_pairs
from app.rag.chunking.strategies.qa_markdown import QAMarkdownChunker, looks_like_qa_markdown
from app.rag.chunking.strategies.recursive import LangChainRecursiveChunker
from app.rag.chunking.strategies.resume_structured import ResumeStructuredChunker, looks_like_resume
from app.rag.chunking.strategies.semantic import SemanticSentenceChunker
from app.rag.chunking.strategies.sop_steps import SOPStepsChunker, looks_like_sop
from app.rag.chunking.strategies.spreadsheet_sheet import SpreadsheetSheetChunker, looks_like_spreadsheet
from app.rag.chunking.strategies.subtitles import SubtitlesChunker, looks_like_subtitles
from app.rag.chunking.strategies.timeline_events import TimelineEventsChunker, looks_like_timeline_events
from app.rag.chunking.strategies.transcript import TranscriptChunker, looks_like_transcript
from app.rag.chunking.strategies.html_sections import HTMLSectionsChunker, looks_like_html_sections
from app.rag.chunking.strategies.rst_sections import RSTSectionsChunker, looks_like_rst_sections
from app.rag.chunking.strategies.asciidoc_sections import AsciiDocSectionsChunker, looks_like_asciidoc
from app.rag.chunking.strategies.latex_sections import LatexSectionsChunker, looks_like_latex_sections
from app.rag.chunking.strategies.orgmode_sections import OrgModeSectionsChunker, looks_like_orgmode
from app.rag.chunking.strategies.mediawiki_sections import MediaWikiSectionsChunker, looks_like_mediawiki
from app.rag.chunking.strategies.yaml_manifest import YAMLManifestChunker, looks_like_yaml_manifest
from app.rag.chunking.strategies.toml_config import TOMLConfigChunker, looks_like_toml_config
from app.rag.chunking.strategies.sql_schema import SqlSchemaChunker, looks_like_sql_schema
from app.rag.chunking.strategies.stacktrace import StackTraceChunker, looks_like_stacktrace
from app.rag.chunking.strategies.dockerfile import DockerfileChunker, looks_like_dockerfile
from app.rag.chunking.strategies.makefile import MakefileChunker, looks_like_makefile
from app.rag.chunking.strategies.nginx_config import NginxConfigChunker, looks_like_nginx_config
from app.rag.chunking.strategies.jira_ticket import JiraTicketChunker, looks_like_jira_ticket
from app.rag.chunking.strategies.prd_spec import PRDSpecChunker, looks_like_prd_spec


_MD_HINT_RE = re.compile(
    r"(^\s*#{1,6}\s+)|(\[[^\]]+\]\([^)]+\))|(^\s*```)|(^\s*[-*+]\s+)",
    flags=re.MULTILINE,
)


def _looks_like_markdown(text: str) -> bool:
    if not text or len(text) < 20:
        return False
    return bool(_MD_HINT_RE.search(text))


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
    - Diff/patch -> diff_patch (splits by file/hunk)
    - Subtitles -> subtitles (splits by cue timecodes)
    - Logs -> log_events (keeps log entries together)
    - Stacktraces -> stacktrace (groups traceback blocks)
    - YAML manifests -> yaml_manifest (splits by --- docs)
    - TOML config -> toml_config (splits by [tables])
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

    def _select(self, doc: Document) -> tuple[BaseChunker, str]:
        meta = doc.metadata or {}
        file_type = str(meta.get("file_type", "") or "").strip().lower()
        text = doc.page_content or ""

        if file_type in {"json"} or _looks_like_json(text):
            # JSON overlap is usually counterproductive; keep it at 0.
            return JSONChunker(chunk_size=self.chunk_size, chunk_overlap=0), "json"

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

        if looks_like_diff_patch(text):
            return self._diff, "diff_patch"

        if looks_like_subtitles(text):
            return self._subtitles, "subtitles"

        if looks_like_log_events(text):
            return self._log_events, "log_events"

        if looks_like_kv_config(text):
            return self._kv_config, "kv_config"

        if looks_like_api_reference(text):
            return self._api, "api_reference"

        if looks_like_changelog(text):
            return self._changelog, "changelog"

        if looks_like_email_thread(text):
            return self._email_thread, "email_thread"

        if looks_like_chat_history(text):
            return self._chat, "chat_history"

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

        if looks_like_markdown_table(text):
            return self._markdown_table, "markdown_table"

        if looks_like_outline(text):
            return self._outline, "outline"

        if file_type in {"md", "markdown"} or _looks_like_markdown(text):
            return self._markdown, "markdown_aware"

        if looks_like_transcript(text):
            return self._transcript, "transcript"

        # If the document is long enough, sentence-aware splitting tends to
        # reduce broken sentences and improves retrieval.
        if len(text) >= max(self.chunk_size * 2, 1200):
            return self._semantic, "semantic_sentence"

        return self._fallback_recursive, "langchain_recursive"

    def split_documents(self, documents: List[Document]) -> List[Document]:
        chunks: List[Document] = []
        for doc in documents:
            chunker, selected = self._select(doc)
            produced = chunker.split_documents([doc])
            for item in produced:
                meta = dict(item.metadata or {})
                meta["chunk_strategy_auto"] = True
                meta.setdefault("chunk_strategy_selected", selected)
                item.metadata = meta
            chunks.extend(produced)
        return chunks

