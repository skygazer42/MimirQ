"""
Manuscript preset chunking strategy.

This is a convenience preset for "mixed" textual documents (文稿/讲稿/手稿/报告),
where the best chunking method depends on the content shape:
- Email threads -> email_thread
- QA pairs / FAQ -> qa_pairs
- SOP / procedures -> sop_steps
- Glossary -> glossary
- Timestamped chat logs -> chat_history
- Meeting minutes / interviews -> transcript
- Legal/policy docs -> laws_structured
- Papers / reports -> paper
- Book-like docs -> book_structured
- Numbered outlines / manuals -> outline
- Resume/CV -> resume_structured
- Slides/deck -> presentation_slides
- CSV rows -> csv_rows
- Spreadsheets -> spreadsheet_sheet
- Markdown tables -> markdown_table
- Markdown -> markdown_aware
- Otherwise -> semantic_sentence or langchain_recursive
"""

from __future__ import annotations

import json
import re
from typing import List

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies.book_structured import BookStructuredChunker, looks_like_book
from app.rag.chunking.strategies.chat_history import ChatHistoryChunker, looks_like_chat_history
from app.rag.chunking.strategies.csv_rows import CsvRowsChunker, looks_like_csv_rows
from app.rag.chunking.strategies.email_thread import EmailThreadChunker, looks_like_email_thread
from app.rag.chunking.strategies.glossary import GlossaryChunker, looks_like_glossary
from app.rag.chunking.strategies.json_code import JSONChunker
from app.rag.chunking.strategies.laws_structured import LawsStructuredChunker, looks_like_laws
from app.rag.chunking.strategies.markdown import MarkdownAwareChunker
from app.rag.chunking.strategies.markdown_table import MarkdownTableChunker, looks_like_markdown_table
from app.rag.chunking.strategies.outline import OutlineChunker, looks_like_outline
from app.rag.chunking.strategies.paper import PaperChunker, looks_like_paper
from app.rag.chunking.strategies.presentation_slides import PresentationSlidesChunker, looks_like_presentation
from app.rag.chunking.strategies.qa_pairs import QAPairsChunker, looks_like_qa_pairs
from app.rag.chunking.strategies.recursive import LangChainRecursiveChunker
from app.rag.chunking.strategies.resume_structured import ResumeStructuredChunker, looks_like_resume
from app.rag.chunking.strategies.semantic import SemanticSentenceChunker
from app.rag.chunking.strategies.sop_steps import SOPStepsChunker, looks_like_sop
from app.rag.chunking.strategies.spreadsheet_sheet import SpreadsheetSheetChunker, looks_like_spreadsheet
from app.rag.chunking.strategies.transcript import TranscriptChunker, looks_like_transcript


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

    def _select(self, doc: Document) -> tuple[BaseChunker, str]:
        meta = doc.metadata or {}
        file_type = str(meta.get("file_type", "") or "").strip().lower()
        text = doc.page_content or ""

        if file_type in {"json"} or _looks_like_json(text):
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

        if looks_like_email_thread(text):
            return self._email_thread, "email_thread"

        if looks_like_chat_history(text):
            return self._chat, "chat_history"

        if looks_like_qa_pairs(text):
            return self._qa_pairs, "qa_pairs"

        if looks_like_sop(text):
            return self._sop, "sop_steps"

        if looks_like_glossary(text):
            return self._glossary, "glossary"

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

        if looks_like_outline(text):
            return self._outline, "outline"

        if looks_like_transcript(text):
            return self._transcript, "transcript"

        if looks_like_markdown_table(text):
            return self._markdown_table, "markdown_table"

        if file_type in {"md", "markdown"} or _looks_like_markdown(text):
            return self._markdown, "markdown_aware"

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
                meta["chunk_strategy_preset"] = "manuscript"
                meta.setdefault("chunk_strategy_selected", selected)
                item.metadata = meta
            chunks.extend(produced)
        return chunks
