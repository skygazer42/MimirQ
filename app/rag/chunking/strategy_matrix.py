import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.integrated_pipeline.bridge import chunk_file as integrated_chunk_file


@dataclass(frozen=True)
class StrategyFixture:
    filename: str
    content: str
    metadata: dict[str, Any]


def _fixture(filename: str, content: str, *, file_type: str | None = None) -> StrategyFixture:
    suffix = Path(filename).suffix.lstrip(".").lower()
    resolved_type = str(file_type or suffix or "txt")
    return StrategyFixture(
        filename=filename,
        content=content.strip() + "\n",
        metadata={
            "source_path": filename,
            "filename": filename,
            "file_type": resolved_type,
        },
    )


FIXTURES: dict[str, StrategyFixture] = {
    "generic_text": _fixture(
        "generic.txt",
        """
        MimirQ runs retrieval, governance, and chunking for multi-format corpora.
        The ingestion worker writes parsed markdown, chunk metrics, and KG artifacts.

        1. Collect representative samples before broad ingestion.
        2. Compare retrieval latency and citation coverage.
        3. Review parser-specific failure modes and recovery paths.

        The same workflow should preserve semantic continuity across long paragraphs
        while still giving operators clear boundaries for review.
        """,
    ),
    "markdown_notes": _fixture(
        "ops-notes.md",
        """
        # Weekly Ops Review

        ## Summary
        The team validated parser fallbacks, retrieval coverage, and chunk quality.

        ## Action Items
        - Raise the chunk size for dense API manuals.
        - Keep overlap low for row-based tables.

        ## Code Sample
        ```python
        def compute_latency(values: list[float]) -> float:
            return sum(values) / max(1, len(values))
        ```
        """,
    ),
    "markdown_frontmatter": _fixture(
        "frontmatter.md",
        """
        ---
        title: Retrieval Review
        owner: mimirq
        tags:
          - rag
          - governance
        ---

        # Retrieval Review

        ## Findings
        Mainstream RAG pipelines benefit from stable heading-aware chunks.
        """,
    ),
    "outline": _fixture(
        "outline.txt",
        """
        1. Scope
        1.1 Dataset selection
        1.2 Parser fallback
        2. Retrieval
        2.1 Hybrid search
        2.2 Rerank tuning
        3. Delivery
        3.1 Production gate
        3.2 Monitoring
        """,
    ),
    "qa_pairs": _fixture(
        "faq.md",
        """
        Q: What does the ingestion monitor check first?
        A: It checks parser health, queue depth, and chunk completeness.

        Q: When should we use parent-child retrieval?
        A: Use it when documents have strong section hierarchy and large context windows.
        """,
    ),
    "chat_history": _fixture(
        "chat-history.txt",
        """
        [2026-05-20 10:00] Alice: Please validate the parser fallback path.
        [2026-05-20 10:01] Bob: The PDF layout chunks look stable after the fix.
        [2026-05-20 10:02] Alice: Good, then run the retrieval benchmark again.
        [2026-05-20 10:03] Bob: Second pass is now under three seconds.
        """,
    ),
    "transcript": _fixture(
        "transcript.txt",
        """
        Alice: Today we review the production ingestion gate.
        Bob: The first checkpoint is parser availability across formats.
        Alice: After that we inspect chunk overlap and citation coverage.
        Bob: Finally we compare latency against the target SLA.
        """,
    ),
    "paper": _fixture(
        "paper.md",
        """
        # Dense Retrieval Study

        ## Abstract
        This study compares recursive, semantic, and hierarchical chunking on technical corpora.

        ## Introduction
        Retrieval quality depends on preserving local semantics without losing structural anchors.

        ## Method
        We evaluate citation coverage, recall, and latency on realistic engineering documents.

        ## Results
        Heading-aware chunkers reduce fragmentation on manuals and policy docs.

        ## Conclusion
        Hybrid search plus structure-aware chunking remains the practical default.
        """,
    ),
    "book": _fixture(
        "book.txt",
        """
        Part I

        Chapter 1 Retrieval Foundations
        The chapter introduces chunking and ranking for long-form technical material.

        Chapter 2 Evaluation Workflow
        The chapter explains sample selection, benchmark design, and operator review.
        """,
    ),
    "laws": _fixture(
        "policy.txt",
        """
        第一章 总则
        第一条 为保障知识库交付质量，建立统一的治理规范。
        第二条 适用范围包括解析、切块、检索与交付验收。

        第二章 执行要求
        第三条 关键问题必须保留证据引用。
        第四条 低质量样本需要进入人工复核流程。
        """,
    ),
    "policy_manual": _fixture(
        "policy-manual.md",
        """
        # Security Policy Manual

        ## Policy Statement
        Every production retrieval answer must preserve visible evidence.

        ## Control Requirements
        1. Record parser backend and chunk strategy.
        2. Capture governance drops and retries.

        ## Exception Handling
        Document every manual override before release.
        """,
    ),
    "glossary": _fixture(
        "glossary.md",
        """
        Retrieval Budget: The maximum latency or token budget allocated to recall and rerank.
        Parent Chunk: A higher-level chunk that groups semantically related child chunks.
        Governance Pack: A reusable line-oriented cleanup preset for recurring document noise.
        """,
    ),
    "sop": _fixture(
        "sop.md",
        """
        # SOP: Release Readiness

        Step 1: Upload representative files and verify parsing.
        Step 2: Run chunk preview on the default and structure-aware strategies.
        Step 3: Confirm citation coverage and latency before release approval.
        """,
    ),
    "resume": _fixture(
        "resume.md",
        """
        # Chen Li

        ## Experience
        Built retrieval pipelines for enterprise knowledge bases and monitoring systems.

        ## Education
        M.S. in Computer Science, focus on search and information extraction.

        ## Skills
        Python, FastAPI, PostgreSQL, Milvus, RAG evaluation.
        """,
    ),
    "slides": _fixture(
        "slides.md",
        """
        Slide 1
        Retrieval Readiness Review
        ---
        Slide 2
        Latency under 3 seconds
        ---
        Slide 3
        Governance and chunk audit
        """,
    ),
    "csv_rows": _fixture(
        "rows.txt",
        """
        row 1: dataset=alpha | status=completed | chunks=42
        row 2: dataset=beta | status=completed | chunks=57
        row 3: dataset=gamma | status=quarantined | chunks=0
        row 4: dataset=delta | status=completed | chunks=31
        row 5: dataset=epsilon | status=completed | chunks=65
        """,
    ),
    "spreadsheet": _fixture(
        "sheet.txt",
        """
        ## Sheet: Overview
        owner | records | status
        ops | 1200 | active

        ## Sheet: Metrics
        metric | value
        latency_p95 | 2.6s
        citation_coverage | 100%
        """,
    ),
    "markdown_table": _fixture(
        "table.md",
        """
        | metric | value | note |
        | --- | --- | --- |
        | retrieval_p95 | 2.6s | warm path |
        | kg_search_p95 | 2.0s | global mode |
        | citation_coverage | 100% | six citations |
        | failures | 0 | release gate |
        """,
    ),
    "changelog": _fixture(
        "CHANGELOG.md",
        """
        ## [2.3.0] - 2026-05-20
        - Added production readiness chain coverage.
        - Fixed LLM health checks under socks proxy environments.

        ## [2.2.0] - 2026-05-10
        - Added governance rule pack previews.
        """,
    ),
    "log_events": _fixture(
        "events.log",
        """
        2026-05-20 10:00:01 INFO parser completed file=rfc9000.pdf chunks=393
        2026-05-20 10:00:02 WARN kg extractor timeout chunk=abc123 retry=1
        2026-05-20 10:00:03 INFO retrieval elapsed_ms=2481 citations=6
        2026-05-20 10:00:04 INFO release gate passed dataset=prod-readiness
        """,
    ),
    "subtitles": _fixture(
        "session.srt",
        """
        1
        00:00:00,000 --> 00:00:03,000
        We start with parser validation.

        2
        00:00:03,100 --> 00:00:06,000
        Then we measure retrieval latency.
        """,
    ),
    "api_reference": _fixture(
        "api.txt",
        """
        GET /api/v1/documents
        List uploaded documents in the active dataset.

        POST /api/v1/documents/upload
        Upload a new document and trigger parsing.

        GET /api/v1/kg/stats
        Return graph entity, event, and link counts.
        """,
    ),
    "diff_patch": _fixture(
        "change.patch",
        """
        diff --git a/app/api/v1/settings.py b/app/api/v1/settings.py
        @@ -10,6 +10,9 @@
        +with httpx.Client(trust_env=trust_env, timeout=timeout) as http_client:
        +    async with httpx.AsyncClient(trust_env=trust_env, timeout=timeout) as http_async_client:
        +        pass
        diff --git a/app/rag/preprocessing/cleaning.py b/app/rag/preprocessing/cleaning.py
        @@ -20,6 +20,9 @@
        +stats = {"regex_timeout_count": 1}
        """,
    ),
    "git_commit_log": _fixture(
        "git.log",
        """
        commit 1111111111111111111111111111111111111111
        Author: demo <demo@example.com>
        Date:   Tue May 20 10:00:00 2026 +0800

            tighten real production-readiness gate

        commit 2222222222222222222222222222222222222222
        Author: demo <demo@example.com>
        Date:   Tue May 19 09:00:00 2026 +0800

            add governance timeout resilience
        """,
    ),
    "kv_config": _fixture(
        "settings.ini",
        """
        [retrieval]
        top_k=6
        score_threshold=0

        [governance]
        enabled=true
        remove_noise_lines=true
        """,
    ),
    "meeting_minutes": _fixture(
        "minutes.md",
        """
        # Meeting Minutes

        ## Agenda
        Review production readiness gate.

        ## Decisions
        Keep hybrid retrieval as the default.

        ## Action Items
        Run full chunk strategy audit before release.
        """,
    ),
    "timeline": _fixture(
        "timeline.md",
        """
        2026-05-18 Parser fallback fixed.
        2026-05-19 Governance timeout hardened.
        2026-05-20 Full production readiness chain passed.
        """,
    ),
    "html_sections": _fixture(
        "page.html",
        """
        <html><body>
        <h1>Retrieval Guide</h1>
        <p>Hybrid search combines vector and lexical recall.</p>
        <h2>Evidence</h2>
        <p>Every answer must carry citations.</p>
        </body></html>
        """,
        file_type="html",
    ),
    "rst_sections": _fixture(
        "guide.rst",
        """
        Retrieval Guide
        ===============

        Summary
        -------
        Use structure-aware chunking for long technical docs.
        """,
    ),
    "asciidoc_sections": _fixture(
        "guide.adoc",
        """
        = Retrieval Guide

        == Summary
        This section explains chunking and governance defaults.
        """,
    ),
    "latex_sections": _fixture(
        "paper.tex",
        """
        \\section{Introduction}
        Retrieval quality depends on chunk boundaries.
        \\section{Method}
        We compare recursive and hierarchical strategies.
        """,
    ),
    "orgmode_sections": _fixture(
        "notes.org",
        """
        * Retrieval
        Hybrid search keeps citation quality stable.
        ** Governance
        Rule packs clean repeated export noise.
        """,
    ),
    "mediawiki_sections": _fixture(
        "wiki.txt",
        """
        == Retrieval ==
        Hybrid search combines lexical and semantic recall.
        == Governance ==
        Operators review dropped or quarantined documents.
        """,
    ),
    "yaml_manifest": _fixture(
        "manifest.yaml",
        """
        ---
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: mimirq-api
        ---
        apiVersion: v1
        kind: Service
        metadata:
          name: mimirq-api
        """,
        file_type="yaml",
    ),
    "toml_config": _fixture(
        "config.toml",
        """
        [retrieval]
        top_k = 6
        mode = "hybrid"

        [governance]
        enabled = true
        """,
    ),
    "sql_schema": _fixture(
        "schema.sql",
        """
        CREATE TABLE documents (
          id UUID PRIMARY KEY,
          filename TEXT NOT NULL,
          status TEXT NOT NULL
        );

        CREATE INDEX idx_documents_status ON documents(status);
        """,
        file_type="sql",
    ),
    "stacktrace": _fixture(
        "trace.txt",
        """
        Traceback (most recent call last):
          File "runner.py", line 10, in <module>
            main()
          File "runner.py", line 6, in main
            raise RuntimeError("boom")
        RuntimeError: boom
        """,
    ),
    "dockerfile": _fixture(
        "Dockerfile",
        """
        FROM python:3.11-slim
        WORKDIR /app
        COPY . .
        RUN pip install -r requirements.txt
        CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
        """,
        file_type="dockerfile",
    ),
    "makefile": _fixture(
        "Makefile",
        """
        backend:
        \t.venv/bin/python -m uvicorn app.main:app --port 8000

        test:
        \t.venv/bin/python -m pytest -q
        """,
        file_type="makefile",
    ),
    "nginx_config": _fixture(
        "nginx.conf",
        """
        server {
            listen 80;
            location /api/ {
                proxy_pass http://127.0.0.1:8000;
            }
        }
        """,
        file_type="conf",
    ),
    "jira_ticket": _fixture(
        "ticket.txt",
        """
        Summary: Retrieval latency exceeds target
        Description: The first warmup query is above three seconds.
        Steps to Reproduce: Upload the benchmark corpus and run the readiness script.
        Expected Result: Retrieval remains under three seconds.
        Actual Result: First attempt is slower than the warmed cache path.
        """,
    ),
    "prd_spec": _fixture(
        "prd.md",
        """
        # Production Readiness PRD

        ## Background
        Operators need a trustworthy release gate for RAG deployments.

        ## Goals
        Measure real parsing, chunking, KG, and retrieval behavior.

        ## Requirements
        Every query must return citations and stay under the SLA.

        ## Acceptance Criteria
        Twelve representative documents pass end-to-end validation.
        """,
    ),
    "json": _fixture(
        "payload.json",
        """
        {
          "dataset": "prod-readiness",
          "checks": [
            {"name": "retrieval_under_3s", "ok": true},
            {"name": "citations_present", "ok": true}
          ],
          "metadata": {
            "owner": "demo",
            "pipeline": "langchain_recursive"
          }
        }
        """,
        file_type="json",
    ),
    "jsonl_records": _fixture(
        "records.jsonl",
        """
        {"dataset":"alpha","status":"completed","chunks":42}
        {"dataset":"beta","status":"completed","chunks":57}
        {"dataset":"gamma","status":"quarantined","chunks":0}
        """,
        file_type="jsonl",
    ),
    "xml_feed": _fixture(
        "feed.xml",
        """
        <rss><channel>
          <item><title>Retrieval Gate</title><description>Hybrid search passed.</description></item>
          <item><title>Governance Gate</title><description>Rule packs passed.</description></item>
        </channel></rss>
        """,
        file_type="xml",
    ),
    "openapi_spec": _fixture(
        "openapi.yaml",
        """
        openapi: 3.1.0
        info:
          title: MimirQ API
          version: 1.0.0
        paths:
          /api/v1/documents:
            get:
              summary: List documents
          /api/v1/chat:
            post:
              summary: Ask a question
        """,
        file_type="yaml",
    ),
    "graphql_schema": _fixture(
        "schema.graphql",
        """
        type Query {
          documents(status: String): [Document!]!
        }

        type Document {
          id: ID!
          filename: String!
          status: String!
        }
        """,
        file_type="graphql",
    ),
    "proto_schema": _fixture(
        "schema.proto",
        """
        syntax = "proto3";

        message Document {
          string id = 1;
          string filename = 2;
        }

        service RetrievalService {
          rpc Search(Document) returns (Document);
        }
        """,
        file_type="proto",
    ),
    "terraform_hcl": _fixture(
        "main.tf",
        """
        resource "aws_s3_bucket" "reports" {
          bucket = "mimirq-reports"
        }

        module "vector_db" {
          source = "./modules/milvus"
        }
        """,
        file_type="tf",
    ),
    "terraform_plan": _fixture(
        "plan.txt",
        """
        # aws_s3_bucket.reports will be created
        + resource "aws_s3_bucket" "reports" {
            bucket = "mimirq-reports"
          }

        # module.vector_db.aws_instance.main will be updated in-place
        ~ resource "aws_instance" "main" {
            instance_type = "t3.large"
          }
        """,
    ),
    "postmortem": _fixture(
        "postmortem.md",
        """
        # Incident Postmortem

        ## Summary
        The readiness script failed because a regex timeout reset the upload connection.

        ## Impact
        The benchmark dataset could not finish ingestion.

        ## Timeline
        10:00 upload started
        10:01 background task crashed

        ## Root Cause
        Governance regex timeout bubbled out of the cleaning layer.

        ## Action Items
        Catch timeout, skip rule, and preserve the document.
        """,
    ),
    "docker_compose": _fixture(
        "docker-compose.yml",
        """
        services:
          api:
            image: mimirq/api:latest
            ports: ["8000:8000"]
          web:
            image: mimirq/web:latest
            ports: ["3000:3000"]
        """,
        file_type="yaml",
    ),
    "github_actions": _fixture(
        ".github/workflows/ci.yml",
        """
        name: CI
        on: [push]
        jobs:
          test:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - run: pytest -q
        """,
        file_type="yaml",
    ),
    "gitlab_ci": _fixture(
        ".gitlab-ci.yml",
        """
        stages:
          - test

        pytest:
          stage: test
          script:
            - pytest -q
        """,
        file_type="yaml",
    ),
    "ansible_playbook": _fixture(
        "playbook.yml",
        """
        - hosts: all
          tasks:
            - name: restart api
              service:
                name: mimirq-api
                state: restarted
        """,
        file_type="yaml",
    ),
    "http_trace": _fixture(
        "trace.http",
        """
        GET /api/v1/health HTTP/1.1
        Host: localhost:8000

        HTTP/1.1 200 OK
        Content-Type: application/json

        {"ok":true}
        """,
    ),
    "junit_xml": _fixture(
        "junit.xml",
        """
        <testsuite name="suite">
          <testcase classname="tests.test_chain" name="test_retrieval_under_3s" time="2.48" />
          <testcase classname="tests.test_chain" name="test_chat_has_citations" time="0.43" />
        </testsuite>
        """,
        file_type="xml",
    ),
    "sitemap_xml": _fixture(
        "sitemap.xml",
        """
        <urlset>
          <url><loc>https://example.com/docs/retrieval</loc></url>
          <url><loc>https://example.com/docs/governance</loc></url>
        </urlset>
        """,
        file_type="xml",
    ),
    "maven_pom": _fixture(
        "pom.xml",
        """
        <project>
          <dependencies>
            <dependency>
              <groupId>org.springframework</groupId>
              <artifactId>spring-core</artifactId>
            </dependency>
          </dependencies>
        </project>
        """,
        file_type="xml",
    ),
    "code": _fixture(
        "service.py",
        """
        class RetrievalGate:
            def __init__(self, limit: float) -> None:
                self.limit = limit

            def passed(self, elapsed_ms: float) -> bool:
                return elapsed_ms <= self.limit


        def summarize(values: list[float]) -> float:
            return sum(values) / max(1, len(values))
        """,
        file_type="py",
    ),
    "pdf_layout": _fixture(
        "layout.md",
        """
        Retrieval overview@@1\t10\t100\t20\t40##
        Hybrid search preserves both semantic and lexical evidence@@1\t10\t250\t45\t70##
        Second column note@@1\t320\t520\t45\t80##
        """,
        file_type="pdf",
    ),
    "integrated_email": _fixture(
        "thread.eml",
        """
        From: alice@example.com
        To: ops@example.com
        Subject: Retrieval release gate

        The readiness chain passed after the proxy and regex timeout fixes.
        """,
        file_type="eml",
    ),
}


GENERIC_TEXT_STRATEGIES = {
    "agentic_chunker",
    "langchain_recursive",
    "langchain_token",
    "semantic_sentence",
    "sentence_window",
    "separator",
    "late_chunking",
    "late_chunking_jina",
    "proposition",
    "raptor",
    "manuscript",
    "text_hierarchy",
}
MARKDOWN_STRATEGIES = {
    "markdown",
    "markdown_header",
    "markdown_outline",
    "markdown_aware",
    "markdown_hierarchy",
    "auto",
}
STRATEGY_FIXTURE_KEY: dict[str, str] = {}


def _assign(strategies: set[str], fixture_key: str) -> None:
    for strategy in strategies:
        STRATEGY_FIXTURE_KEY[strategy] = fixture_key


_assign(GENERIC_TEXT_STRATEGIES, "generic_text")
_assign(MARKDOWN_STRATEGIES, "markdown_notes")
_assign({"markdown_frontmatter"}, "markdown_frontmatter")
_assign({"outline"}, "outline")
_assign({"qa_pairs", "qa_markdown"}, "qa_pairs")
_assign({"chat_history"}, "chat_history")
_assign({"transcript"}, "transcript")
_assign({"paper"}, "paper")
_assign({"book_structured"}, "book")
_assign({"laws_structured"}, "laws")
_assign({"policy_manual_structured"}, "policy_manual")
_assign({"glossary"}, "glossary")
_assign({"sop_steps"}, "sop")
_assign({"resume_structured"}, "resume")
_assign({"presentation_slides"}, "slides")
_assign({"csv_rows"}, "csv_rows")
_assign({"spreadsheet_sheet"}, "spreadsheet")
_assign({"markdown_table"}, "markdown_table")
_assign({"changelog"}, "changelog")
_assign({"log_events"}, "log_events")
_assign({"subtitles"}, "subtitles")
_assign({"api_reference"}, "api_reference")
_assign({"diff_patch"}, "diff_patch")
_assign({"git_commit_log"}, "git_commit_log")
_assign({"kv_config"}, "kv_config")
_assign({"meeting_minutes"}, "meeting_minutes")
_assign({"timeline_events"}, "timeline")
_assign({"html_sections"}, "html_sections")
_assign({"rst_sections"}, "rst_sections")
_assign({"asciidoc_sections"}, "asciidoc_sections")
_assign({"latex_sections"}, "latex_sections")
_assign({"orgmode_sections"}, "orgmode_sections")
_assign({"mediawiki_sections"}, "mediawiki_sections")
_assign({"yaml_manifest"}, "yaml_manifest")
_assign({"toml_config"}, "toml_config")
_assign({"sql_schema"}, "sql_schema")
_assign({"stacktrace"}, "stacktrace")
_assign({"dockerfile"}, "dockerfile")
_assign({"makefile"}, "makefile")
_assign({"nginx_config"}, "nginx_config")
_assign({"jira_ticket"}, "jira_ticket")
_assign({"prd_spec"}, "prd_spec")
_assign({"json"}, "json")
_assign({"jsonl_records"}, "jsonl_records")
_assign({"xml_feed"}, "xml_feed")
_assign({"openapi_spec"}, "openapi_spec")
_assign({"graphql_schema"}, "graphql_schema")
_assign({"proto_schema"}, "proto_schema")
_assign({"terraform_hcl"}, "terraform_hcl")
_assign({"terraform_plan"}, "terraform_plan")
_assign({"postmortem_report"}, "postmortem")
_assign({"docker_compose"}, "docker_compose")
_assign({"github_actions"}, "github_actions")
_assign({"gitlab_ci"}, "gitlab_ci")
_assign({"ansible_playbook"}, "ansible_playbook")
_assign({"http_trace"}, "http_trace")
_assign({"junit_xml"}, "junit_xml")
_assign({"sitemap_xml"}, "sitemap_xml")
_assign({"maven_pom"}, "maven_pom")
_assign({"code", "smart_code"}, "code")
_assign({"pdf_layout"}, "pdf_layout")
_assign({"email_thread"}, "integrated_email")
_assign({"parent_child"}, "markdown_notes")
_assign({"llama_index", "llama_index_hierarchical"}, "generic_text")
_assign({"integrated_naive"}, "markdown_notes")
_assign({"integrated_book"}, "book")
_assign({"integrated_laws"}, "laws")
_assign({"integrated_email"}, "integrated_email")


def validate_strategy_fixture_mapping() -> None:
    expected = set(chunker_factory.SUPPORTED_STRATEGIES.keys()) | set(chunker_factory.INTEGRATED_PIPELINE_STRATEGIES)
    missing = sorted(expected - set(STRATEGY_FIXTURE_KEY))
    extra = sorted(set(STRATEGY_FIXTURE_KEY) - expected)
    if missing or extra:
        raise RuntimeError(f"strategy fixture mapping mismatch: missing={missing} extra={extra}")


def _fixture_document(strategy: str) -> Document:
    fixture = FIXTURES[STRATEGY_FIXTURE_KEY[strategy]]
    meta = dict(fixture.metadata)
    meta["chunk_strategy_requested"] = strategy
    return Document(page_content=fixture.content, metadata=meta)


def _is_expected_unavailable(strategy: str, exc: Exception) -> bool:
    message = str(exc or "")
    if strategy in {"llama_index", "llama_index_hierarchical"}:
        try:
            import llama_index.core as llama_index_core
        except Exception:
            return True
        del llama_index_core
    return "disabled" in message.lower() or "not installed" in message.lower()


def run_chunk_strategy_matrix(
    *,
    chunk_size: int = 900,
    chunk_overlap: int = 90,
) -> list[dict[str, Any]]:
    validate_strategy_fixture_mapping()
    results: list[dict[str, Any]] = []

    for strategy in sorted(
        set(chunker_factory.SUPPORTED_STRATEGIES.keys()) | set(chunker_factory.INTEGRATED_PIPELINE_STRATEGIES)
    ):
        started = time.perf_counter()
        fixture = FIXTURES[STRATEGY_FIXTURE_KEY[strategy]]
        try:
            if strategy in chunker_factory.INTEGRATED_PIPELINE_STRATEGIES:
                with tempfile.TemporaryDirectory(prefix="mimirq-strategy-matrix-") as tmpdir:
                    path = Path(tmpdir) / fixture.filename
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(fixture.content, encoding="utf-8")
                    chunks = integrated_chunk_file(
                        path,
                        strategy=strategy,
                        binary=fixture.content.encode("utf-8"),
                        callback=lambda *_a, **_k: None,
                    )
                    chunk_count = len(chunks or [])
                    first_meta = dict((chunks or [{}])[0]) if chunk_count > 0 and isinstance(chunks[0], dict) else {}
            else:
                restore_llama_flag = None
                if strategy in {"llama_index", "llama_index_hierarchical"} and not bool(
                    getattr(settings, "LLAMA_INDEX_ENABLED", False)
                ):
                    restore_llama_flag = bool(getattr(settings, "LLAMA_INDEX_ENABLED", False))
                    settings.LLAMA_INDEX_ENABLED = True
                try:
                    chunker = chunker_factory.get_chunker(strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
                    docs = [_fixture_document(strategy)]
                    chunks = chunker.split_documents(docs)
                finally:
                    if restore_llama_flag is not None:
                        settings.LLAMA_INDEX_ENABLED = restore_llama_flag
                chunk_count = len(chunks or [])
                if chunk_count > 0 and isinstance(chunks[0], Document):
                    first_meta = dict(chunks[0].metadata or {})
                else:
                    first_meta = {}
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            status = "passed" if chunk_count > 0 else "empty"
            results.append(
                {
                    "strategy": strategy,
                    "fixture": STRATEGY_FIXTURE_KEY[strategy],
                    "status": status,
                    "chunk_count": chunk_count,
                    "elapsed_ms": elapsed_ms,
                    "metadata_keys": sorted(first_meta.keys())[:12],
                    "runtime_flag_enabled": bool(getattr(settings, "LLAMA_INDEX_ENABLED", False))
                    if strategy in {"llama_index", "llama_index_hierarchical"}
                    else None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
            results.append(
                {
                    "strategy": strategy,
                    "fixture": STRATEGY_FIXTURE_KEY[strategy],
                    "status": "unavailable" if _is_expected_unavailable(strategy, exc) else "failed",
                    "chunk_count": 0,
                    "elapsed_ms": elapsed_ms,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return results
