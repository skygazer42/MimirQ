"""
Chunker factory for selecting and creating chunking strategies.

Usage:
    from app.rag.chunking import chunker_factory

    chunker = chunker_factory.get_chunker("langchain_recursive", chunk_size=1000, chunk_overlap=200)
    chunks = chunker.split_documents(documents)
"""

from typing import Any, Optional
import inspect

from app.core.config import settings
from app.rag.chunking.base import BaseChunker
from app.rag.chunking.strategies import (
    LangChainRecursiveChunker,
    LangChainTokenChunker,
    ParentChildChunker,
    SemanticSentenceChunker,
    SeparatorChunker,
    LlamaIndexChunker,
    LlamaIndexHierarchicalChunker,
    # New splitters
    MarkdownHeaderChunker,
    MarkdownAwareChunker,
    JSONChunker,
    CodeChunker,
    SmartCodeChunker,
    AutoChunker,
    OutlineChunker,
    TranscriptChunker,
    QAPairsChunker,
    PaperChunker,
    ManuscriptChunker,
    BookStructuredChunker,
    LawsStructuredChunker,
    EmailThreadChunker,
    SOPStepsChunker,
    GlossaryChunker,
    SentenceWindowChunker,
    ResumeStructuredChunker,
    PresentationSlidesChunker,
    CsvRowsChunker,
    SpreadsheetSheetChunker,
    MarkdownTableChunker,
    ChatHistoryChunker,
    ChangelogChunker,
    LogEventsChunker,
    SubtitlesChunker,
    APIReferenceChunker,
    DiffPatchChunker,
    KVConfigChunker,
    QAMarkdownChunker,
    MeetingMinutesChunker,
    TimelineEventsChunker,
    HTMLSectionsChunker,
    RSTSectionsChunker,
    AsciiDocSectionsChunker,
    LatexSectionsChunker,
    OrgModeSectionsChunker,
    MediaWikiSectionsChunker,
    YAMLManifestChunker,
    TOMLConfigChunker,
    SqlSchemaChunker,
    StackTraceChunker,
    DockerfileChunker,
    MakefileChunker,
    NginxConfigChunker,
    JiraTicketChunker,
    PRDSpecChunker,
    JsonlRecordsChunker,
    XMLFeedChunker,
    OpenAPISpecChunker,
    GraphQLSchemaChunker,
    ProtoSchemaChunker,
    TerraformHCLChunker,
    GitCommitLogChunker,
    PostmortemReportChunker,
    DockerComposeChunker,
    GitHubActionsChunker,
    GitLabCIChunker,
    AnsiblePlaybookChunker,
    MarkdownFrontmatterChunker,
    HTTPTraceChunker,
    JUnitXMLChunker,
    SitemapXMLChunker,
    MavenPOMChunker,
    TerraformPlanChunker,
)


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

    RAGFlow strategies (handled separately):
    - ragflow_naive: General-purpose chunking
    - ragflow_book: Book format chunking
    - ragflow_laws: Legal document chunking
    - ragflow_email: Email format chunking
    """

    SUPPORTED_STRATEGIES = {
        "auto": AutoChunker,
        "manuscript": ManuscriptChunker,
        "langchain_recursive": LangChainRecursiveChunker,
        "langchain_token": LangChainTokenChunker,
        "semantic_sentence": SemanticSentenceChunker,
        "sentence_window": SentenceWindowChunker,
        "separator": SeparatorChunker,
        "llama_index": LlamaIndexChunker,
        "llama_index_hierarchical": LlamaIndexHierarchicalChunker,
        "parent_child": ParentChildChunker,
        # New splitters
        "markdown_header": MarkdownHeaderChunker,
        "markdown_aware": MarkdownAwareChunker,
        "markdown": MarkdownHeaderChunker,  # Alias
        "json": JSONChunker,
        "code": CodeChunker,
        "smart_code": SmartCodeChunker,
        "outline": OutlineChunker,
        "transcript": TranscriptChunker,
        "qa_pairs": QAPairsChunker,
        "paper": PaperChunker,
        "book_structured": BookStructuredChunker,
        "laws_structured": LawsStructuredChunker,
        "email_thread": EmailThreadChunker,
        "sop_steps": SOPStepsChunker,
        "glossary": GlossaryChunker,
        "resume_structured": ResumeStructuredChunker,
        "presentation_slides": PresentationSlidesChunker,
        "csv_rows": CsvRowsChunker,
        "spreadsheet_sheet": SpreadsheetSheetChunker,
        "markdown_table": MarkdownTableChunker,
        "chat_history": ChatHistoryChunker,
        "changelog": ChangelogChunker,
        "log_events": LogEventsChunker,
        "subtitles": SubtitlesChunker,
        "api_reference": APIReferenceChunker,
        "diff_patch": DiffPatchChunker,
        "kv_config": KVConfigChunker,
        "qa_markdown": QAMarkdownChunker,
        "meeting_minutes": MeetingMinutesChunker,
        "timeline_events": TimelineEventsChunker,
        "html_sections": HTMLSectionsChunker,
        "rst_sections": RSTSectionsChunker,
        "asciidoc_sections": AsciiDocSectionsChunker,
        "latex_sections": LatexSectionsChunker,
        "orgmode_sections": OrgModeSectionsChunker,
        "mediawiki_sections": MediaWikiSectionsChunker,
        "yaml_manifest": YAMLManifestChunker,
        "toml_config": TOMLConfigChunker,
        "sql_schema": SqlSchemaChunker,
        "stacktrace": StackTraceChunker,
        "dockerfile": DockerfileChunker,
        "makefile": MakefileChunker,
        "nginx_config": NginxConfigChunker,
        "jira_ticket": JiraTicketChunker,
        "prd_spec": PRDSpecChunker,
        "jsonl_records": JsonlRecordsChunker,
        "xml_feed": XMLFeedChunker,
        "openapi_spec": OpenAPISpecChunker,
        "graphql_schema": GraphQLSchemaChunker,
        "proto_schema": ProtoSchemaChunker,
        "terraform_hcl": TerraformHCLChunker,
        "git_commit_log": GitCommitLogChunker,
        "postmortem_report": PostmortemReportChunker,
        "docker_compose": DockerComposeChunker,
        "github_actions": GitHubActionsChunker,
        "gitlab_ci": GitLabCIChunker,
        "ansible_playbook": AnsiblePlaybookChunker,
        "markdown_frontmatter": MarkdownFrontmatterChunker,
        "http_trace": HTTPTraceChunker,
        "junit_xml": JUnitXMLChunker,
        "sitemap_xml": SitemapXMLChunker,
        "maven_pom": MavenPOMChunker,
        "terraform_plan": TerraformPlanChunker,
    }

    RAGFLOW_STRATEGIES = {
        "ragflow_naive",
        "ragflow_book",
        "ragflow_laws",
        "ragflow_email",
    }

    STRATEGY_ALIASES = {
        # RAGFlow presets
        "ragflow": "ragflow_naive",
        "naive": "ragflow_naive",
        "book": "ragflow_book",
        "law": "ragflow_laws",
        "laws": "ragflow_laws",
        "legal": "ragflow_laws",
        "email": "ragflow_email",
        "mail": "ragflow_email",
        # Local presets
        "faq": "qa_pairs",
        "qa": "qa_pairs",
        "qna": "qa_pairs",
        "sop": "sop_steps",
        "procedure": "sop_steps",
        "workflow": "sop_steps",
        "steps": "sop_steps",
        "contract": "laws_structured",
        "policy": "laws_structured",
        "regulation": "laws_structured",
        "dictionary": "glossary",
        "terminology": "glossary",
        "emailthread": "email_thread",
        "mail_thread": "email_thread",
        "book_local": "book_structured",
        "laws_local": "laws_structured",
        # New local presets
        "resume": "resume_structured",
        "cv": "resume_structured",
        "简历": "resume_structured",
        "履历": "resume_structured",
        "slides": "presentation_slides",
        "slide": "presentation_slides",
        "ppt": "presentation_slides",
        "pptx": "presentation_slides",
        "presentation": "presentation_slides",
        "deck": "presentation_slides",
        "幻灯片": "presentation_slides",
        "csv": "csv_rows",
        "excel": "spreadsheet_sheet",
        "xlsx": "spreadsheet_sheet",
        "xls": "spreadsheet_sheet",
        "spreadsheet": "spreadsheet_sheet",
        "table": "markdown_table",
        "md_table": "markdown_table",
        "chat": "chat_history",
        "chatlog": "chat_history",
        "im": "chat_history",
        "聊天记录": "chat_history",
        "对话记录": "chat_history",
        "changelog": "changelog",
        "release_notes": "changelog",
        "releasenotes": "changelog",
        "release": "changelog",
        "releases": "changelog",
        "log": "log_events",
        "logs": "log_events",
        "日志": "log_events",
        "subtitles": "subtitles",
        "subtitle": "subtitles",
        "srt": "subtitles",
        "vtt": "subtitles",
        "字幕": "subtitles",
        "api": "api_reference",
        "openapi": "openapi_spec",
        "swagger": "openapi_spec",
        "接口文档": "api_reference",
        "diff": "diff_patch",
        "patch": "diff_patch",
        "gitdiff": "diff_patch",
        "git_diff": "diff_patch",
        "kv": "kv_config",
        "env": "kv_config",
        "dotenv": "kv_config",
        "ini": "kv_config",
        "properties": "kv_config",
        "配置": "kv_config",
        "qa_md": "qa_markdown",
        "faq_md": "qa_markdown",
        "md_qa": "qa_markdown",
        "minutes": "meeting_minutes",
        "meeting": "meeting_minutes",
        "meeting_notes": "meeting_minutes",
        "会议纪要": "meeting_minutes",
        "timeline": "timeline_events",
        "chronology": "timeline_events",
        "timeline_events": "timeline_events",
        "时间线": "timeline_events",
        "时间轴": "timeline_events",
        "时间记录": "timeline_events",
        # Markup / text formats
        "html_sections": "html_sections",
        "html": "html_sections",
        "rst": "rst_sections",
        "restructuredtext": "rst_sections",
        "restructured_text": "rst_sections",
        "asciidoc": "asciidoc_sections",
        "adoc": "asciidoc_sections",
        "asciidoc_sections": "asciidoc_sections",
        "latex": "latex_sections",
        "tex": "latex_sections",
        "latex_sections": "latex_sections",
        "org": "orgmode_sections",
        "orgmode": "orgmode_sections",
        "org_mode": "orgmode_sections",
        "wiki": "mediawiki_sections",
        "mediawiki": "mediawiki_sections",
        "wikitext": "mediawiki_sections",
        "xml_feed": "xml_feed",
        "rss": "xml_feed",
        "atom": "xml_feed",
        "feed": "xml_feed",
        # Config / code formats
        "jsonl": "jsonl_records",
        "ndjson": "jsonl_records",
        "jsonl_records": "jsonl_records",
        "yaml": "yaml_manifest",
        "yml": "yaml_manifest",
        "k8s": "yaml_manifest",
        "kubernetes": "yaml_manifest",
        "manifest": "yaml_manifest",
        "openapi_spec": "openapi_spec",
        "swagger_spec": "openapi_spec",
        "graphql": "graphql_schema",
        "gql": "graphql_schema",
        "graphql_schema": "graphql_schema",
        "proto": "proto_schema",
        "protobuf": "proto_schema",
        "proto_schema": "proto_schema",
        "terraform": "terraform_hcl",
        "tf": "terraform_hcl",
        "hcl": "terraform_hcl",
        "terraform_hcl": "terraform_hcl",
        "toml": "toml_config",
        "toml_config": "toml_config",
        "sql": "sql_schema",
        "ddl": "sql_schema",
        "schema": "sql_schema",
        "sql_schema": "sql_schema",
        "git_log": "git_commit_log",
        "gitlog": "git_commit_log",
        "git_commits": "git_commit_log",
        "commit_log": "git_commit_log",
        "git_commit_log": "git_commit_log",
        "stack": "stacktrace",
        "trace": "stacktrace",
        "traceback": "stacktrace",
        "stacktrace": "stacktrace",
        "docker": "dockerfile",
        "dockerfile": "dockerfile",
        "make": "makefile",
        "makefile": "makefile",
        "nginx": "nginx_config",
        "nginx_conf": "nginx_config",
        "nginx_config": "nginx_config",
        # Business docs
        "jira": "jira_ticket",
        "ticket": "jira_ticket",
        "issue": "jira_ticket",
        "jira_ticket": "jira_ticket",
        "prd": "prd_spec",
        "requirements": "prd_spec",
        "spec": "prd_spec",
        "prd_spec": "prd_spec",
        "postmortem": "postmortem_report",
        "rca": "postmortem_report",
        "incident_report": "postmortem_report",
        "postmortem_report": "postmortem_report",
        # DevOps / CI / infra
        "compose": "docker_compose",
        "docker-compose": "docker_compose",
        "docker_compose": "docker_compose",
        "github_actions": "github_actions",
        "github_action": "github_actions",
        "github_workflow": "github_actions",
        "gha": "github_actions",
        "gitlab": "gitlab_ci",
        "gitlab_ci": "gitlab_ci",
        "gitlab-ci": "gitlab_ci",
        "ansible": "ansible_playbook",
        "playbook": "ansible_playbook",
        "ansible_playbook": "ansible_playbook",
        "frontmatter": "markdown_frontmatter",
        "md_frontmatter": "markdown_frontmatter",
        "markdown_frontmatter": "markdown_frontmatter",
        "http_trace": "http_trace",
        "httpdump": "http_trace",
        "curl_verbose": "http_trace",
        "junit": "junit_xml",
        "junit_report": "junit_xml",
        "junit_xml": "junit_xml",
        "sitemap": "sitemap_xml",
        "sitemap_xml": "sitemap_xml",
        "pom": "maven_pom",
        "pom_xml": "maven_pom",
        "maven": "maven_pom",
        "maven_pom": "maven_pom",
        "terraform_plan": "terraform_plan",
        "tfplan": "terraform_plan",
    }

    def resolve_strategy(self, strategy: Optional[str]) -> str:
        """
        Resolve and validate the chunking strategy name.

        Args:
            strategy: Strategy name or None for default.

        Returns:
            Normalized strategy name.

        Raises:
            ValueError: If strategy is not supported.
        """
        normalized = (strategy or settings.DEFAULT_CHUNK_STRATEGY).lower()

        if normalized in self.STRATEGY_ALIASES:
            normalized = self.STRATEGY_ALIASES[normalized]

        if normalized in self.RAGFLOW_STRATEGIES:
            return normalized

        if normalized not in self.SUPPORTED_STRATEGIES:
            all_strategies = sorted(self.SUPPORTED_STRATEGIES) + sorted(self.RAGFLOW_STRATEGIES)
            raise ValueError(
                f"Unsupported chunk strategy '{strategy}'. "
                f"Supported strategies: {all_strategies}"
            )

        if normalized.startswith("llama_index") and not settings.LLAMA_INDEX_ENABLED:
            raise ValueError(
                "LlamaIndex chunker is disabled. Set LLAMA_INDEX_ENABLED=True to use it."
            )

        return normalized

    def get_chunker(
        self,
        strategy: Optional[str],
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
            ValueError: If strategy is RAGFlow-based (requires different handling).
        """
        resolved = self.resolve_strategy(strategy)

        if resolved in self.RAGFLOW_STRATEGIES:
            raise ValueError(
                f"Chunk strategy '{resolved}' is handled by the RAGFlow pipeline. "
                f"Use 'chunk_file' from app.rag.chunking.ragflow.bridge instead."
            )

        chunker_cls = self.SUPPORTED_STRATEGIES[resolved]

        # Strategy-specific kwargs are allowed for enterprise tuning (e.g. parent_child child_ratio/min_child_size),
        # but must not break chunkers that don't accept them.
        if kwargs:
            cache = getattr(self, "_init_kwargs_cache", None)
            if cache is None:
                cache = {}
                setattr(self, "_init_kwargs_cache", cache)

            accepted = cache.get(chunker_cls)
            if accepted is None:
                try:
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
                except Exception:  # pragma: no cover
                    accepted = set()
                cache[chunker_cls] = accepted

            if accepted is False:
                return chunker_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap, **kwargs)

            filtered = {k: v for k, v in kwargs.items() if k in accepted}
            return chunker_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap, **filtered)

        return chunker_cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def is_ragflow_strategy(self, strategy: Optional[str]) -> bool:
        """Check if the strategy requires RAGFlow pipeline."""
        try:
            resolved = self.resolve_strategy(strategy)
            return resolved in self.RAGFLOW_STRATEGIES
        except ValueError:
            return False


# Singleton factory instance
chunker_factory = ChunkerFactory()
