from langchain_core.documents import Document

from app.rag.chunking.strategies.asciidoc_sections import AsciiDocSectionsChunker
from app.rag.chunking.strategies.dockerfile import DockerfileChunker
from app.rag.chunking.strategies.html_sections import HTMLSectionsChunker
from app.rag.chunking.strategies.jira_ticket import JiraTicketChunker
from app.rag.chunking.strategies.latex_sections import LatexSectionsChunker
from app.rag.chunking.strategies.makefile import MakefileChunker
from app.rag.chunking.strategies.mediawiki_sections import MediaWikiSectionsChunker
from app.rag.chunking.strategies.nginx_config import NginxConfigChunker
from app.rag.chunking.strategies.orgmode_sections import OrgModeSectionsChunker
from app.rag.chunking.strategies.prd_spec import PRDSpecChunker
from app.rag.chunking.strategies.rst_sections import RSTSectionsChunker
from app.rag.chunking.strategies.sql_schema import SqlSchemaChunker
from app.rag.chunking.strategies.stacktrace import StackTraceChunker
from app.rag.chunking.strategies.toml_config import TOMLConfigChunker
from app.rag.chunking.strategies.yaml_manifest import YAMLManifestChunker


def _assert_offsets(text: str, chunks):
    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata or {}
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content


def test_markup_chunkers_preserve_offsets_and_heading_metadata():
    samples = [
        (
            "html_sections",
            HTMLSectionsChunker(chunk_size=160, chunk_overlap=40),
            "<html><body>\n<h1>Intro</h1>\n<p>" + ("a " * 80).strip() + "</p>\n<h2>Part A</h2>\n<p>" + ("b " * 80).strip() + "</p>\n</body></html>\n",
            "html_heading",
        ),
        (
            "rst_sections",
            RSTSectionsChunker(chunk_size=200, chunk_overlap=40),
            "Title\n=====\n\nSection One\n-----------\n" + ("x " * 80).strip() + "\n\nSection Two\n-----------\n" + ("y " * 80).strip() + "\n",
            "rst_heading",
        ),
        (
            "asciidoc_sections",
            AsciiDocSectionsChunker(chunk_size=200, chunk_overlap=40),
            "= Doc Title\n\n== One\n" + ("x " * 80).strip() + "\n\n== Two\n" + ("y " * 80).strip() + "\n",
            "asciidoc_heading",
        ),
        (
            "latex_sections",
            LatexSectionsChunker(chunk_size=220, chunk_overlap=40),
            "\\section{Intro}\n" + ("x " * 80).strip() + "\n\n\\subsection{Details}\n" + ("y " * 80).strip() + "\n",
            "latex_heading",
        ),
        (
            "orgmode_sections",
            OrgModeSectionsChunker(chunk_size=220, chunk_overlap=40),
            "* Intro\n" + ("x " * 80).strip() + "\n\n** Details\n" + ("y " * 80).strip() + "\n",
            "org_heading",
        ),
        (
            "mediawiki_sections",
            MediaWikiSectionsChunker(chunk_size=220, chunk_overlap=40),
            "== Intro ==\n" + ("x " * 80).strip() + "\n\n=== Details ===\n[[Link]]\n" + ("y " * 80).strip() + "\n",
            "wiki_heading",
        ),
    ]

    for strategy, chunker, text, meta_key in samples:
        chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])
        _assert_offsets(text, chunks)
        assert all((c.metadata or {}).get("chunk_strategy") == strategy for c in chunks)
        assert any((c.metadata or {}).get(meta_key) for c in chunks)


def test_yaml_toml_sql_and_stacktrace_chunkers_preserve_offsets_and_metadata():
    yaml_text = (
        "apiVersion: v1\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        "  name: cm1\n"
        "data:\n"
        "  a: b\n"
        "---\n"
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: dep1\n"
        "spec:\n"
        "  replicas: 2\n"
    )
    yaml_chunks = YAMLManifestChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=yaml_text, metadata={"file_type": "yaml"})]
    )
    _assert_offsets(yaml_text, yaml_chunks)
    assert any((c.metadata or {}).get("yaml_id") == "ConfigMap/cm1" for c in yaml_chunks)
    assert any((c.metadata or {}).get("yaml_id") == "Deployment/dep1" for c in yaml_chunks)

    toml_text = (
        "[tool.poetry]\n"
        "name = \"demo\"\n"
        "version = \"0.1.0\"\n\n"
        "[tool.poetry.dependencies]\n"
        "python = \"^3.11\"\n"
        "requests = \"^2.0\"\n"
    )
    toml_chunks = TOMLConfigChunker(chunk_size=200, chunk_overlap=40).split_documents(
        [Document(page_content=toml_text, metadata={"file_type": "toml"})]
    )
    _assert_offsets(toml_text, toml_chunks)
    keys = []
    for c in toml_chunks:
        keys.extend((c.metadata or {}).get("toml_keys") or [])
    assert "name" in keys or "version" in keys

    sql_text = (
        "CREATE TABLE users (\n"
        "  id INT PRIMARY KEY,\n"
        "  name TEXT\n"
        ");\n\n"
        "ALTER TABLE users ADD COLUMN email TEXT;\n"
    )
    sql_chunks = SqlSchemaChunker(chunk_size=200, chunk_overlap=40).split_documents(
        [Document(page_content=sql_text, metadata={"file_type": "sql"})]
    )
    _assert_offsets(sql_text, sql_chunks)
    assert any((c.metadata or {}).get("sql_stmt_type") for c in sql_chunks)

    trace_text = (
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1, in <module>\n"
        "    boom()\n"
        "  File \"x.py\", line 2, in boom\n"
        "    1/0\n"
        "ZeroDivisionError: division by zero\n"
    )
    trace_chunks = StackTraceChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=trace_text, metadata={"file_type": "txt"})]
    )
    _assert_offsets(trace_text, trace_chunks)
    assert any((c.metadata or {}).get("stacktrace_kind") == "python" for c in trace_chunks)
    assert any(int((c.metadata or {}).get("stacktrace_frame_count") or 0) >= 2 for c in trace_chunks)


def test_docker_make_nginx_chunkers_preserve_offsets_and_metadata():
    docker_text = (
        "FROM python:3.11-slim AS base\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        "RUN pip install -r requirements.txt\n\n"
        "FROM base AS final\n"
        "CMD [\"python\", \"main.py\"]\n"
    )
    docker_chunks = DockerfileChunker(chunk_size=180, chunk_overlap=40).split_documents(
        [Document(page_content=docker_text, metadata={"file_type": "txt"})]
    )
    _assert_offsets(docker_text, docker_chunks)
    assert any((c.metadata or {}).get("docker_from_image") for c in docker_chunks)

    make_text = ".PHONY: build test\nbuild:\n\t@echo build\n\ntest:\n\tpytest -q\n"
    make_chunks = MakefileChunker(chunk_size=160, chunk_overlap=40).split_documents(
        [Document(page_content=make_text, metadata={"file_type": "mk"})]
    )
    _assert_offsets(make_text, make_chunks)
    assert any((c.metadata or {}).get("make_targets") for c in make_chunks)

    nginx_text = (
        "http {\n"
        "  server {\n"
        "    listen 80;\n"
        "    server_name example.com;\n"
        "    location / {\n"
        "      proxy_pass http://localhost:8000;\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    nginx_chunks = NginxConfigChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=nginx_text, metadata={"file_type": "conf"})]
    )
    _assert_offsets(nginx_text, nginx_chunks)
    assert any((c.metadata or {}).get("nginx_block_kind") == "server" for c in nginx_chunks)
    assert any((c.metadata or {}).get("nginx_server_name") for c in nginx_chunks)


def test_jira_and_prd_chunkers_preserve_offsets_and_section_metadata():
    ticket_text = (
        "Summary: Login fails\n\n"
        "Description:\n"
        + ("x " * 60).strip()
        + "\n\n"
        "Steps to Reproduce:\n"
        "1. Open app\n"
        "2. Click login\n\n"
        "Expected Result:\n"
        "User logged in\n\n"
        "Actual Result:\n"
        "500 error\n\n"
        "Environment:\n"
        "OS: Windows\n"
    )
    ticket_chunks = JiraTicketChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=ticket_text, metadata={"file_type": "txt"})]
    )
    _assert_offsets(ticket_text, ticket_chunks)
    assert any((c.metadata or {}).get("ticket_section") for c in ticket_chunks)

    prd_text = (
        "# Background\n"
        + ("b " * 80).strip()
        + "\n\n"
        "# Goals\n"
        + ("g " * 80).strip()
        + "\n\n"
        "# Scope\n"
        + ("s " * 80).strip()
        + "\n\n"
        "# Requirements\n"
        + ("r " * 80).strip()
        + "\n\n"
        "# Acceptance Criteria\n"
        + ("a " * 80).strip()
        + "\n\n"
        "# Risks\n"
        + ("k " * 80).strip()
        + "\n"
    )
    prd_chunks = PRDSpecChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=prd_text, metadata={"file_type": "md"})]
    )
    _assert_offsets(prd_text, prd_chunks)
    assert any((c.metadata or {}).get("prd_section") for c in prd_chunks)

