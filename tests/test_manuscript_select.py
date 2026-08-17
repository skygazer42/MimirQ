
import datetime as dt
from collections.abc import Iterable

import pytest
from langchain_core.documents import Document

import app.rag.chunking.strategies.manuscript as manuscript_module
from app.rag.chunking.strategies.manuscript import ManuscriptChunker

if not hasattr(dt, "UTC"):
    dt.UTC = dt.timezone.utc

_DETECTOR_NAMES = [
    "_looks_like_json",
    "_looks_like_markdown",
    "looks_like_ansible_playbook",
    "looks_like_api_reference",
    "looks_like_asciidoc",
    "looks_like_book",
    "looks_like_changelog",
    "looks_like_chat_history",
    "looks_like_csv_rows",
    "looks_like_diff_patch",
    "looks_like_docker_compose",
    "looks_like_dockerfile",
    "looks_like_email_thread",
    "looks_like_git_commit_log",
    "looks_like_github_actions_workflow",
    "looks_like_gitlab_ci",
    "looks_like_glossary",
    "looks_like_graphql_schema",
    "looks_like_html_sections",
    "looks_like_http_trace",
    "looks_like_jira_ticket",
    "looks_like_jsonl_records",
    "looks_like_junit_xml",
    "looks_like_kv_config",
    "looks_like_latex_sections",
    "looks_like_laws",
    "looks_like_log_events",
    "looks_like_makefile",
    "looks_like_markdown_frontmatter",
    "looks_like_markdown_table",
    "looks_like_maven_pom",
    "looks_like_mediawiki",
    "looks_like_meeting_minutes",
    "looks_like_nginx_config",
    "looks_like_openapi_spec",
    "looks_like_orgmode",
    "looks_like_outline",
    "looks_like_paper",
    "looks_like_postmortem_report",
    "looks_like_prd_spec",
    "looks_like_presentation",
    "looks_like_proto_schema",
    "looks_like_qa_markdown",
    "looks_like_qa_pairs",
    "looks_like_resume",
    "looks_like_rst_sections",
    "looks_like_sitemap_xml",
    "looks_like_sop",
    "looks_like_spreadsheet",
    "looks_like_sql_schema",
    "looks_like_stacktrace",
    "looks_like_subtitles",
    "looks_like_terraform_hcl",
    "looks_like_terraform_plan",
    "looks_like_timeline_events",
    "looks_like_toml_config",
    "looks_like_transcript",
    "looks_like_xml_feed",
    "looks_like_yaml_manifest",
]


def _doc(text: str = "fixture text", *, file_type: str = "") -> Document:
    metadata = {"source": "fixture"}
    if file_type:
        metadata["file_type"] = file_type
    return Document(page_content=text, metadata=metadata)


def _constant_detector(value: bool):
    def _detector(_text: str) -> bool:
        return value

    return _detector


def _stub_detectors(monkeypatch: pytest.MonkeyPatch, truthy: Iterable[str] = ()) -> None:
    active = set(truthy)
    for name in _DETECTOR_NAMES:
        monkeypatch.setattr(manuscript_module, name, _constant_detector(name in active))


def _assert_public_route(
    chunker: ManuscriptChunker,
    doc: Document,
    *,
    expected_selected: str,
) -> list[Document]:
    chunks = chunker.split_documents([doc])

    assert chunks
    assert all(chunk.page_content.strip() for chunk in chunks)
    assert {chunk.metadata["chunk_strategy_selected"] for chunk in chunks} == {expected_selected}
    assert {chunk.metadata["chunk_strategy_preset"] for chunk in chunks} == {"manuscript"}
    assert {chunk.metadata["source"] for chunk in chunks} == {"fixture"}
    return chunks


@pytest.mark.parametrize(
    ("file_type", "expected_selected"),
    [
        pytest.param("json", "json", id="json-file-type"),
        pytest.param("jsonl", "jsonl_records", id="jsonl-file-type"),
        pytest.param("ndjson", "jsonl_records", id="ndjson-file-type"),
        pytest.param("rss", "xml_feed", id="rss-file-type"),
        pytest.param("atom", "xml_feed", id="atom-file-type"),
        pytest.param("graphql", "graphql_schema", id="graphql-file-type"),
        pytest.param("gql", "graphql_schema", id="gql-file-type"),
        pytest.param("proto", "proto_schema", id="proto-file-type"),
        pytest.param("tf", "terraform_hcl", id="tf-file-type"),
        pytest.param("hcl", "terraform_hcl", id="hcl-file-type"),
        pytest.param("toml", "toml_config", id="toml-file-type"),
        pytest.param("sql", "sql_schema", id="sql-file-type"),
        pytest.param("mk", "makefile", id="mk-file-type"),
        pytest.param("rst", "rst_sections", id="rst-file-type"),
        pytest.param("adoc", "asciidoc_sections", id="adoc-file-type"),
        pytest.param("asciidoc", "asciidoc_sections", id="asciidoc-file-type"),
        pytest.param("tex", "latex_sections", id="tex-file-type"),
        pytest.param("latex", "latex_sections", id="latex-file-type"),
        pytest.param("org", "orgmode_sections", id="org-file-type"),
        pytest.param("markdown", "markdown_aware", id="markdown-file-type"),
    ],
)
def test_split_documents_exposes_file_type_driven_routes(
    monkeypatch: pytest.MonkeyPatch,
    file_type: str,
    expected_selected: str,
) -> None:
    _stub_detectors(monkeypatch)
    text = '{"items": [1, 2, 3]}' if file_type == "json" else "fixture text"

    _assert_public_route(
        ManuscriptChunker(chunk_size=80, chunk_overlap=9),
        _doc(text, file_type=file_type),
        expected_selected=expected_selected,
    )


@pytest.mark.parametrize(
    ("file_type", "truthy_detector", "expected_selected"),
    [
        pytest.param("csv", "looks_like_csv_rows", "csv_rows", id="csv-rows"),
        pytest.param("csv", "looks_like_markdown_table", "markdown_table", id="csv-table"),
        pytest.param("xlsx", "looks_like_spreadsheet", "spreadsheet_sheet", id="xlsx-sheet"),
        pytest.param("xlsx", "looks_like_markdown_table", "markdown_table", id="xlsx-table"),
        pytest.param("yaml", "looks_like_github_actions_workflow", "github_actions", id="gha"),
        pytest.param("yaml", "looks_like_docker_compose", "docker_compose", id="compose"),
        pytest.param("yaml", "looks_like_gitlab_ci", "gitlab_ci", id="gitlab"),
        pytest.param("yaml", "looks_like_ansible_playbook", "ansible_playbook", id="ansible"),
        pytest.param("yaml", None, "yaml_manifest", id="yaml-file-type"),
        pytest.param("yml", None, "yaml_manifest", id="yml-file-type"),
        pytest.param(
            "md",
            "looks_like_markdown_frontmatter",
            "markdown_frontmatter",
            id="md-frontmatter",
        ),
        pytest.param("md", None, "markdown_aware", id="md-markdown-aware"),
    ],
)
def test_split_documents_exposes_file_type_predicate_routes(
    monkeypatch: pytest.MonkeyPatch,
    file_type: str,
    truthy_detector: str | None,
    expected_selected: str,
) -> None:
    truthy = () if truthy_detector is None else (truthy_detector,)
    _stub_detectors(monkeypatch, truthy)

    _assert_public_route(
        ManuscriptChunker(chunk_size=80, chunk_overlap=9),
        _doc(file_type=file_type),
        expected_selected=expected_selected,
    )


@pytest.mark.parametrize(
    ("truthy_detector", "expected_selected"),
    [
        pytest.param("looks_like_maven_pom", "maven_pom", id="maven-pom"),
        pytest.param("looks_like_junit_xml", "junit_xml", id="junit-xml"),
        pytest.param("looks_like_sitemap_xml", "sitemap_xml", id="sitemap-xml"),
        pytest.param("looks_like_xml_feed", "xml_feed", id="xml-feed-heuristic"),
        pytest.param("looks_like_graphql_schema", "graphql_schema", id="graphql-heuristic"),
        pytest.param("looks_like_proto_schema", "proto_schema", id="proto-heuristic"),
        pytest.param("looks_like_terraform_hcl", "terraform_hcl", id="terraform-hcl"),
        pytest.param("looks_like_git_commit_log", "git_commit_log", id="git-commit-log"),
        pytest.param("looks_like_diff_patch", "diff_patch", id="diff-patch"),
        pytest.param("looks_like_subtitles", "subtitles", id="subtitles"),
        pytest.param("looks_like_log_events", "log_events", id="log-events"),
        pytest.param("looks_like_stacktrace", "stacktrace", id="stacktrace"),
        pytest.param("looks_like_http_trace", "http_trace", id="http-trace"),
        pytest.param("looks_like_terraform_plan", "terraform_plan", id="terraform-plan"),
        pytest.param("looks_like_openapi_spec", "openapi_spec", id="openapi"),
        pytest.param("looks_like_nginx_config", "nginx_config", id="nginx"),
        pytest.param("looks_like_dockerfile", "dockerfile", id="dockerfile"),
        pytest.param("looks_like_kv_config", "kv_config", id="kv-config"),
        pytest.param("looks_like_api_reference", "api_reference", id="api-reference"),
        pytest.param("looks_like_changelog", "changelog", id="changelog"),
        pytest.param("looks_like_email_thread", "email_thread", id="email-thread"),
        pytest.param("looks_like_chat_history", "chat_history", id="chat-history"),
        pytest.param("looks_like_jira_ticket", "jira_ticket", id="jira-ticket"),
        pytest.param("looks_like_postmortem_report", "postmortem_report", id="postmortem"),
        pytest.param("looks_like_qa_pairs", "qa_pairs", id="qa-pairs"),
        pytest.param("looks_like_qa_markdown", "qa_markdown", id="qa-markdown"),
        pytest.param("looks_like_sop", "sop_steps", id="sop"),
        pytest.param("looks_like_glossary", "glossary", id="glossary"),
        pytest.param("looks_like_meeting_minutes", "meeting_minutes", id="meeting-minutes"),
        pytest.param("looks_like_timeline_events", "timeline_events", id="timeline-events"),
        pytest.param("looks_like_prd_spec", "prd_spec", id="prd-spec"),
        pytest.param("looks_like_resume", "resume_structured", id="resume"),
        pytest.param("looks_like_presentation", "presentation_slides", id="presentation"),
        pytest.param("looks_like_laws", "laws_structured", id="laws"),
        pytest.param("looks_like_paper", "paper", id="paper"),
        pytest.param("looks_like_book", "book_structured", id="book"),
        pytest.param("looks_like_mediawiki", "mediawiki_sections", id="mediawiki"),
        pytest.param("looks_like_html_sections", "html_sections", id="html"),
        pytest.param("looks_like_outline", "outline", id="outline"),
        pytest.param("looks_like_transcript", "transcript", id="transcript"),
        pytest.param("looks_like_markdown_table", "markdown_table", id="markdown-table"),
        pytest.param("_looks_like_markdown", "markdown_aware", id="markdown-heuristic"),
    ],
)
def test_split_documents_exposes_heuristic_routes(
    monkeypatch: pytest.MonkeyPatch,
    truthy_detector: str,
    expected_selected: str,
) -> None:
    _stub_detectors(monkeypatch, [truthy_detector])

    _assert_public_route(
        ManuscriptChunker(chunk_size=80, chunk_overlap=9),
        _doc(),
        expected_selected=expected_selected,
    )


@pytest.mark.parametrize(
    ("file_type", "truthy_detectors", "expected_selected"),
    [
        pytest.param("", ("_looks_like_json", "looks_like_jsonl_records"), "json", id="json-before-jsonl"),
        pytest.param(
            "csv",
            ("looks_like_csv_rows", "looks_like_markdown_table"),
            "csv_rows",
            id="csv-rows-before-table",
        ),
        pytest.param(
            "",
            ("looks_like_openapi_spec", "looks_like_yaml_manifest"),
            "openapi_spec",
            id="openapi-before-yaml",
        ),
        pytest.param(
            "yaml",
            (
                "looks_like_github_actions_workflow",
                "looks_like_docker_compose",
                "looks_like_gitlab_ci",
                "looks_like_ansible_playbook",
                "looks_like_yaml_manifest",
            ),
            "github_actions",
            id="github-actions-before-other-yaml",
        ),
        pytest.param(
            "md",
            ("looks_like_markdown_table", "looks_like_markdown_frontmatter", "_looks_like_markdown"),
            "markdown_table",
            id="table-before-markdown",
        ),
    ],
)
def test_split_documents_keeps_core_precedence(
    monkeypatch: pytest.MonkeyPatch,
    file_type: str,
    truthy_detectors: tuple[str, ...],
    expected_selected: str,
) -> None:
    _stub_detectors(monkeypatch, truthy_detectors)

    _assert_public_route(
        ManuscriptChunker(chunk_size=80, chunk_overlap=9),
        _doc(file_type=file_type),
        expected_selected=expected_selected,
    )


def test_split_documents_prefers_nginx_when_config_detectors_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_detectors(monkeypatch, ("looks_like_nginx_config", "looks_like_kv_config"))
    text = (
        "# meta\n"
        "server {\n"
        "    listen 80;\n"
        "    server_name example.com;\n"
        "}\n"
        "server {\n"
        "    listen 443;\n"
        "    server_name secure.example.com;\n"
        "}\n"
    )

    chunks = _assert_public_route(
        ManuscriptChunker(chunk_size=500, chunk_overlap=0),
        _doc(text),
        expected_selected="nginx_config",
    )

    assert [chunk.metadata["nginx_server_name"] for chunk in chunks] == ["example.com", "secure.example.com"]
    assert all(chunk.metadata["doc_type_kwd"] == "nginx" for chunk in chunks)


def test_split_documents_prefers_resume_when_longform_detectors_collide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_detectors(monkeypatch, ("looks_like_resume", "looks_like_presentation", "looks_like_laws"))
    text = (
        "Jane Doe\n"
        "jane@example.com | github.com/janedoe\n"
        "Summary\n"
        "Pragmatic engineer with retrieval, ingestion, ranking, and production support experience.\n"
        "Experience\n"
        "Built and operated internal RAG systems across document, search, and evaluation pipelines.\n"
        "Languages\n"
        "English, Mandarin, Japanese\n"
    )

    chunks = _assert_public_route(
        ManuscriptChunker(chunk_size=500, chunk_overlap=0),
        _doc(text),
        expected_selected="resume_structured",
    )

    languages_chunk = next(chunk for chunk in chunks if chunk.metadata.get("resume_section") == "languages")
    assert languages_chunk.metadata["resume_section_title"] == "Languages"


def test_split_documents_prefers_presentation_before_laws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_detectors(monkeypatch, ("looks_like_presentation", "looks_like_laws"))
    text = (
        "# Overview\n"
        "A concise opening slide with enough explanatory content for a realistic deck fixture.\n"
        "---\n"
        "# Evidence\n"
        "The second slide summarizes retrieval quality, ranking behavior, and evaluation results.\n"
        "---\n"
        "# Decision\n"
        "The final slide records the selected rollout plan and its operational constraints.\n"
    )

    chunks = _assert_public_route(
        ManuscriptChunker(chunk_size=500, chunk_overlap=0),
        _doc(text),
        expected_selected="presentation_slides",
    )

    assert [chunk.metadata["slide_index"] for chunk in chunks] == [0, 1, 2]
    assert [chunk.metadata["slide_title"] for chunk in chunks] == ["Overview", "Evidence", "Decision"]


def test_split_documents_prefers_outline_before_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_detectors(monkeypatch, ("looks_like_outline", "_looks_like_markdown"))
    text = (
        "# Manual\n"
        "This introduction establishes context before the numbered sections.\n"
        "1. Start\n"
        "Body paragraph.\n"
        "1.1 Detail\n"
        "Nested paragraph.\n"
        "2. End\n"
        "Final paragraph.\n"
    )

    chunks = _assert_public_route(
        ManuscriptChunker(chunk_size=500, chunk_overlap=0),
        _doc(text),
        expected_selected="outline",
    )

    detail = next(chunk for chunk in chunks if chunk.metadata.get("outline_heading") == "1.1 Detail")
    assert detail.metadata["outline_path"] == ["1. Start", "1.1 Detail"]


def test_split_documents_prefers_transcript_before_semantic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_detectors(monkeypatch, ("looks_like_transcript",))
    detail = "context evidence decision follow-up " * 15
    text = f"Host: {detail}\nGuest: {detail}\nHost: {detail}\n"
    chunker = ManuscriptChunker(chunk_size=200, chunk_overlap=0)
    assert len(text) >= max(chunker.chunk_size * 2, 1200)

    chunks = _assert_public_route(chunker, _doc(text), expected_selected="transcript")

    assert {speaker for chunk in chunks for speaker in chunk.metadata["speakers"]} == {"Host", "Guest"}


def test_split_documents_uses_semantic_sentence_for_long_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_detectors(monkeypatch)
    text = "Long plain prose without structure. " * 50

    _assert_public_route(
        ManuscriptChunker(chunk_size=80, chunk_overlap=9),
        _doc(text),
        expected_selected="semantic_sentence",
    )


def test_split_documents_preserves_resume_languages_metadata_and_selection() -> None:
    text = (
        "Jane Doe\n"
        "jane@example.com | github.com/janedoe\n"
        "Summary\n"
        "Pragmatic engineer with retrieval, ingestion, ranking, and production support experience. " * 2 + "\n"
        "Experience\n"
        "Built and operated internal RAG systems across document, search, and evaluation pipelines. " * 2 + "\n"
        "Languages\n"
        "English, Mandarin, Japanese\n"
    )

    chunks = ManuscriptChunker(chunk_size=500, chunk_overlap=0).split_documents([_doc(text)])

    languages_chunk = next(chunk for chunk in chunks if chunk.metadata.get("resume_section") == "languages")
    assert languages_chunk.metadata["resume_section_title"] == "Languages"
    assert languages_chunk.metadata["chunk_strategy_selected"] == "resume_structured"
    assert languages_chunk.metadata["chunk_strategy_preset"] == "manuscript"


def test_split_documents_preserves_law_heading_metadata_and_order() -> None:
    text = (
        "General Provisions\n"
        "Article 1 Scope\n"
        "This regulation applies to controlled testing environments and compliance reviews.\n"
        "Section 1.1 Evidence Preservation\n"
        "Records shall retain their hierarchy and numbering across every chunk.\n"
        "Article 2 Definitions\n"
        "Key terms are defined below for operators and reviewers.\n"
    )

    chunks = ManuscriptChunker(chunk_size=96, chunk_overlap=0).split_documents([_doc(text)])
    selected = [chunk.metadata["chunk_strategy_selected"] for chunk in chunks]

    assert selected == ["laws_structured"] * 6
    assert [chunk.metadata["chunk_strategy_preset"] for chunk in chunks] == ["manuscript"] * 6

    first_article = next(chunk for chunk in chunks if chunk.metadata.get("law_heading") == "Article 1 Scope")
    section_chunk = next(
        chunk for chunk in chunks if chunk.metadata.get("law_heading") == "Section 1.1 Evidence Preservation"
    )
    second_article = next(chunk for chunk in chunks if chunk.metadata.get("law_heading") == "Article 2 Definitions")

    assert first_article.metadata["law_kind"] == "article"
    assert first_article.metadata["law_number"] == "1"
    assert first_article.metadata["law_article"] == "Article 1 Scope"
    assert first_article.metadata["law_path"] == ["Article 1 Scope"]
    assert section_chunk.metadata["law_kind"] == "section"
    assert section_chunk.metadata["law_number"] == "1.1"
    assert section_chunk.metadata["law_path"] == ["Section 1.1 Evidence Preservation"]
    assert second_article.metadata["law_kind"] == "article"
    assert second_article.metadata["law_number"] == "2"
    assert second_article.metadata["law_path"] == ["Section 1.1 Evidence Preservation", "Article 2 Definitions"]


def test_split_documents_preserves_markdown_table_metadata() -> None:
    text = (
        "Lead in\n"
        "Context paragraph that keeps the sample long enough for markdown table detection.\n"
        "Another line ensures the heuristic sees a table-oriented document.\n\n"
        "| Col A | Col B |\n"
        "| --- | --- |\n"
        "| alpha | one |\n"
        "| beta | two |\n"
        "| gamma | three |\n"
        "Tail text that preserves the trailing narrative after the table block.\n"
    )

    chunks = ManuscriptChunker(chunk_size=52, chunk_overlap=0).split_documents([_doc(text, file_type="csv")])
    table_chunks = [chunk for chunk in chunks if chunk.metadata.get("doc_type_kwd") == "table"]

    assert [chunk.page_content for chunk in table_chunks] == [
        "| Col A | Col B |\n| --- | --- |\n| alpha | one |\n",
        "| beta | two |\n| gamma | three |\n",
    ]
    assert all(chunk.metadata["chunk_strategy_selected"] == "markdown_table" for chunk in table_chunks)
    assert all(chunk.metadata["chunk_strategy_preset"] == "manuscript" for chunk in table_chunks)
    assert table_chunks[0].metadata["table_header"] == "| Col A | Col B |\n| --- | --- |\n"
    assert table_chunks[0].metadata["table_row_start_index"] == 0
    assert table_chunks[1].metadata["table_row_start_index"] == 1
    assert table_chunks[1].metadata["table_row_end_index"] == 2


def test_split_documents_preserves_markdown_list_and_heading_metadata() -> None:
    text = "# Tasks\n- first\n  continuation\n\n  more\n- second\nend\n"

    chunks = ManuscriptChunker(chunk_size=80, chunk_overlap=10).split_documents([_doc(text, file_type="md")])

    assert [(chunk.page_content, chunk.metadata["chunk_strategy_selected"]) for chunk in chunks] == [
        (text.rstrip(), "markdown_aware")
    ]
    assert chunks[0].metadata["chunk_strategy_preset"] == "manuscript"
    assert chunks[0].metadata["header_context"] == "# Tasks"
    assert chunks[0].metadata["header_path"] == "# Tasks"


def test_split_documents_preserves_latex_heading_metadata_for_math_content() -> None:
    text = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Method}\n"
        "We define the score as $E = mc^2$ and track its derivation carefully.\n"
        "\\subsection{Derivation}\n"
        "The proof proceeds by bounding the objective and normalizing each term.\n"
        "\\end{document}\n"
    )

    chunks = ManuscriptChunker(chunk_size=500, chunk_overlap=0).split_documents([_doc(text, file_type="tex")])

    assert [chunk.metadata["chunk_strategy_selected"] for chunk in chunks] == [
        "latex_sections",
        "latex_sections",
        "latex_sections",
    ]
    method_chunk, derivation_chunk = chunks[1], chunks[2]
    assert method_chunk.metadata["latex_heading"] == "Method"
    assert method_chunk.metadata["latex_path"] == ["Method"]
    assert derivation_chunk.metadata["latex_heading"] == "Derivation"
    assert derivation_chunk.metadata["latex_path"] == ["Method", "Derivation"]
    assert all(chunk.metadata["chunk_strategy_preset"] == "manuscript" for chunk in chunks)


def test_split_documents_preserves_recursive_fallback_overlap() -> None:
    text = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu " * 6).strip()

    chunks = ManuscriptChunker(chunk_size=80, chunk_overlap=10).split_documents([_doc(text)])

    assert len(chunks) > 1
    assert all(chunk.metadata["chunk_strategy_selected"] == "langchain_recursive" for chunk in chunks)
    assert all(chunk.metadata["chunk_strategy_preset"] == "manuscript" for chunk in chunks)
    assert chunks[1].metadata["start_char"] < chunks[0].metadata["end_char"]
