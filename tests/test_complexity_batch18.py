from typing import Any

from langchain_core.documents import Document

from app.rag.chunking.roles import classify_chunk_semantic_role
from app.rag.chunking.strategies.book_structured import BookStructuredChunker
from app.rag.chunking.strategies.chat_history import ChatHistoryChunker
from app.rag.chunking.strategies.docker_compose import DockerComposeChunker
from app.rag.chunking.strategies.dockerfile import DockerfileChunker
from app.rag.chunking.strategies.email_thread import EmailThreadChunker
from app.rag.chunking.strategies.git_commit_log import GitCommitLogChunker
from app.rag.chunking.strategies.github_actions import GitHubActionsChunker
from app.rag.chunking.strategies.glossary import GlossaryChunker


def _summarize_chunks(chunker: Any, text: str) -> list[tuple[str, dict[str, Any]]]:
    docs = chunker.split_documents([Document(page_content=text, metadata={"source": "fixture"})])
    return [
        (
            doc.page_content,
            {key: value for key, value in doc.metadata.items() if key != "source"},
        )
        for doc in docs
    ]


def test_classify_chunk_semantic_role_characterizes_existing_values_and_precedence() -> None:
    assert classify_chunk_semantic_role(content="x", meta={"chunk_semantic_role": "TABLE"}) == "table"
    assert (
        classify_chunk_semantic_role(
            content="1. step one\n2. step two",
            meta={"header_path": "FAQ / Install", "chunk_strategy": "glossary"},
        )
        == "definition"
    )


def test_book_structured_chunker_characterizes_heading_paths() -> None:
    text = "Front matter.\n\nChapter 1\nAlpha body.\n\nSection 1.1\nBeta body.\n"

    assert _summarize_chunks(BookStructuredChunker(10_000, 0), text) == [
        (
            "Front matter.",
            {
                "chunk_strategy": "book_structured",
                "start_char": 0,
                "end_char": 13,
                "chunk_index": 0,
            },
        ),
        (
            "Chapter 1\nAlpha body.",
            {
                "chunk_strategy": "book_structured",
                "start_char": 15,
                "end_char": 36,
                "book_heading": "Chapter 1",
                "book_level": 2,
                "book_kind": "chapter",
                "book_path": ["Chapter 1"],
                "book_path_str": "Chapter 1",
                "chunk_index": 1,
            },
        ),
        (
            "Section 1.1\nBeta body.",
            {
                "chunk_strategy": "book_structured",
                "start_char": 38,
                "end_char": 60,
                "book_heading": "Section 1.1",
                "book_level": 3,
                "book_kind": "section",
                "book_path": ["Chapter 1", "Section 1.1"],
                "book_path_str": "Chapter 1 / Section 1.1",
                "chunk_index": 2,
            },
        ),
    ]


def test_chat_history_chunker_characterizes_structured_and_fallback_chunks() -> None:
    structured = "[2024-01-01 10:00] Alice: Hello\n[2024-01-01 10:01] Bob: Hi\n[2024-01-01 10:02] Alice: Update\n"
    fallback = "plain paragraph without timestamps\nsecond line\n"

    assert _summarize_chunks(ChatHistoryChunker(60, 15), structured) == [
        (
            "[2024-01-01 10:00] Alice: Hello\n[2024-01-01 10:01] Bob: Hi\n",
            {
                "chunk_strategy": "chat_history",
                "start_char": 0,
                "end_char": 59,
                "message_count": 2,
                "participants": ["Alice", "Bob"],
                "has_timestamps": True,
                "first_timestamp": "2024-01-01 10:00",
                "last_timestamp": "2024-01-01 10:01",
                "chunk_index": 0,
            },
        ),
        (
            "[2024-01-01 10:01] Bob: Hi\n[2024-01-01 10:02] Alice: Update\n",
            {
                "chunk_strategy": "chat_history",
                "start_char": 32,
                "end_char": 92,
                "message_count": 2,
                "participants": ["Bob", "Alice"],
                "has_timestamps": True,
                "first_timestamp": "2024-01-01 10:01",
                "last_timestamp": "2024-01-01 10:02",
                "chunk_index": 1,
            },
        ),
        (
            "[2024-01-01 10:02] Alice: Update\n",
            {
                "chunk_strategy": "chat_history",
                "start_char": 59,
                "end_char": 92,
                "message_count": 1,
                "participants": ["Alice"],
                "has_timestamps": True,
                "first_timestamp": "2024-01-01 10:02",
                "last_timestamp": "2024-01-01 10:02",
                "chunk_index": 2,
            },
        ),
    ]
    assert _summarize_chunks(ChatHistoryChunker(50, 0), fallback) == [
        (
            "plain paragraph without timestamps\nsecond line",
            {
                "chunk_strategy": "chat_history",
                "start_char": 0,
                "end_char": 46,
                "chat_fallback": True,
                "chunk_index": 0,
            },
        ),
    ]


def test_docker_compose_chunker_characterizes_service_and_fallback_chunks() -> None:
    structured = (
        'version: "3.9"\n'
        "name: demo\n"
        "services:\n"
        "  api:\n"
        "    image: demo:latest\n"
        '    ports:\n      - "80:80"\n'
        "  worker:\n"
        "    build: .\n"
    )
    fallback = "services disabled\njust text\n"

    assert _summarize_chunks(DockerComposeChunker(10_000, 0), structured) == [
        (
            'version: "3.9"\nname: demo\nservices:',
            {
                "chunk_strategy": "docker_compose",
                "start_char": 0,
                "end_char": 35,
                "docker_compose_preamble": True,
                "docker_compose_version": '"3.9"',
                "doc_type_kwd": "docker-compose",
                "chunk_index": 0,
            },
        ),
        (
            'api:\n    image: demo:latest\n    ports:\n      - "80:80"',
            {
                "chunk_strategy": "docker_compose",
                "start_char": 38,
                "end_char": 92,
                "doc_type_kwd": "docker-compose",
                "docker_compose_version": '"3.9"',
                "compose_service": "api",
                "compose_service_index": 0,
                "compose_service_count": 2,
                "chunk_index": 1,
            },
        ),
        (
            "worker:\n    build: .",
            {
                "chunk_strategy": "docker_compose",
                "start_char": 95,
                "end_char": 115,
                "doc_type_kwd": "docker-compose",
                "docker_compose_version": '"3.9"',
                "compose_service": "worker",
                "compose_service_index": 1,
                "compose_service_count": 2,
                "chunk_index": 2,
            },
        ),
    ]
    assert _summarize_chunks(DockerComposeChunker(50, 0), fallback) == [
        (
            "services disabled\njust text",
            {
                "chunk_strategy": "docker_compose",
                "start_char": 0,
                "end_char": 27,
                "docker_compose_fallback": True,
                "doc_type_kwd": "docker-compose",
                "chunk_index": 0,
            },
        ),
    ]


def test_dockerfile_chunker_characterizes_stage_overlap_and_instruction_metadata() -> None:
    text = (
        "# syntax=docker/dockerfile:1\n"
        "FROM python:3.12-slim AS base\n"
        "RUN apt-get update\n"
        "COPY . /app\n"
        "FROM base AS final\n"
        'CMD ["python", "app.py"]\n'
    )

    assert _summarize_chunks(DockerfileChunker(55, 12), text) == [
        (
            "FROM python:3.12-slim AS base\nRUN apt-get update\n",
            {
                "chunk_strategy": "dockerfile",
                "start_char": 29,
                "end_char": 78,
                "doc_type_kwd": "dockerfile",
                "docker_stage_index": 0,
                "docker_from_image": "python:3.12-slim",
                "docker_from_alias": "base",
                "docker_instructions": ["FROM", "RUN"],
                "chunk_index": 0,
            },
        ),
        (
            "RUN apt-get update\nCOPY . /app\n",
            {
                "chunk_strategy": "dockerfile",
                "start_char": 59,
                "end_char": 90,
                "doc_type_kwd": "dockerfile",
                "docker_stage_index": 0,
                "docker_from_image": "python:3.12-slim",
                "docker_from_alias": "base",
                "docker_instructions": ["RUN", "COPY"],
                "chunk_index": 1,
            },
        ),
        (
            "COPY . /app\n",
            {
                "chunk_strategy": "dockerfile",
                "start_char": 78,
                "end_char": 90,
                "doc_type_kwd": "dockerfile",
                "docker_stage_index": 0,
                "docker_from_image": "python:3.12-slim",
                "docker_from_alias": "base",
                "docker_instructions": ["COPY"],
                "chunk_index": 2,
            },
        ),
        (
            'FROM base AS final\nCMD ["python", "app.py"]\n',
            {
                "chunk_strategy": "dockerfile",
                "start_char": 90,
                "end_char": 134,
                "doc_type_kwd": "dockerfile",
                "docker_stage_index": 1,
                "docker_from_image": "base",
                "docker_from_alias": "final",
                "docker_instructions": ["FROM", "CMD"],
                "chunk_index": 3,
            },
        ),
        (
            'CMD ["python", "app.py"]\n',
            {
                "chunk_strategy": "dockerfile",
                "start_char": 109,
                "end_char": 134,
                "doc_type_kwd": "dockerfile",
                "docker_stage_index": 1,
                "docker_from_image": "base",
                "docker_from_alias": "final",
                "docker_instructions": ["CMD"],
                "chunk_index": 4,
            },
        ),
    ]


def test_email_thread_chunker_characterizes_message_and_fallback_chunks() -> None:
    structured = (
        "From: Alice <alice@example.com>\n"
        "To: Team <team@example.com>\n"
        "Subject: Status\n"
        "Date: Mon, 1 Jan 2024 10:00:00 +0000\n\n"
        "Body one.\n"
        "-----Original Message-----\n"
        "From: Bob <bob@example.com>\n"
        "To: Team <team@example.com>\n"
        "Subject: Re: Status\n"
        "Date: Mon, 1 Jan 2024 09:00:00 +0000\n\n"
        "> quoted\n"
        "Body two.\n"
    )
    fallback = "single email body only\nno headers here\n"

    assert _summarize_chunks(EmailThreadChunker(180, 50), structured) == [
        (
            "From: Alice <alice@example.com>\n"
            "To: Team <team@example.com>\n"
            "Subject: Status\n"
            "Date: Mon, 1 Jan 2024 10:00:00 +0000\n\n"
            "Body one.\n",
            {
                "chunk_strategy": "email_thread",
                "start_char": 0,
                "end_char": 124,
                "email_message_count": 1,
                "email_subjects": ["Status"],
                "email_froms": ["Alice <alice@example.com>"],
                "email_has_quotes": False,
                "chunk_index": 0,
            },
        ),
        (
            "From: Bob <bob@example.com>\n"
            "To: Team <team@example.com>\n"
            "Subject: Re: Status\n"
            "Date: Mon, 1 Jan 2024 09:00:00 +0000\n\n"
            "> quoted\n"
            "Body two.\n",
            {
                "chunk_strategy": "email_thread",
                "start_char": 151,
                "end_char": 284,
                "email_message_count": 1,
                "email_subjects": ["Re: Status"],
                "email_froms": ["Bob <bob@example.com>"],
                "email_has_quotes": True,
                "chunk_index": 1,
            },
        ),
    ]
    assert _summarize_chunks(EmailThreadChunker(40, 0), fallback) == [
        (
            "single email body only\nno headers here",
            {
                "chunk_strategy": "email_thread",
                "start_char": 0,
                "end_char": 38,
                "email_thread_fallback": True,
                "chunk_index": 0,
            },
        ),
    ]


def test_git_commit_log_chunker_characterizes_commit_metadata() -> None:
    text = (
        "commit 1234567\nAuthor: Alice\nDate: 2024-01-01\n\nfirst\n\n"
        "commit 89abcde\nAuthor: Bob\nDate: 2024-01-02\n\nsecond\n"
    )

    assert _summarize_chunks(GitCommitLogChunker(10_000, 0), text) == [
        (
            "commit 1234567\nAuthor: Alice\nDate: 2024-01-01\n\nfirst",
            {
                "chunk_strategy": "git_commit_log",
                "start_char": 0,
                "end_char": 52,
                "doc_type_kwd": "git",
                "git_commit": "1234567",
                "git_author": "Alice",
                "git_date": "2024-01-01",
                "chunk_index": 0,
            },
        ),
        (
            "commit 89abcde\nAuthor: Bob\nDate: 2024-01-02\n\nsecond",
            {
                "chunk_strategy": "git_commit_log",
                "start_char": 54,
                "end_char": 105,
                "doc_type_kwd": "git",
                "git_commit": "89abcde",
                "git_author": "Bob",
                "git_date": "2024-01-02",
                "chunk_index": 1,
            },
        ),
    ]


def test_github_actions_chunker_characterizes_job_and_fallback_chunks() -> None:
    structured = (
        "name: CI\n"
        "on: push\n"
        "jobs:\n"
        "  test-job:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: pytest\n"
        "  deploy_job:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: ./deploy.sh\n"
    )
    fallback = "name: text\njust notes\n"

    assert _summarize_chunks(GitHubActionsChunker(10_000, 0), structured) == [
        (
            "name: CI\non: push\njobs:",
            {
                "chunk_strategy": "github_actions",
                "start_char": 0,
                "end_char": 23,
                "github_actions_preamble": True,
                "github_workflow_name": "CI",
                "doc_type_kwd": "github-actions",
                "chunk_index": 0,
            },
        ),
        (
            "test-job:\n    runs-on: ubuntu-latest\n    steps:\n      - run: pytest",
            {
                "chunk_strategy": "github_actions",
                "start_char": 26,
                "end_char": 93,
                "doc_type_kwd": "github-actions",
                "github_workflow_name": "CI",
                "github_job": "test-job",
                "github_job_index": 0,
                "github_job_count": 2,
                "chunk_index": 1,
            },
        ),
        (
            "deploy_job:\n    runs-on: ubuntu-latest\n    steps:\n      - run: ./deploy.sh",
            {
                "chunk_strategy": "github_actions",
                "start_char": 96,
                "end_char": 170,
                "doc_type_kwd": "github-actions",
                "github_workflow_name": "CI",
                "github_job": "deploy_job",
                "github_job_index": 1,
                "github_job_count": 2,
                "chunk_index": 2,
            },
        ),
    ]
    assert _summarize_chunks(GitHubActionsChunker(40, 0), fallback) == [
        (
            "name: text\njust notes",
            {
                "chunk_strategy": "github_actions",
                "start_char": 0,
                "end_char": 21,
                "github_actions_fallback": True,
                "github_workflow_name": "text",
                "doc_type_kwd": "github-actions",
                "chunk_index": 0,
            },
        ),
    ]


def test_glossary_chunker_characterizes_entry_overlap_and_fallback_chunks() -> None:
    structured = (
        "API: Application programming interface\n"
        "SDK: Software development kit\n"
        "CLI: Command line interface\n"
    )
    fallback = "random prose only\nno entries\n"

    assert _summarize_chunks(GlossaryChunker(65, 20), structured) == [
        (
            "API: Application programming interface\n",
            {
                "chunk_strategy": "glossary",
                "start_char": 0,
                "end_char": 39,
                "glossary_entry_count": 1,
                "glossary_terms": ["API"],
                "chunk_index": 0,
            },
        ),
        (
            "SDK: Software development kit\nCLI: Command line interface\n",
            {
                "chunk_strategy": "glossary",
                "start_char": 39,
                "end_char": 97,
                "glossary_entry_count": 2,
                "glossary_terms": ["SDK", "CLI"],
                "chunk_index": 1,
            },
        ),
        (
            "CLI: Command line interface\n",
            {
                "chunk_strategy": "glossary",
                "start_char": 69,
                "end_char": 97,
                "glossary_entry_count": 1,
                "glossary_terms": ["CLI"],
                "chunk_index": 2,
            },
        ),
    ]
    assert _summarize_chunks(GlossaryChunker(40, 0), fallback) == [
        (
            "random prose only\nno entries",
            {
                "chunk_strategy": "glossary",
                "start_char": 0,
                "end_char": 28,
                "glossary_fallback": True,
                "chunk_index": 0,
            },
        ),
    ]
