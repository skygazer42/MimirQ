from langchain_core.documents import Document

from app.rag.chunking.strategies.auto import AutoChunker


def test_auto_chunker_selects_markdown_for_markdownish_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    docs = [Document(page_content="# Title\n\nHello world.\n", metadata={"file_type": "md"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "markdown_aware"


def test_auto_chunker_selects_json_for_json_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    docs = [Document(page_content='{"a": 1, "b": 2}', metadata={"file_type": "json"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "json"


def test_auto_chunker_selects_semantic_for_long_plain_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = ("hello world. " * 200).strip()
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "semantic_sentence"


def test_auto_chunker_selects_qa_pairs_for_qa_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = (
        "Q: What is RAG?\n"
        "A: Retrieval-Augmented Generation.\n\n"
        "Q: Why chunk?\n"
        "A: Better retrieval.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "qa_pairs"


def test_auto_chunker_selects_transcript_for_dialogue_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = (
        "Host: Hello everyone.\n"
        "Guest: Thanks.\n"
        "Host: Let's begin.\n"
        "Guest: Sure.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "transcript"


def test_auto_chunker_selects_paper_for_paper_like_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = (
        "Abstract\n"
        + ("a" * 420)
        + "\nIntroduction\n"
        + ("b" * 420)
        + "\nReferences\n"
        + ("c" * 80)
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "paper"


def test_auto_chunker_selects_outline_for_numbered_outline_text():
    chunker = AutoChunker(chunk_size=200, chunk_overlap=50)
    text = (
        "1. Chapter One\n"
        "This is some content under chapter one.\n\n"
        "2. Chapter Two\n"
        "This is some content under chapter two.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "outline"


def test_auto_chunker_selects_email_thread_for_email_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "From: Alice <a@example.com>\n"
        "To: Bob <b@example.com>\n"
        "Subject: Re: Hello\n"
        "Date: Mon, 1 Jan 2024 10:00:00 +0000\n"
        "\n"
        "Hi Bob,\n"
        "Here is the update: " + ("x" * 80) + "\n"
        "\n"
        "-----Original Message-----\n"
        "From: Bob <b@example.com>\n"
        "To: Alice <a@example.com>\n"
        "Subject: Hello\n"
        "Date: Mon, 1 Jan 2024 09:00:00 +0000\n"
        "\n"
        "Hi Alice,\n"
        "Thanks! " + ("y" * 60) + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "email_thread"


def test_auto_chunker_selects_sop_steps_for_procedure_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "操作步骤如下：\n"
        "步骤一：打开应用。" + ("a" * 90) + "\n"
        "步骤二：登录账号。" + ("b" * 90) + "\n"
        "步骤三：完成设置。" + ("c" * 90) + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "sop_steps"


def test_auto_chunker_selects_glossary_for_glossary_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "RAG: Retrieval-Augmented Generation " + ("r" * 40) + "\n"
        "LLM: Large Language Model " + ("l" * 40) + "\n"
        "Embedding: Vector representation " + ("e" * 40) + "\n"
        "Chunk: A piece of text " + ("c" * 40) + "\n"
        "Retriever: Fetches relevant chunks " + ("t" * 40) + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "glossary"


def test_auto_chunker_selects_laws_for_laws_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "第一章 总则\n"
        "第一条【目的】" + ("法" * 120) + "\n"
        "第二条【适用范围】" + ("规" * 120) + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "laws_structured"


def test_auto_chunker_selects_book_for_book_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "Part I: Getting Started\n"
        "Chapter 1: Intro\n"
        + ("x" * 120)
        + "\n"
        "Chapter 2: Basics\n"
        + ("y" * 120)
        + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "book_structured"


def test_auto_chunker_selects_chat_history_for_timestamped_chat():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "[2024-01-01 10:00] Alice: " + ("hello " * 12).strip() + "\n"
        "[2024-01-01 10:01] Bob: " + ("hi " * 12).strip() + "\n"
        "[2024-01-01 10:02] Alice: " + ("update " * 12).strip() + "\n"
        "[2024-01-01 10:03] Bob: " + ("thanks " * 12).strip() + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "chat_history"


def test_auto_chunker_selects_resume_for_resume_like_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "# Education\n"
        + ("University of Example. " * 12)
        + "\n"
        "# Work Experience\n"
        + ("Example Corp. " * 12)
        + "\n"
        "# Skills\n"
        + ("Python, RAG, FastAPI. " * 12)
        + "\n"
        "Email: alice@example.com\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "md"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "resume_structured"


def test_auto_chunker_selects_presentation_for_slide_like_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "# Slide 1\n"
        + ("intro " * 25).strip()
        + "\n"
        "---\n"
        "# Slide 2\n"
        + ("agenda " * 25).strip()
        + "\n"
        "---\n"
        "# Slide 3\n"
        + ("results " * 25).strip()
        + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "md"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "presentation_slides"


def test_auto_chunker_selects_csv_rows_for_csv_parser_output():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "CSV: demo.csv\n"
        "Delimiter: ','\n"
        "Columns: name, age, note\n\n"
        "row 1: name=Alice | age=30 | note=" + ("a" * 60) + "\n"
        "row 2: name=Bob | age=31 | note=" + ("b" * 60) + "\n"
        "row 3: name=Carol | age=29 | note=" + ("c" * 60) + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "csv"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "csv_rows"


def test_auto_chunker_selects_spreadsheet_sheet_for_excel_parser_output():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "Excel: demo.xlsx\n"
        "Sheets: Sheet1, Sheet2\n\n"
        "## Sheet: Sheet1\n\n"
        "| A | B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n\n"
        "## Sheet: Sheet2\n\n"
        "| X | Y |\n"
        "| --- | --- |\n"
        "| a | b |\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "xlsx"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "spreadsheet_sheet"


def test_auto_chunker_selects_markdown_table_for_table_heavy_markdown():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "# Table Demo\n\n"
        "| Name | Score |\n"
        "| --- | --- |\n"
        "| Alice | 90 |\n"
        "| Bob | 85 |\n"
        "| Carol | 95 |\n\n"
        + ("tail " * 30).strip()
        + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "md"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "markdown_table"


def test_auto_chunker_selects_diff_patch_for_diff_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "diff --git a/foo.txt b/foo.txt\n"
        "index 1111111..2222222 100644\n"
        "--- a/foo.txt\n"
        "+++ b/foo.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "-old\n"
        "+new\n"
        "@@ -4,1 +4,1 @@\n"
        "-old2\n"
        "+new2\n"
        "diff --git a/bar.txt b/bar.txt\n"
        "index 3333333..4444444 100644\n"
        "--- a/bar.txt\n"
        "+++ b/bar.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-x\n"
        "+y\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "diff_patch"


def test_auto_chunker_selects_subtitles_for_srt_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "1\n"
        "00:00:01,000 --> 00:00:02,000\n"
        "Hello.\n\n"
        "2\n"
        "00:00:03,000 --> 00:00:04,000\n"
        "World.\n\n"
        "3\n"
        "00:00:05,000 --> 00:00:06,000\n"
        "Again.\n\n"
        "4\n"
        "00:00:07,000 --> 00:00:08,000\n"
        "Done.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "subtitles"


def test_auto_chunker_selects_log_events_for_log_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "2024-01-01 10:00:00,123 INFO service: started\n"
        "2024-01-01 10:00:01,456 WARN service: warming up\n"
        "2024-01-01 10:00:02,789 ERROR service: failed\n"
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1, in <module>\n"
        "    boom()\n"
        "2024-01-01 10:00:03,000 INFO service: recovered\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "log_events"


def test_auto_chunker_selects_kv_config_for_env_like_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "# Example config\n"
        "DATABASE_URL=postgresql://localhost:5432/db\n"
        "API_KEY=secret\n"
        "DEBUG=true\n"
        "TIMEOUT_SEC=30\n"
        "RETRY_MAX=2\n"
        "RERANKER_TOP_N=20\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "kv_config"


def test_auto_chunker_selects_api_reference_for_endpoint_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "# API\n\n"
        "GET /health\n"
        + ("Returns ok. " * 12).strip()
        + "\n\n"
        "POST /api/v1/items\n"
        + ("Creates item. " * 12).strip()
        + "\n\n"
        "DELETE /api/v1/items/{id}\n"
        + ("Deletes item. " * 12).strip()
        + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "md"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "api_reference"


def test_auto_chunker_selects_changelog_for_changelog_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "# Changelog\n\n"
        "## [1.0.0] - 2024-01-01\n"
        + ("Added feature. " * 15).strip()
        + "\n\n"
        "## [0.9.0] - 2023-12-01\n"
        + ("Fixed bug. " * 15).strip()
        + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "md"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "changelog"


def test_auto_chunker_selects_qa_markdown_for_markdown_qa_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "- **Q:** What is RAG?\n"
        "- **A:** Retrieval-Augmented Generation.\n\n"
        "- **Q:** Why chunk?\n"
        "- **A:** Better retrieval.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "md"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "qa_markdown"


def test_auto_chunker_selects_meeting_minutes_for_minutes_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "Meeting Notes\n\n"
        "Agenda:\n"
        "- Review progress\n"
        "- Discuss risks\n\n"
        "Action Items:\n"
        "- Alice: update docs\n"
        "- Bob: run tests\n\n"
        "Decisions:\n"
        "- Ship on Friday\n"
        + ("notes " * 40).strip()
        + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "meeting_minutes"


def test_auto_chunker_selects_timeline_events_for_timeline_text():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "2024-01-01 - Kickoff\n"
        + ("A " * 60).strip()
        + "\n"
        "2024-01-02 - Planning\n"
        + ("B " * 60).strip()
        + "\n"
        "2024-01-03 - Execution\n"
        + ("C " * 60).strip()
        + "\n"
        "2024-01-04 - Wrap up\n"
        + ("D " * 60).strip()
        + "\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_auto") is True
    assert chunks[0].metadata.get("chunk_strategy_selected") == "timeline_events"


def test_auto_chunker_selects_config_and_code_formats():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    cases = [
        (
            "yaml_manifest",
            "yaml",
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cm1\n---\napiVersion: v1\nkind: Service\nmetadata:\n  name: svc1\n",
        ),
        (
            "toml_config",
            "toml",
            "[tool.poetry]\nname = \"demo\"\nversion = \"0.1.0\"\n\n[tool.poetry.dependencies]\npython = \"^3.11\"\n",
        ),
        (
            "sql_schema",
            "sql",
            "CREATE TABLE users (\n  id INT PRIMARY KEY,\n  name TEXT\n);\n\nALTER TABLE users ADD COLUMN email TEXT;\n",
        ),
        (
            "nginx_config",
            "conf",
            "server {\n  listen 80;\n  server_name example.com;\n  location / { proxy_pass http://localhost:8000; }\n}\n",
        ),
        (
            "dockerfile",
            "txt",
            "FROM python:3.11-slim\nWORKDIR /app\nCOPY . .\nRUN echo hi\n",
        ),
        (
            "makefile",
            "mk",
            ".PHONY: build test\nbuild:\n\t@echo build\n\ntest:\n\tpytest -q\n",
        ),
        (
            "stacktrace",
            "txt",
            "Traceback (most recent call last):\n  File \"x.py\", line 1, in <module>\n    boom()\nZeroDivisionError: division by zero\n",
        ),
    ]

    for expected, file_type, text in cases:
        docs = [Document(page_content=text, metadata={"file_type": file_type})]
        chunks = chunker.split_documents(docs)
        assert chunks
        assert chunks[0].metadata.get("chunk_strategy_auto") is True
        assert chunks[0].metadata.get("chunk_strategy_selected") == expected


def test_auto_chunker_selects_ticket_and_prd_formats():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    cases = [
        (
            "jira_ticket",
            "txt",
            "Summary: Login fails\n\nDescription:\nSomething is wrong.\n\nSteps to Reproduce:\n1. Open app\n2. Click login\n\nExpected Result:\nSuccess\n\nActual Result:\n500\n",
        ),
        (
            "prd_spec",
            "md",
            "# Background\nx\n\n# Goals\ny\n\n# Scope\nz\n\n# Requirements\nr\n\n# Acceptance Criteria\na\n\n# Risks\nk\n",
        ),
    ]
    for expected, file_type, text in cases:
        docs = [Document(page_content=text, metadata={"file_type": file_type})]
        chunks = chunker.split_documents(docs)
        assert chunks
        assert chunks[0].metadata.get("chunk_strategy_auto") is True
        assert chunks[0].metadata.get("chunk_strategy_selected") == expected


def test_auto_chunker_selects_markup_formats():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    cases = [
        (
            "rst_sections",
            "rst",
            "Title\n=====\n\nSection One\n-----------\nhello\n\nSection Two\n-----------\nworld\n",
        ),
        (
            "asciidoc_sections",
            "adoc",
            "= Doc Title\n\n== One\nhello\n\n== Two\nworld\n",
        ),
        (
            "latex_sections",
            "tex",
            "\\section{Intro}\nhello\n\n\\subsection{Details}\nworld\n",
        ),
        (
            "orgmode_sections",
            "org",
            "* Intro\nhello\n\n** Details\nworld\n",
        ),
        (
            "mediawiki_sections",
            "txt",
            "== Intro ==\nhello\n\n=== Details ===\n[[Link]]\nworld\n",
        ),
        (
            "html_sections",
            "html",
            "<html><body><h1>Intro</h1><p>hello</p><h2>Details</h2><p>world</p></body></html>\n",
        ),
    ]
    for expected, file_type, text in cases:
        docs = [Document(page_content=text, metadata={"file_type": file_type})]
        chunks = chunker.split_documents(docs)
        assert chunks
        assert chunks[0].metadata.get("chunk_strategy_auto") is True
        assert chunks[0].metadata.get("chunk_strategy_selected") == expected


def test_auto_chunker_selects_openapi_spec_for_openapi_yaml():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "openapi: 3.0.0\n"
        "info:\n"
        "  title: Demo\n"
        "paths:\n"
        "  /health:\n"
        "    get:\n"
        "      responses:\n"
        "        '200':\n"
        "          description: ok\n"
        "  /items:\n"
        "    post:\n"
        "      responses:\n"
        "        '201':\n"
        "          description: created\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "yaml"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "openapi_spec"


def test_auto_chunker_selects_github_actions_for_workflow_yaml():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "yaml"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "github_actions"


def test_auto_chunker_selects_docker_compose_for_compose_yaml():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "version: \"3.9\"\n"
        "services:\n"
        "  web:\n"
        "    image: nginx:latest\n"
        "  api:\n"
        "    build: .\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "yaml"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "docker_compose"


def test_auto_chunker_selects_gitlab_ci_for_gitlab_ci_yaml():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "stages:\n"
        "  - build\n\n"
        "build_job:\n"
        "  script:\n"
        "    - echo build\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "yml"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "gitlab_ci"


def test_auto_chunker_selects_ansible_playbook_for_playbook_yaml():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "---\n"
        "- name: Setup\n"
        "  hosts: all\n"
        "  tasks:\n"
        "    - name: Ping\n"
        "      ping:\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "yaml"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "ansible_playbook"


def test_auto_chunker_selects_markdown_frontmatter_for_frontmatter_md():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "---\n"
        "title: Demo\n"
        "---\n\n"
        "# Heading\n"
        "Hello.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "md"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "markdown_frontmatter"


def test_auto_chunker_selects_junit_xml_for_junit_report():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "<testsuite name=\"demo\">\n"
        "  <testcase classname=\"a\" name=\"t1\"/>\n"
        "  <testcase classname=\"a\" name=\"t2\"/>\n"
        "</testsuite>\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "xml"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "junit_xml"


def test_auto_chunker_selects_sitemap_xml_for_sitemap():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "<urlset>\n"
        "  <url><loc>https://example.com/</loc></url>\n"
        "  <url><loc>https://example.com/a</loc></url>\n"
        "</urlset>\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "xml"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "sitemap_xml"


def test_auto_chunker_selects_maven_pom_for_pom_xml():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "<project>\n"
        "  <modelVersion>4.0.0</modelVersion>\n"
        "  <dependencies>\n"
        "    <dependency><groupId>a</groupId><artifactId>b</artifactId></dependency>\n"
        "    <dependency><groupId>c</groupId><artifactId>d</artifactId></dependency>\n"
        "  </dependencies>\n"
        "</project>\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "xml"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "maven_pom"


def test_auto_chunker_selects_http_trace_for_http_logs():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "> GET /health HTTP/1.1\n"
        "> Host: example.com\n"
        ">\n"
        "< HTTP/1.1 200 OK\n"
        "< Content-Type: text/plain\n"
        "<\n"
        "ok\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "log"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "http_trace"


def test_auto_chunker_selects_terraform_plan_for_plan_output():
    chunker = AutoChunker(chunk_size=240, chunk_overlap=40)
    text = (
        "Terraform will perform the following actions:\n\n"
        "  # aws_s3_bucket.b will be created\n"
        "  + resource \"aws_s3_bucket\" \"b\" {}\n"
        "Plan: 1 to add, 0 to change, 0 to destroy.\n"
    )
    docs = [Document(page_content=text, metadata={"file_type": "txt"})]
    chunks = chunker.split_documents(docs)
    assert chunks
    assert chunks[0].metadata.get("chunk_strategy_selected") == "terraform_plan"

