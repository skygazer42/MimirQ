from langchain_core.documents import Document

from app.rag.chunking.strategies.api_reference import APIReferenceChunker
from app.rag.chunking.strategies.asciidoc_sections import AsciiDocSectionsChunker
from app.rag.chunking.strategies.html_sections import HTMLSectionsChunker
from app.rag.chunking.strategies.latex_sections import LatexSectionsChunker
from app.rag.chunking.strategies.markdown_frontmatter import MarkdownFrontmatterChunker
from app.rag.chunking.strategies.mediawiki_sections import MediaWikiSectionsChunker
from app.rag.chunking.strategies.nginx_config import NginxConfigChunker
from app.rag.chunking.strategies.orgmode_sections import OrgModeSectionsChunker
from app.rag.chunking.strategies.rst_sections import RSTSectionsChunker
from app.rag.chunking.strategies.spreadsheet_sheet import SpreadsheetSheetChunker


def _summarize_chunks(chunker, text: str) -> list[tuple[str, dict]]:
    docs = chunker.split_documents([Document(page_content=text, metadata={"source": "fixture"})])
    return [
        (
            doc.page_content,
            {key: value for key, value in doc.metadata.items() if key != "source"},
        )
        for doc in docs
    ]


def test_api_reference_chunker_characterizes_prefix_and_endpoint_metadata() -> None:
    text = (
        "Overview for operators.\n\n"
        "GET /api/v1/documents\n"
        "List uploaded documents.\n\n"
        "POST /api/v1/documents/upload\n"
        "Upload a new document.\n"
    )

    assert _summarize_chunks(APIReferenceChunker(10_000, 0), text) == [
        (
            "Overview for operators.",
            {
                "chunk_strategy": "api_reference",
                "start_char": 0,
                "end_char": 23,
                "endpoint_index": -1,
                "doc_type_kwd": "api",
                "chunk_index": 0,
            },
        ),
        (
            "GET /api/v1/documents\nList uploaded documents.",
            {
                "chunk_strategy": "api_reference",
                "start_char": 25,
                "end_char": 71,
                "doc_type_kwd": "api",
                "endpoint_index": 0,
                "http_method": "GET",
                "api_path": "/api/v1/documents",
                "endpoint_signature": "GET /api/v1/documents",
                "chunk_index": 1,
            },
        ),
        (
            "POST /api/v1/documents/upload\nUpload a new document.",
            {
                "chunk_strategy": "api_reference",
                "start_char": 73,
                "end_char": 125,
                "doc_type_kwd": "api",
                "endpoint_index": 1,
                "http_method": "POST",
                "api_path": "/api/v1/documents/upload",
                "endpoint_signature": "POST /api/v1/documents/upload",
                "chunk_index": 2,
            },
        ),
    ]


def test_section_chunkers_characterize_heading_metadata_and_paths() -> None:
    cases = [
        (
            AsciiDocSectionsChunker(10_000, 0),
            "Preface line.\n= Retrieval Guide\nIntro section.\n== Summary\nSummary body.\n",
            [
                (
                    "Preface line.",
                    {
                        "chunk_strategy": "asciidoc_sections",
                        "start_char": 0,
                        "end_char": 13,
                        "doc_type_kwd": "asciidoc",
                        "chunk_index": 0,
                    },
                ),
                (
                    "= Retrieval Guide\nIntro section.",
                    {
                        "chunk_strategy": "asciidoc_sections",
                        "start_char": 14,
                        "end_char": 46,
                        "doc_type_kwd": "asciidoc",
                        "asciidoc_heading": "Retrieval Guide",
                        "asciidoc_level": 1,
                        "asciidoc_path": ["Retrieval Guide"],
                        "asciidoc_path_str": "Retrieval Guide",
                        "chunk_index": 1,
                    },
                ),
                (
                    "== Summary\nSummary body.",
                    {
                        "chunk_strategy": "asciidoc_sections",
                        "start_char": 47,
                        "end_char": 71,
                        "doc_type_kwd": "asciidoc",
                        "asciidoc_heading": "Summary",
                        "asciidoc_level": 2,
                        "asciidoc_path": ["Retrieval Guide", "Summary"],
                        "asciidoc_path_str": "Retrieval Guide / Summary",
                        "chunk_index": 2,
                    },
                ),
            ],
        ),
        (
            HTMLSectionsChunker(10_000, 0),
            "<p>Intro.</p>\n<h1>Retrieval Guide</h1>\n<p>Overview.</p>\n<h2>Evidence</h2>\n<p>Body.</p>\n",
            [
                (
                    "<p>Intro.</p>",
                    {
                        "chunk_strategy": "html_sections",
                        "start_char": 0,
                        "end_char": 13,
                        "doc_type_kwd": "html",
                        "chunk_index": 0,
                    },
                ),
                (
                    "<h1>Retrieval Guide</h1>\n<p>Overview.</p>",
                    {
                        "chunk_strategy": "html_sections",
                        "start_char": 14,
                        "end_char": 55,
                        "doc_type_kwd": "html",
                        "html_heading": "Retrieval Guide",
                        "html_level": 1,
                        "html_path": ["Retrieval Guide"],
                        "html_path_str": "Retrieval Guide",
                        "chunk_index": 1,
                    },
                ),
                (
                    "<h2>Evidence</h2>\n<p>Body.</p>",
                    {
                        "chunk_strategy": "html_sections",
                        "start_char": 56,
                        "end_char": 86,
                        "doc_type_kwd": "html",
                        "html_heading": "Evidence",
                        "html_level": 2,
                        "html_path": ["Retrieval Guide", "Evidence"],
                        "html_path_str": "Retrieval Guide / Evidence",
                        "chunk_index": 2,
                    },
                ),
            ],
        ),
        (
            LatexSectionsChunker(10_000, 0),
            "Lead text.\n\\section{Intro}\nIntro body.\n\\subsection{Detail}\nDetail body.\n",
            [
                (
                    "Lead text.",
                    {
                        "chunk_strategy": "latex_sections",
                        "start_char": 0,
                        "end_char": 10,
                        "doc_type_kwd": "latex",
                        "chunk_index": 0,
                    },
                ),
                (
                    "\\section{Intro}\nIntro body.",
                    {
                        "chunk_strategy": "latex_sections",
                        "start_char": 11,
                        "end_char": 38,
                        "doc_type_kwd": "latex",
                        "latex_heading": "Intro",
                        "latex_level": 3,
                        "latex_cmd": "section",
                        "latex_path": ["Intro"],
                        "latex_path_str": "Intro",
                        "chunk_index": 1,
                    },
                ),
                (
                    "\\subsection{Detail}\nDetail body.",
                    {
                        "chunk_strategy": "latex_sections",
                        "start_char": 39,
                        "end_char": 71,
                        "doc_type_kwd": "latex",
                        "latex_heading": "Detail",
                        "latex_level": 4,
                        "latex_cmd": "subsection",
                        "latex_path": ["Intro", "Detail"],
                        "latex_path_str": "Intro / Detail",
                        "chunk_index": 2,
                    },
                ),
            ],
        ),
        (
            MediaWikiSectionsChunker(10_000, 0),
            "Lead line.\n== Retrieval ==\nOverview.\n=== Evidence ===\nDetail.\n",
            [
                (
                    "Lead line.",
                    {
                        "chunk_strategy": "mediawiki_sections",
                        "start_char": 0,
                        "end_char": 10,
                        "doc_type_kwd": "wiki",
                        "chunk_index": 0,
                    },
                ),
                (
                    "== Retrieval ==\nOverview.",
                    {
                        "chunk_strategy": "mediawiki_sections",
                        "start_char": 11,
                        "end_char": 36,
                        "doc_type_kwd": "wiki",
                        "wiki_heading": "Retrieval",
                        "wiki_level": 1,
                        "wiki_path": ["Retrieval"],
                        "wiki_path_str": "Retrieval",
                        "chunk_index": 1,
                    },
                ),
                (
                    "=== Evidence ===\nDetail.",
                    {
                        "chunk_strategy": "mediawiki_sections",
                        "start_char": 37,
                        "end_char": 61,
                        "doc_type_kwd": "wiki",
                        "wiki_heading": "Evidence",
                        "wiki_level": 2,
                        "wiki_path": ["Retrieval", "Evidence"],
                        "wiki_path_str": "Retrieval / Evidence",
                        "chunk_index": 2,
                    },
                ),
            ],
        ),
        (
            OrgModeSectionsChunker(10_000, 0),
            "#+TITLE: Notes\n* TODO Retrieval :tag:\nOverview.\n** Governance\nDetail.\n",
            [
                (
                    "#+TITLE: Notes",
                    {
                        "chunk_strategy": "orgmode_sections",
                        "start_char": 0,
                        "end_char": 14,
                        "doc_type_kwd": "org",
                        "chunk_index": 0,
                    },
                ),
                (
                    "* TODO Retrieval :tag:\nOverview.",
                    {
                        "chunk_strategy": "orgmode_sections",
                        "start_char": 15,
                        "end_char": 47,
                        "doc_type_kwd": "org",
                        "org_heading": "Retrieval",
                        "org_level": 1,
                        "org_path": ["Retrieval"],
                        "org_path_str": "Retrieval",
                        "chunk_index": 1,
                    },
                ),
                (
                    "** Governance\nDetail.",
                    {
                        "chunk_strategy": "orgmode_sections",
                        "start_char": 48,
                        "end_char": 69,
                        "doc_type_kwd": "org",
                        "org_heading": "Governance",
                        "org_level": 2,
                        "org_path": ["Retrieval", "Governance"],
                        "org_path_str": "Retrieval / Governance",
                        "chunk_index": 2,
                    },
                ),
            ],
        ),
        (
            RSTSectionsChunker(10_000, 0),
            "Lead line.\nGuide\n=====\nOverview.\nDetail\n------\nBody.\n",
            [
                (
                    "Lead line.",
                    {
                        "chunk_strategy": "rst_sections",
                        "start_char": 0,
                        "end_char": 10,
                        "doc_type_kwd": "rst",
                        "chunk_index": 0,
                    },
                ),
                (
                    "Guide\n=====\nOverview.",
                    {
                        "chunk_strategy": "rst_sections",
                        "start_char": 11,
                        "end_char": 32,
                        "doc_type_kwd": "rst",
                        "rst_heading": "Guide",
                        "rst_level": 1,
                        "rst_adorn": "=",
                        "rst_path": ["Guide"],
                        "rst_path_str": "Guide",
                        "chunk_index": 1,
                    },
                ),
                (
                    "Detail\n------\nBody.",
                    {
                        "chunk_strategy": "rst_sections",
                        "start_char": 33,
                        "end_char": 52,
                        "doc_type_kwd": "rst",
                        "rst_heading": "Detail",
                        "rst_level": 2,
                        "rst_adorn": "-",
                        "rst_path": ["Guide", "Detail"],
                        "rst_path_str": "Guide / Detail",
                        "chunk_index": 2,
                    },
                ),
            ],
        ),
    ]

    for chunker, text, expected in cases:
        assert _summarize_chunks(chunker, text) == expected


def test_markdown_frontmatter_chunker_characterizes_frontmatter_and_body_metadata() -> None:
    text = (
        "---\n"
        "title: Retrieval Review\n"
        "owner: mimirq\n"
        "---\n"
        "# Retrieval Review\n\n"
        "Body paragraph.\n"
    )

    assert _summarize_chunks(MarkdownFrontmatterChunker(10_000, 0), text) == [
        (
            "---\ntitle: Retrieval Review\nowner: mimirq\n---",
            {
                "chunk_strategy": "markdown_frontmatter",
                "start_char": 0,
                "end_char": 45,
                "markdown_frontmatter": True,
                "frontmatter_end_char": 46,
                "frontmatter_title": "Retrieval Review",
                "doc_type_kwd": "markdown",
                "chunk_index": 0,
            },
        ),
        (
            "# Retrieval Review\n\nBody paragraph.",
            {
                "chunk_strategy": "markdown_frontmatter",
                "start_char": 46,
                "end_char": 81,
                "frontmatter_present": True,
                "frontmatter_end_char": 46,
                "frontmatter_title": "Retrieval Review",
                "doc_type_kwd": "markdown",
                "chunk_index": 1,
            },
        ),
    ]


def test_nginx_config_chunker_characterizes_server_block_metadata() -> None:
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

    assert _summarize_chunks(NginxConfigChunker(10_000, 0), text) == [
        (
            "server {\n    listen 80;\n    server_name example.com;\n}",
            {
                "chunk_strategy": "nginx_config",
                "start_char": 7,
                "end_char": 61,
                "doc_type_kwd": "nginx",
                "nginx_block_kind": "server",
                "nginx_server_name": "example.com",
                "nginx_listen": "80",
                "chunk_index": 0,
            },
        ),
        (
            "server {\n    listen 443;\n    server_name secure.example.com;\n}",
            {
                "chunk_strategy": "nginx_config",
                "start_char": 62,
                "end_char": 124,
                "doc_type_kwd": "nginx",
                "nginx_block_kind": "server",
                "nginx_server_name": "secure.example.com",
                "nginx_listen": "443",
                "chunk_index": 1,
            },
        ),
    ]


def test_spreadsheet_sheet_chunker_characterizes_prefix_and_sheet_metadata() -> None:
    text = "Workbook note\n## Sheet: Q1\nA,B\n1,2\n## Sheet: Q2\nC,D\n3,4\n"

    assert _summarize_chunks(SpreadsheetSheetChunker(10_000, 0), text) == [
        (
            "Workbook note",
            {
                "chunk_strategy": "spreadsheet_sheet",
                "start_char": 0,
                "end_char": 13,
                "sheet_index": -1,
                "sheet_name": "_meta",
                "chunk_index": 0,
            },
        ),
        (
            "## Sheet: Q1\nA,B\n1,2",
            {
                "chunk_strategy": "spreadsheet_sheet",
                "start_char": 14,
                "end_char": 34,
                "sheet_index": 0,
                "sheet_name": "Q1",
                "chunk_index": 1,
            },
        ),
        (
            "## Sheet: Q2\nC,D\n3,4",
            {
                "chunk_strategy": "spreadsheet_sheet",
                "start_char": 35,
                "end_char": 55,
                "sheet_index": 1,
                "sheet_name": "Q2",
                "chunk_index": 2,
            },
        ),
    ]
