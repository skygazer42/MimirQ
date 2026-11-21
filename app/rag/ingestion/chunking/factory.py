"""
Chunker factory for selecting and creating chunking strategies.

Usage:
    from app.rag.ingestion.chunking.factory import chunker_factory

    chunker = chunker_factory.get_chunker("langchain_recursive", chunk_size=1000, chunk_overlap=200)
    chunks = chunker.split_documents(documents)
"""

import inspect
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.capabilities import (
    CHUNKER_STRATEGY_ALIASES,
    OPTIONAL_DEPENDENCY_STRATEGIES,
    reject_retired_chunk_strategy,
)
from app.rag.ingestion.chunking.registry import CHUNKER_STRATEGY_REGISTRY
from app.rag.ingestion.governance.tagging.metadata_enrichment import (
    build_document_metadata_enrichment,
    build_rich_metadata_header,
    enrich_documents_metadata,
)


class _MetadataAwareChunker(BaseChunker):
    def __init__(
        self,
        inner: BaseChunker,
        *,
        enrich_document_metadata: bool,
        inject_metadata_header: bool,
        metadata_keywords_provider: str,
        metadata_keyword_top_k: int,
        metadata_keyword_max_chars: int,
        metadata_summary_max_chars: int,
        metadata_question_count: int,
        metadata_generate_questions: bool,
    ) -> None:
        self._inner = inner
        self._enrich_document_metadata = enrich_document_metadata
        self._inject_metadata_header = inject_metadata_header
        self._metadata_keywords_provider = metadata_keywords_provider
        self._metadata_keyword_top_k = metadata_keyword_top_k
        self._metadata_keyword_max_chars = metadata_keyword_max_chars
        self._metadata_summary_max_chars = metadata_summary_max_chars
        self._metadata_question_count = metadata_question_count
        self._metadata_generate_questions = metadata_generate_questions

    def _enrichment_kwargs(self) -> dict[str, Any]:
        return {
            "keywords_provider": self._metadata_keywords_provider,
            "keyword_top_k": self._metadata_keyword_top_k,
            "keyword_max_chars": self._metadata_keyword_max_chars,
            "summary_max_chars": self._metadata_summary_max_chars,
            "question_count": self._metadata_question_count,
            "generate_questions": self._metadata_generate_questions,
        }

    def split_documents(self, documents: list[Document]) -> list[Document]:
        enrichment_kwargs = self._enrichment_kwargs()
        working = list(documents)
        if self._enrich_document_metadata:
            working = enrich_documents_metadata(working, **enrichment_kwargs)

        chunks = self._inner.split_documents(working)
        if not self._inject_metadata_header:
            return chunks

        out: list[Document] = []
        for chunk in chunks:
            meta = dict(chunk.metadata)
            if "metadata_enrichment_schema" not in meta:
                meta.update(
                    build_document_metadata_enrichment(
                        chunk.page_content,
                        metadata=meta,
                        **enrichment_kwargs,
                    )
                )
            header = build_rich_metadata_header(meta)
            if not header:
                out.append(chunk)
                continue
            payload = f"{header}\n\nContent:\n{chunk.page_content}".strip()
            meta["rich_metadata_header_applied"] = True
            meta["rich_metadata_header_chars"] = len(header)
            out.append(chunk.model_copy(update={"page_content": payload, "metadata": meta}))
        return out


class ChunkerFactory:
    """
    Factory for creating chunking strategy instances.

    Supported strategies:
    - auto: Content-aware strategy selection
    - manuscript: Preset for manuscript-like documents
    - langchain_recursive: RecursiveCharacterTextSplitter (default)
    - langchain_token: TokenTextSplitter (by token count)
    - parent_child: Two-level parent-child chunking
    - semantic_sentence: Sentence-boundary aggregation
    - sentence_window: Sentence window (sentence overlap)
    - separator: Custom separator-based chunking
    - llama_index: LlamaIndex SentenceSplitter (disabled)
    - llama_index_hierarchical: LlamaIndex hierarchical (disabled)
    - markdown_header: Markdown header-based chunking
    - markdown_aware: Enhanced markdown-aware chunking
    - json: JSON structure-aware chunking
    - code: Programming language-aware chunking
    - smart_code: AST-like code chunking (Python)
    - outline: Numbered-outline aware chunking
    - transcript: Transcript / dialogue aware chunking
    - qa_pairs: Q/A pair aware chunking
    - paper: Academic paper section aware chunking
    - book_structured: Book chapter/part aware chunking
    - laws_structured: Legal document clause-aware chunking
    - policy_manual_structured: Policy/manual clause-aware parent-child chunking
    - email_thread: Email thread aware chunking
    - sop_steps: SOP/procedure step-aware chunking
    - glossary: Glossary/dictionary entry-aware chunking
    - resume_structured: Resume/CV section-aware chunking
    - presentation_slides: Slide-aware chunking
    - csv_rows: CSV row-aware chunking
    - spreadsheet_sheet: Spreadsheet sheet-aware chunking
    - markdown_table: Markdown table-aware chunking
    - chat_history: Timestamped chat history chunking
    - changelog: Changelog/release notes aware chunking
    - log_events: Log entry aware chunking
    - subtitles: Subtitles (SRT/VTT-like) cue chunking
    - api_reference: API endpoint reference aware chunking
    - diff_patch: Diff/patch aware chunking
    - kv_config: Key-value config aware chunking
    - qa_markdown: Markdown Q/A aware chunking
    - meeting_minutes: Meeting minutes section-aware chunking
    - timeline_events: Timeline/date-event aware chunking
    - html_sections: HTML heading-aware chunking
    - rst_sections: reStructuredText section-aware chunking
    - asciidoc_sections: AsciiDoc section-aware chunking
    - latex_sections: LaTeX section-aware chunking
    - orgmode_sections: Org-mode section-aware chunking
    - mediawiki_sections: MediaWiki section-aware chunking
    - yaml_manifest: YAML manifest multi-doc chunking
    - toml_config: TOML config table-aware chunking
    - sql_schema: SQL schema/DDL statement chunking
    - stacktrace: Stacktrace block-aware chunking
    - dockerfile: Dockerfile instruction-aware chunking
    - makefile: Makefile target-aware chunking
    - nginx_config: Nginx config block-aware chunking
    - jira_ticket: Jira/issue ticket section-aware chunking
    - prd_spec: PRD/requirements section-aware chunking
    - jsonl_records: JSONL/NDJSON record-aware chunking
    - xml_feed: XML feed (RSS/Atom) item-aware chunking
    - openapi_spec: OpenAPI/Swagger spec aware chunking
    - graphql_schema: GraphQL schema aware chunking
    - proto_schema: Protocol Buffers schema aware chunking
    - terraform_hcl: Terraform/HCL block-aware chunking
    - git_commit_log: Git commit-log aware chunking
    - postmortem_report: Incident postmortem/RCA section-aware chunking
    - docker_compose: Docker Compose service-aware chunking
    - github_actions: GitHub Actions workflow job-aware chunking
    - gitlab_ci: GitLab CI pipeline job-aware chunking
    - ansible_playbook: Ansible playbook play-aware chunking
    - markdown_frontmatter: Markdown YAML frontmatter aware chunking
    - http_trace: HTTP request/response trace chunking
    - junit_xml: JUnit XML testcase-aware chunking
    - sitemap_xml: Sitemap XML entry-aware chunking
    - maven_pom: Maven POM dependency/plugin aware chunking
    - terraform_plan: Terraform plan output block-aware chunking

    Integrated pipeline strategies (handled separately):
    - integrated_naive: General-purpose chunking
    - integrated_book: Book format chunking
    - integrated_laws: Legal document chunking
    - integrated_email: Email format chunking
    """

    SUPPORTED_STRATEGIES = CHUNKER_STRATEGY_REGISTRY

    INTEGRATED_PIPELINE_STRATEGIES = {
        "integrated_naive",
        "integrated_book",
        "integrated_laws",
        "integrated_email",
    }

    STRATEGY_ALIASES = {
        # Integrated pipeline presets
        "integrated": "integrated_naive",
        "naive": "integrated_naive",
        "book": "integrated_book",
        "law": "integrated_laws",
        "laws": "integrated_laws",
        "legal": "integrated_laws",
        "email": "integrated_email",
        "mail": "integrated_email",
        **CHUNKER_STRATEGY_ALIASES,
    }

    def __init__(self) -> None:
        self._init_kwargs_cache: dict[type[BaseChunker], set[str] | Literal[False]] = {}

    def resolve_strategy(self, strategy: str | None) -> str:
        """
        Resolve and validate the chunking strategy name.

        Args:
            strategy: Strategy name or None for default.

        Returns:
            Normalized strategy name.

        Raises:
            ValueError: If strategy is not supported.
        """
        normalized = "" if strategy is None else strategy.lower()
        if normalized == "":
            normalized = settings.DEFAULT_CHUNK_STRATEGY.lower()

        reject_retired_chunk_strategy(normalized)

        if normalized in self.STRATEGY_ALIASES:
            normalized = self.STRATEGY_ALIASES[normalized]

        if normalized in self.INTEGRATED_PIPELINE_STRATEGIES:
            return normalized

        if normalized not in self.SUPPORTED_STRATEGIES:
            all_strategies = sorted(self.SUPPORTED_STRATEGIES) + sorted(self.INTEGRATED_PIPELINE_STRATEGIES)
            raise ValueError(f"Unsupported chunk strategy '{strategy}'. Supported strategies: {all_strategies}")

        if (
            normalized in OPTIONAL_DEPENDENCY_STRATEGIES
            and normalized.startswith("llama_index")
            and not settings.LLAMA_INDEX_ENABLED
        ):
            raise ValueError("LlamaIndex chunker is disabled. Set LLAMA_INDEX_ENABLED=True to use it.")

        return normalized

    def get_chunker(
        self,
        strategy: str | None,
        chunk_size: int,
        chunk_overlap: int,
        **kwargs: Any,
    ) -> BaseChunker:
        """
        Create a chunker instance for the specified strategy.

        Args:
            strategy: Chunking strategy name.
            chunk_size: Target chunk size in characters.
            chunk_overlap: Overlap between chunks in characters.

        Returns:
            BaseChunker instance.

        Raises:
            ValueError: If strategy is Integrated pipeline-based (requires different handling).
        """
        resolved = self.resolve_strategy(strategy)

        if resolved in self.INTEGRATED_PIPELINE_STRATEGIES:
            raise ValueError(
                f"Chunk strategy '{resolved}' is handled by the integrated parse+chunk pipeline. "
                f"Use 'chunk_file' from app.rag.ingestion.chunking.factory instead."
            )

        enrich_document_metadata = bool(kwargs.pop("enrich_document_metadata", False))
        inject_metadata_header = bool(kwargs.pop("inject_metadata_header", False))
        metadata_keywords_provider = str(kwargs.pop("metadata_keywords_provider", "auto") or "auto")
        metadata_keyword_top_k = int(kwargs.pop("metadata_keyword_top_k", 8))
        metadata_keyword_max_chars = int(kwargs.pop("metadata_keyword_max_chars", 4000))
        metadata_summary_max_chars = int(kwargs.pop("metadata_summary_max_chars", 220))
        metadata_question_count = int(kwargs.pop("metadata_question_count", 3))
        metadata_generate_questions = bool(kwargs.pop("metadata_generate_questions", False))

        chunker_cls = self.SUPPORTED_STRATEGIES[resolved]
        chunker: BaseChunker

        # Strategy-specific kwargs are allowed for enterprise tuning (e.g. parent_child child_ratio/min_child_size),
        # but must not break chunkers that don't accept them.
        if kwargs:
            accepted = self._init_kwargs_cache.get(chunker_cls)
            if accepted is None:
                sig = inspect.signature(chunker_cls.__init__)
                if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                    # Accept any kwargs (constructor has **kwargs).
                    accepted = False  # sentinel: accept-all
                else:
                    accepted = {
                        p.name
                        for p in sig.parameters.values()
                        if p.name != "self"
                        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
                    }
                self._init_kwargs_cache[chunker_cls] = accepted

            if accepted is False:
                chunker = chunker_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap, **kwargs)
            else:
                filtered = {k: v for k, v in kwargs.items() if k in accepted}
                chunker = chunker_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap, **filtered)
        else:
            chunker = chunker_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        if enrich_document_metadata or inject_metadata_header:
            return _MetadataAwareChunker(
                chunker,
                enrich_document_metadata=enrich_document_metadata or inject_metadata_header,
                inject_metadata_header=inject_metadata_header,
                metadata_keywords_provider=metadata_keywords_provider,
                metadata_keyword_top_k=metadata_keyword_top_k,
                metadata_keyword_max_chars=metadata_keyword_max_chars,
                metadata_summary_max_chars=metadata_summary_max_chars,
                metadata_question_count=metadata_question_count,
                metadata_generate_questions=metadata_generate_questions,
            )

        return chunker

    def is_integrated_pipeline_strategy(self, strategy: str | None) -> bool:
        """Check if the strategy requires the integrated parse+chunk pipeline."""
        try:
            resolved = self.resolve_strategy(strategy)
            return resolved in self.INTEGRATED_PIPELINE_STRATEGIES
        except ValueError:
            return False


# Singleton factory instance
chunker_factory = ChunkerFactory()


ChunkStrategy = Literal["integrated_naive", "integrated_book", "integrated_laws", "integrated_email"]

logger = logging.getLogger("integrated.bridge")


def chunk_file(
    file_path: Path,
    *,
    strategy: ChunkStrategy,
    binary: bytes | None = None,
    callback: Callable | None = None,
    **kwargs: Any,
) -> list[dict]:
    """
    Process a file using the integrated parse+chunk pipeline.

    Args:
        file_path: Path to the file to process.
        strategy: Integrated pipeline strategy to use.
        binary: Optional file binary content (if already loaded).
        callback: Progress callback function(progress, message).
        **kwargs: Additional arguments passed to the chunker.

    Returns:
        List of chunk dictionaries produced by the integrated pipeline.

    Raises:
        ValueError: If strategy is not supported.
    """
    strat = strategy.lower()

    if strat == "integrated_naive":
        from app.rag.ingestion.parsing.files.general import chunk as chunk_fn
    elif strat == "integrated_book":
        from app.rag.ingestion.parsing.files.book import chunk as chunk_fn
    elif strat == "integrated_laws":
        from app.rag.ingestion.parsing.files.laws import chunk as chunk_fn
    elif strat == "integrated_email":
        from app.rag.ingestion.parsing.files.email import chunk as chunk_fn
    else:
        raise ValueError(
            f"Unsupported Integrated pipeline strategy: {strategy}. "
            "Supported: integrated_naive, integrated_book, integrated_laws, integrated_email"
        )

    if callback is None:

        def callback(prog=None, msg=""):
            if msg:
                logger.info("[integrated] %s (%s)", msg, prog)

    return chunk_fn(str(file_path), binary=binary, callback=callback, **kwargs)
