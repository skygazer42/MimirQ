from dataclasses import dataclass

RETIRED_CHUNK_STRATEGIES = frozenset({"agentic_chunker", "late_chunking", "late_chunking_jina", "raptor"})


class RetiredChunkStrategyError(ValueError):
    """A removed strategy cannot be selected for ingestion or reused from a cache."""


def reject_retired_chunk_strategy(value: str | None) -> None:
    if value is not None and value.strip().lower() in RETIRED_CHUNK_STRATEGIES:
        raise RetiredChunkStrategyError(
            f"Chunk strategy '{value}' has been removed. Select a supported chunk strategy."
        )


@dataclass(frozen=True, slots=True)
class ChunkerCapability:
    strategy_name: str
    module_name: str
    class_name: str
    experimental: bool = False
    optional_dependency: bool = False


CHUNKER_CAPABILITIES = (
    ChunkerCapability("auto", "app.rag.ingestion.chunking.strategies.auto", "AutoChunker"),
    ChunkerCapability("manuscript", "app.rag.ingestion.chunking.strategies.manuscript", "ManuscriptChunker"),
    ChunkerCapability(
        "langchain_recursive", "app.rag.ingestion.chunking.strategies.text.recursive", "LangChainRecursiveChunker"
    ),
    ChunkerCapability("langchain_token", "app.rag.ingestion.chunking.strategies.text.token", "LangChainTokenChunker"),
    ChunkerCapability("pdf_layout", "app.rag.ingestion.chunking.strategies.documents.pdf_layout", "PDFLayoutChunker"),
    ChunkerCapability(
        "semantic_sentence", "app.rag.ingestion.chunking.strategies.model_based.semantic", "SemanticSentenceChunker"
    ),
    ChunkerCapability(
        "sentence_window", "app.rag.ingestion.chunking.strategies.text.sentence_window", "SentenceWindowChunker"
    ),
    ChunkerCapability("separator", "app.rag.ingestion.chunking.strategies.text.separator", "SeparatorChunker"),
    ChunkerCapability(
        "llama_index",
        "app.rag.ingestion.chunking.strategies.model_based.llama_index",
        "LlamaIndexChunker",
        optional_dependency=True,
    ),
    ChunkerCapability(
        "llama_index_hierarchical",
        "app.rag.ingestion.chunking.strategies.model_based.llama_index",
        "LlamaIndexHierarchicalChunker",
        optional_dependency=True,
    ),
    ChunkerCapability("parent_child", "app.rag.ingestion.chunking.strategies.text.parent_child", "ParentChildChunker"),
    ChunkerCapability(
        "markdown_header", "app.rag.ingestion.chunking.strategies.markup.markdown", "MarkdownHeaderChunker"
    ),
    ChunkerCapability(
        "markdown_outline", "app.rag.ingestion.chunking.strategies.markup.markdown_outline", "MarkdownOutlineChunker"
    ),
    ChunkerCapability(
        "markdown_aware", "app.rag.ingestion.chunking.strategies.markup.markdown", "MarkdownAwareChunker"
    ),
    ChunkerCapability(
        "markdown_hierarchy",
        "app.rag.ingestion.chunking.strategies.markup.markdown_hierarchy",
        "MarkdownHierarchyChunker",
    ),
    ChunkerCapability("markdown", "app.rag.ingestion.chunking.strategies.markup.markdown", "MarkdownHeaderChunker"),
    ChunkerCapability(
        "text_hierarchy", "app.rag.ingestion.chunking.strategies.text.text_hierarchy", "TextHierarchyChunker"
    ),
    ChunkerCapability("json", "app.rag.ingestion.chunking.strategies.code.json", "JSONChunker"),
    ChunkerCapability("code", "app.rag.ingestion.chunking.strategies.code.source", "CodeChunker"),
    ChunkerCapability("smart_code", "app.rag.ingestion.chunking.strategies.code.source", "SmartCodeChunker"),
    ChunkerCapability("outline", "app.rag.ingestion.chunking.strategies.text.outline", "OutlineChunker"),
    ChunkerCapability("transcript", "app.rag.ingestion.chunking.strategies.records.transcript", "TranscriptChunker"),
    ChunkerCapability("qa_pairs", "app.rag.ingestion.chunking.strategies.records.qa_pairs", "QAPairsChunker"),
    ChunkerCapability(
        "proposition",
        "app.rag.ingestion.chunking.strategies.model_based.proposition",
        "PropositionChunker",
        experimental=True,
    ),
    ChunkerCapability("paper", "app.rag.ingestion.chunking.strategies.documents.paper", "PaperChunker"),
    ChunkerCapability(
        "book_structured", "app.rag.ingestion.chunking.strategies.documents.book_structured", "BookStructuredChunker"
    ),
    ChunkerCapability(
        "laws_structured", "app.rag.ingestion.chunking.strategies.documents.laws_structured", "LawsStructuredChunker"
    ),
    ChunkerCapability(
        "policy_manual_structured",
        "app.rag.ingestion.chunking.strategies.documents.policy_manual_structured",
        "PolicyManualStructuredChunker",
    ),
    ChunkerCapability(
        "email_thread", "app.rag.ingestion.chunking.strategies.records.email_thread", "EmailThreadChunker"
    ),
    ChunkerCapability("sop_steps", "app.rag.ingestion.chunking.strategies.documents.sop_steps", "SOPStepsChunker"),
    ChunkerCapability("glossary", "app.rag.ingestion.chunking.strategies.documents.glossary", "GlossaryChunker"),
    ChunkerCapability(
        "resume_structured",
        "app.rag.ingestion.chunking.strategies.documents.resume_structured",
        "ResumeStructuredChunker",
    ),
    ChunkerCapability(
        "presentation_slides",
        "app.rag.ingestion.chunking.strategies.documents.presentation_slides",
        "PresentationSlidesChunker",
    ),
    ChunkerCapability("csv_rows", "app.rag.ingestion.chunking.strategies.records.csv_rows", "CsvRowsChunker"),
    ChunkerCapability(
        "spreadsheet_sheet",
        "app.rag.ingestion.chunking.strategies.records.spreadsheet_sheet",
        "SpreadsheetSheetChunker",
    ),
    ChunkerCapability(
        "markdown_table", "app.rag.ingestion.chunking.strategies.markup.markdown_table", "MarkdownTableChunker"
    ),
    ChunkerCapability(
        "chat_history", "app.rag.ingestion.chunking.strategies.records.chat_history", "ChatHistoryChunker"
    ),
    ChunkerCapability("changelog", "app.rag.ingestion.chunking.strategies.records.changelog", "ChangelogChunker"),
    ChunkerCapability("log_events", "app.rag.ingestion.chunking.strategies.records.log_events", "LogEventsChunker"),
    ChunkerCapability("subtitles", "app.rag.ingestion.chunking.strategies.records.subtitles", "SubtitlesChunker"),
    ChunkerCapability(
        "api_reference", "app.rag.ingestion.chunking.strategies.documents.api_reference", "APIReferenceChunker"
    ),
    ChunkerCapability("diff_patch", "app.rag.ingestion.chunking.strategies.code.diff_patch", "DiffPatchChunker"),
    ChunkerCapability("kv_config", "app.rag.ingestion.chunking.strategies.config.kv_config", "KVConfigChunker"),
    ChunkerCapability("qa_markdown", "app.rag.ingestion.chunking.strategies.records.qa_markdown", "QAMarkdownChunker"),
    ChunkerCapability(
        "meeting_minutes", "app.rag.ingestion.chunking.strategies.records.meeting_minutes", "MeetingMinutesChunker"
    ),
    ChunkerCapability(
        "timeline_events", "app.rag.ingestion.chunking.strategies.records.timeline_events", "TimelineEventsChunker"
    ),
    ChunkerCapability(
        "html_sections", "app.rag.ingestion.chunking.strategies.markup.html_sections", "HTMLSectionsChunker"
    ),
    ChunkerCapability(
        "rst_sections", "app.rag.ingestion.chunking.strategies.markup.rst_sections", "RSTSectionsChunker"
    ),
    ChunkerCapability(
        "asciidoc_sections",
        "app.rag.ingestion.chunking.strategies.markup.asciidoc_sections",
        "AsciiDocSectionsChunker",
    ),
    ChunkerCapability(
        "latex_sections", "app.rag.ingestion.chunking.strategies.markup.latex_sections", "LatexSectionsChunker"
    ),
    ChunkerCapability(
        "orgmode_sections",
        "app.rag.ingestion.chunking.strategies.markup.orgmode_sections",
        "OrgModeSectionsChunker",
    ),
    ChunkerCapability(
        "mediawiki_sections",
        "app.rag.ingestion.chunking.strategies.markup.mediawiki_sections",
        "MediaWikiSectionsChunker",
    ),
    ChunkerCapability(
        "yaml_manifest", "app.rag.ingestion.chunking.strategies.config.yaml_manifest", "YAMLManifestChunker"
    ),
    ChunkerCapability("toml_config", "app.rag.ingestion.chunking.strategies.config.toml_config", "TOMLConfigChunker"),
    ChunkerCapability("sql_schema", "app.rag.ingestion.chunking.strategies.code.sql_schema", "SqlSchemaChunker"),
    ChunkerCapability("stacktrace", "app.rag.ingestion.chunking.strategies.records.stacktrace", "StackTraceChunker"),
    ChunkerCapability("dockerfile", "app.rag.ingestion.chunking.strategies.config.dockerfile", "DockerfileChunker"),
    ChunkerCapability("makefile", "app.rag.ingestion.chunking.strategies.config.makefile", "MakefileChunker"),
    ChunkerCapability(
        "nginx_config", "app.rag.ingestion.chunking.strategies.config.nginx_config", "NginxConfigChunker"
    ),
    ChunkerCapability("jira_ticket", "app.rag.ingestion.chunking.strategies.records.jira_ticket", "JiraTicketChunker"),
    ChunkerCapability("prd_spec", "app.rag.ingestion.chunking.strategies.documents.prd_spec", "PRDSpecChunker"),
    ChunkerCapability(
        "jsonl_records", "app.rag.ingestion.chunking.strategies.records.jsonl_records", "JsonlRecordsChunker"
    ),
    ChunkerCapability("xml_feed", "app.rag.ingestion.chunking.strategies.records.xml_feed", "XMLFeedChunker"),
    ChunkerCapability("openapi_spec", "app.rag.ingestion.chunking.strategies.code.openapi_spec", "OpenAPISpecChunker"),
    ChunkerCapability(
        "graphql_schema", "app.rag.ingestion.chunking.strategies.code.graphql_schema", "GraphQLSchemaChunker"
    ),
    ChunkerCapability("proto_schema", "app.rag.ingestion.chunking.strategies.code.proto_schema", "ProtoSchemaChunker"),
    ChunkerCapability(
        "terraform_hcl", "app.rag.ingestion.chunking.strategies.config.terraform_hcl", "TerraformHCLChunker"
    ),
    ChunkerCapability(
        "git_commit_log", "app.rag.ingestion.chunking.strategies.records.git_commit_log", "GitCommitLogChunker"
    ),
    ChunkerCapability(
        "postmortem_report",
        "app.rag.ingestion.chunking.strategies.documents.postmortem_report",
        "PostmortemReportChunker",
    ),
    ChunkerCapability(
        "docker_compose", "app.rag.ingestion.chunking.strategies.config.docker_compose", "DockerComposeChunker"
    ),
    ChunkerCapability(
        "github_actions",
        "app.rag.ingestion.chunking.strategies.config.github_actions",
        "GitHubActionsChunker",
    ),
    ChunkerCapability("gitlab_ci", "app.rag.ingestion.chunking.strategies.config.gitlab_ci", "GitLabCIChunker"),
    ChunkerCapability(
        "ansible_playbook",
        "app.rag.ingestion.chunking.strategies.config.ansible_playbook",
        "AnsiblePlaybookChunker",
    ),
    ChunkerCapability(
        "markdown_frontmatter",
        "app.rag.ingestion.chunking.strategies.markup.markdown_frontmatter",
        "MarkdownFrontmatterChunker",
    ),
    ChunkerCapability("http_trace", "app.rag.ingestion.chunking.strategies.records.http_trace", "HTTPTraceChunker"),
    ChunkerCapability("junit_xml", "app.rag.ingestion.chunking.strategies.records.junit_xml", "JUnitXMLChunker"),
    ChunkerCapability("sitemap_xml", "app.rag.ingestion.chunking.strategies.records.sitemap_xml", "SitemapXMLChunker"),
    ChunkerCapability("maven_pom", "app.rag.ingestion.chunking.strategies.config.maven_pom", "MavenPOMChunker"),
    ChunkerCapability(
        "terraform_plan",
        "app.rag.ingestion.chunking.strategies.config.terraform_plan",
        "TerraformPlanChunker",
    ),
)

CHUNKER_CAPABILITIES_BY_NAME = {item.strategy_name: item for item in CHUNKER_CAPABILITIES}

CHUNKER_STRATEGY_ALIASES = {
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
    "layout_pdf": "pdf_layout",
    "pdf_layout_v1": "pdf_layout",
}

OPTIONAL_DEPENDENCY_STRATEGIES = frozenset(
    item.strategy_name for item in CHUNKER_CAPABILITIES if item.optional_dependency
)
EXPERIMENTAL_STRATEGIES = frozenset(item.strategy_name for item in CHUNKER_CAPABILITIES if item.experimental)

_CLASS_EXPORTS_UNORDERED: dict[str, tuple[str, str]] = {}
for item in CHUNKER_CAPABILITIES:
    _CLASS_EXPORTS_UNORDERED.setdefault(item.class_name, (item.module_name, item.class_name))

_CLASS_EXPORT_ORDER = [
    "LangChainRecursiveChunker",
    "LangChainTokenChunker",
    "ParentChildChunker",
    "SemanticSentenceChunker",
    "SeparatorChunker",
    "LlamaIndexChunker",
    "LlamaIndexHierarchicalChunker",
    "MarkdownHeaderChunker",
    "MarkdownAwareChunker",
    "MarkdownHierarchyChunker",
    "MarkdownOutlineChunker",
    "TextHierarchyChunker",
    "JSONChunker",
    "CodeChunker",
    "SmartCodeChunker",
    "AutoChunker",
    "OutlineChunker",
    "TranscriptChunker",
    "QAPairsChunker",
    "PropositionChunker",
    "PaperChunker",
    "ManuscriptChunker",
    "BookStructuredChunker",
    "LawsStructuredChunker",
    "PolicyManualStructuredChunker",
    "EmailThreadChunker",
    "SOPStepsChunker",
    "GlossaryChunker",
    "SentenceWindowChunker",
    "ResumeStructuredChunker",
    "PresentationSlidesChunker",
    "CsvRowsChunker",
    "SpreadsheetSheetChunker",
    "MarkdownTableChunker",
    "ChatHistoryChunker",
    "ChangelogChunker",
    "LogEventsChunker",
    "SubtitlesChunker",
    "APIReferenceChunker",
    "DiffPatchChunker",
    "KVConfigChunker",
    "QAMarkdownChunker",
    "MeetingMinutesChunker",
    "TimelineEventsChunker",
    "HTMLSectionsChunker",
    "RSTSectionsChunker",
    "AsciiDocSectionsChunker",
    "LatexSectionsChunker",
    "OrgModeSectionsChunker",
    "MediaWikiSectionsChunker",
    "YAMLManifestChunker",
    "TOMLConfigChunker",
    "SqlSchemaChunker",
    "StackTraceChunker",
    "DockerfileChunker",
    "MakefileChunker",
    "NginxConfigChunker",
    "JiraTicketChunker",
    "PRDSpecChunker",
    "JsonlRecordsChunker",
    "XMLFeedChunker",
    "OpenAPISpecChunker",
    "GraphQLSchemaChunker",
    "ProtoSchemaChunker",
    "PDFLayoutChunker",
    "TerraformHCLChunker",
    "GitCommitLogChunker",
    "PostmortemReportChunker",
    "DockerComposeChunker",
    "GitHubActionsChunker",
    "GitLabCIChunker",
    "AnsiblePlaybookChunker",
    "MarkdownFrontmatterChunker",
    "HTTPTraceChunker",
    "JUnitXMLChunker",
    "SitemapXMLChunker",
    "MavenPOMChunker",
    "TerraformPlanChunker",
]

CHUNKER_CLASS_EXPORTS = {class_name: _CLASS_EXPORTS_UNORDERED[class_name] for class_name in _CLASS_EXPORT_ORDER}

__all__ = [
    "CHUNKER_CAPABILITIES",
    "CHUNKER_CAPABILITIES_BY_NAME",
    "CHUNKER_CLASS_EXPORTS",
    "CHUNKER_STRATEGY_ALIASES",
    "ChunkerCapability",
    "EXPERIMENTAL_STRATEGIES",
    "OPTIONAL_DEPENDENCY_STRATEGIES",
    "RETIRED_CHUNK_STRATEGIES",
    "RetiredChunkStrategyError",
    "reject_retired_chunk_strategy",
]
