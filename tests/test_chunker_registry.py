import json
import os
import subprocess
import sys
import textwrap

import pytest

from app.rag.chunking.factory import chunker_factory

EXPECTED_SUPPORTED_STRATEGIES = [
    "agentic_chunker",
    "ansible_playbook",
    "api_reference",
    "asciidoc_sections",
    "auto",
    "book_structured",
    "changelog",
    "chat_history",
    "code",
    "csv_rows",
    "diff_patch",
    "docker_compose",
    "dockerfile",
    "email_thread",
    "git_commit_log",
    "github_actions",
    "gitlab_ci",
    "glossary",
    "graphql_schema",
    "html_sections",
    "http_trace",
    "jira_ticket",
    "json",
    "jsonl_records",
    "junit_xml",
    "kv_config",
    "langchain_recursive",
    "langchain_token",
    "late_chunking",
    "late_chunking_jina",
    "latex_sections",
    "laws_structured",
    "llama_index",
    "llama_index_hierarchical",
    "log_events",
    "makefile",
    "manuscript",
    "markdown",
    "markdown_aware",
    "markdown_frontmatter",
    "markdown_header",
    "markdown_hierarchy",
    "markdown_outline",
    "markdown_table",
    "maven_pom",
    "mediawiki_sections",
    "meeting_minutes",
    "nginx_config",
    "openapi_spec",
    "orgmode_sections",
    "outline",
    "paper",
    "parent_child",
    "pdf_layout",
    "policy_manual_structured",
    "postmortem_report",
    "prd_spec",
    "presentation_slides",
    "proposition",
    "proto_schema",
    "qa_markdown",
    "qa_pairs",
    "raptor",
    "resume_structured",
    "rst_sections",
    "semantic_sentence",
    "sentence_window",
    "separator",
    "sitemap_xml",
    "smart_code",
    "sop_steps",
    "spreadsheet_sheet",
    "sql_schema",
    "stacktrace",
    "subtitles",
    "terraform_hcl",
    "terraform_plan",
    "text_hierarchy",
    "timeline_events",
    "toml_config",
    "transcript",
    "xml_feed",
    "yaml_manifest",
]

EXPECTED_STRATEGY_ALIASES = {
    "integrated": "integrated_naive",
    "naive": "integrated_naive",
    "book": "integrated_book",
    "law": "integrated_laws",
    "laws": "integrated_laws",
    "legal": "integrated_laws",
    "email": "integrated_email",
    "mail": "integrated_email",
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


def _run_python_snippet(snippet: str) -> dict[str, object]:
    env = {**os.environ, "PYTHONWARNINGS": "ignore::FutureWarning"}
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(snippet)],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )
    return json.loads(result.stdout.strip())


def test_chunker_factory_supported_strategy_names_are_stable() -> None:
    assert sorted(chunker_factory.SUPPORTED_STRATEGIES.keys()) == EXPECTED_SUPPORTED_STRATEGIES


def test_chunker_factory_alias_table_is_stable() -> None:
    assert chunker_factory.STRATEGY_ALIASES == EXPECTED_STRATEGY_ALIASES


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("integrated", "integrated_naive"),
        ("qa", "qa_pairs"),
        ("markdown", "markdown"),
        ("resume", "resume_structured"),
        ("docker-compose", "docker_compose"),
        ("layout_pdf", "pdf_layout"),
        ("tfplan", "terraform_plan"),
    ],
)
def test_chunker_factory_resolve_strategy_preserves_current_alias_behavior(alias: str, expected: str) -> None:
    assert chunker_factory.resolve_strategy(alias) == expected


def test_chunker_factory_uses_default_strategy_when_strategy_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.rag.chunking.factory.settings.DEFAULT_CHUNK_STRATEGY", "langchain_recursive", raising=False)
    assert chunker_factory.resolve_strategy(None) == "langchain_recursive"


def test_chunker_factory_rejects_unknown_strategy_with_supported_list() -> None:
    with pytest.raises(ValueError) as exc_info:
        chunker_factory.resolve_strategy("does-not-exist")

    expected_supported = EXPECTED_SUPPORTED_STRATEGIES + sorted(chunker_factory.INTEGRATED_PIPELINE_STRATEGIES)
    assert str(exc_info.value) == (
        "Unsupported chunk strategy 'does-not-exist'. "
        f"Supported strategies: {expected_supported}"
    )


def test_chunker_factory_rejects_disabled_llama_index_strategies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.rag.chunking.factory.settings.LLAMA_INDEX_ENABLED", False, raising=False)

    with pytest.raises(ValueError) as exc_info:
        chunker_factory.resolve_strategy("llama_index")

    assert str(exc_info.value) == "LlamaIndex chunker is disabled. Set LLAMA_INDEX_ENABLED=True to use it."


def test_chunker_factory_rejects_integrated_pipeline_with_current_guidance() -> None:
    with pytest.raises(ValueError) as exc_info:
        chunker_factory.get_chunker("integrated", chunk_size=1000, chunk_overlap=200)

    assert str(exc_info.value) == (
        "Chunk strategy 'integrated_naive' is handled by the integrated parse+chunk pipeline. "
        "Use 'chunk_file' from app.rag.chunking.integrated_pipeline.bridge instead."
    )


def test_importing_chunker_factory_does_not_load_strategy_modules_by_default() -> None:
    payload = _run_python_snippet(
        """
        import json
        import sys

        before = set(sys.modules)
        import app.rag.chunking.factory as factory  # noqa: F401
        after = set(sys.modules)
        added = sorted(name for name in after - before if name.startswith("app.rag.chunking.strategies"))
        print(json.dumps({"added": added}))
        """
    )

    assert payload == {"added": []}


def test_strategy_exports_remain_lazy_and_backward_compatible() -> None:
    payload = _run_python_snippet(
        """
        import json
        import sys

        before = set(sys.modules)
        import app.rag.chunking.strategies as strategies
        after_import = set(sys.modules)
        separator_cls = strategies.SeparatorChunker
        after_attr = set(sys.modules)
        print(
            json.dumps(
                {
                    "after_import": sorted(
                        name for name in after_import - before if name.startswith("app.rag.chunking.strategies")
                    ),
                    "after_attr": sorted(
                        name for name in after_attr - after_import if name.startswith("app.rag.chunking.strategies")
                    ),
                    "class_name": separator_cls.__name__,
                }
            )
        )
        """
    )

    assert payload == {
        "after_import": ["app.rag.chunking.strategies"],
        "after_attr": ["app.rag.chunking.strategies.separator"],
        "class_name": "SeparatorChunker",
    }


def test_supported_strategy_lookup_loads_only_requested_strategy_module() -> None:
    payload = _run_python_snippet(
        """
        import json
        import sys

        import app.rag.chunking.factory as factory

        before = set(sys.modules)
        chunker_cls = factory.chunker_factory.SUPPORTED_STRATEGIES["separator"]
        after = set(sys.modules)
        print(
            json.dumps(
                {
                    "added": sorted(name for name in after - before if name.startswith("app.rag.chunking.strategies")),
                    "class_name": chunker_cls.__name__,
                }
            )
        )
        """
    )

    assert payload == {
        "added": [
            "app.rag.chunking.strategies",
            "app.rag.chunking.strategies.separator",
        ],
        "class_name": "SeparatorChunker",
    }
