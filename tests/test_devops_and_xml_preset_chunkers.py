from langchain_core.documents import Document

from app.rag.chunking.strategies.ansible_playbook import AnsiblePlaybookChunker
from app.rag.chunking.strategies.docker_compose import DockerComposeChunker
from app.rag.chunking.strategies.gitlab_ci import GitLabCIChunker
from app.rag.chunking.strategies.github_actions import GitHubActionsChunker
from app.rag.chunking.strategies.http_trace import HTTPTraceChunker
from app.rag.chunking.strategies.junit_xml import JUnitXMLChunker
from app.rag.chunking.strategies.markdown_frontmatter import MarkdownFrontmatterChunker
from app.rag.chunking.strategies.maven_pom import MavenPOMChunker
from app.rag.chunking.strategies.sitemap_xml import SitemapXMLChunker
from app.rag.chunking.strategies.terraform_plan import TerraformPlanChunker
from app.rag.chunking.strategies.git_commit_log import GitCommitLogChunker
from app.rag.chunking.strategies.jsonl_records import JsonlRecordsChunker
from app.rag.chunking.strategies.openapi_spec import OpenAPISpecChunker
from app.rag.chunking.strategies.graphql_schema import GraphQLSchemaChunker
from app.rag.chunking.strategies.proto_schema import ProtoSchemaChunker
from app.rag.chunking.strategies.terraform_hcl import TerraformHCLChunker
from app.rag.chunking.strategies.xml_feed import XMLFeedChunker
from app.rag.chunking.strategies.postmortem_report import PostmortemReportChunker


def _assert_offsets(text: str, chunks):
    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata or {}
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content


def test_api_and_schema_chunkers_preserve_offsets_and_metadata():
    openapi_text = (
        "openapi: 3.0.0\n"
        "info:\n"
        "  title: Demo\n"
        "paths:\n"
        "  /health:\n"
        "    get:\n"
        "      summary: Health\n"
        "      responses:\n"
        "        '200':\n"
        "          description: ok\n"
        "  /items:\n"
        "    post:\n"
        "      summary: Create\n"
        "      responses:\n"
        "        '201':\n"
        "          description: created\n"
    )
    openapi_chunks = OpenAPISpecChunker(chunk_size=240, chunk_overlap=40).split_documents(
        [Document(page_content=openapi_text, metadata={"file_type": "yaml"})]
    )
    _assert_offsets(openapi_text, openapi_chunks)
    assert any((c.metadata or {}).get("openapi_path") == "/health" for c in openapi_chunks)
    assert any((c.metadata or {}).get("openapi_path") == "/items" for c in openapi_chunks)

    gql_text = (
        "schema {\n"
        "  query: Query\n"
        "}\n\n"
        "type Query {\n"
        "  hello: String\n"
        "}\n\n"
        "type User {\n"
        "  id: ID!\n"
        "  name: String\n"
        "}\n\n"
        "enum Role {\n"
        "  ADMIN\n"
        "  USER\n"
        "}\n"
    )
    gql_chunks = GraphQLSchemaChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=gql_text, metadata={"file_type": "graphql"})]
    )
    _assert_offsets(gql_text, gql_chunks)
    assert any((c.metadata or {}).get("graphql_kind") for c in gql_chunks)

    proto_text = (
        "syntax = \"proto3\";\n"
        "package demo.v1;\n\n"
        "message User {\n"
        "  string id = 1;\n"
        "}\n\n"
        "service UserService {\n"
        "  rpc GetUser (User) returns (User);\n"
        "}\n"
    )
    proto_chunks = ProtoSchemaChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=proto_text, metadata={"file_type": "proto"})]
    )
    _assert_offsets(proto_text, proto_chunks)
    assert any((c.metadata or {}).get("proto_kind") == "message" for c in proto_chunks)
    assert any((c.metadata or {}).get("proto_kind") == "service" for c in proto_chunks)

    hcl_text = (
        "variable \"region\" {\n"
        "  type = string\n"
        "}\n\n"
        "provider \"aws\" {\n"
        "  region = var.region\n"
        "}\n\n"
        "resource \"aws_s3_bucket\" \"b\" {\n"
        "  bucket = \"demo\"\n"
        "}\n"
    )
    hcl_chunks = TerraformHCLChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=hcl_text, metadata={"file_type": "tf"})]
    )
    _assert_offsets(hcl_text, hcl_chunks)
    assert any((c.metadata or {}).get("hcl_block_type") for c in hcl_chunks)


def test_yaml_workflow_chunkers_preserve_offsets_and_metadata():
    compose_text = (
        "version: \"3.9\"\n"
        "services:\n"
        "  web:\n"
        "    image: nginx:latest\n"
        "    ports:\n"
        "      - \"80:80\"\n"
        "  api:\n"
        "    build: .\n"
        "    depends_on:\n"
        "      - web\n"
    )
    compose_chunks = DockerComposeChunker(chunk_size=200, chunk_overlap=40).split_documents(
        [Document(page_content=compose_text, metadata={"file_type": "yaml"})]
    )
    _assert_offsets(compose_text, compose_chunks)
    assert any((c.metadata or {}).get("compose_service") == "web" for c in compose_chunks)
    assert any((c.metadata or {}).get("compose_service") == "api" for c in compose_chunks)

    gha_text = (
        "name: CI\n"
        "on:\n"
        "  push:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  build:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo test\n"
    )
    gha_chunks = GitHubActionsChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=gha_text, metadata={"file_type": "yaml"})]
    )
    _assert_offsets(gha_text, gha_chunks)
    assert any((c.metadata or {}).get("github_job") == "build" for c in gha_chunks)
    assert any((c.metadata or {}).get("github_job") == "test" for c in gha_chunks)

    gitlab_text = (
        "stages:\n"
        "  - build\n"
        "  - test\n\n"
        "build_job:\n"
        "  stage: build\n"
        "  script:\n"
        "    - echo build\n\n"
        "test_job:\n"
        "  stage: test\n"
        "  script:\n"
        "    - echo test\n"
    )
    gl_chunks = GitLabCIChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=gitlab_text, metadata={"file_type": "yml"})]
    )
    _assert_offsets(gitlab_text, gl_chunks)
    assert any((c.metadata or {}).get("gitlab_ci_key") == "build_job" for c in gl_chunks)
    assert any((c.metadata or {}).get("gitlab_ci_key") == "test_job" for c in gl_chunks)

    ansible_text = (
        "---\n"
        "- name: Setup\n"
        "  hosts: all\n"
        "  tasks:\n"
        "    - name: Ensure package\n"
        "      apt:\n"
        "        name: curl\n"
        "        state: present\n\n"
        "- hosts: all\n"
        "  tasks:\n"
        "    - name: Ping\n"
        "      ping:\n"
    )
    ansible_chunks = AnsiblePlaybookChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=ansible_text, metadata={"file_type": "yaml"})]
    )
    _assert_offsets(ansible_text, ansible_chunks)
    assert any((c.metadata or {}).get("ansible_play_name") == "Setup" for c in ansible_chunks)
    assert any((c.metadata or {}).get("ansible_hosts") for c in ansible_chunks)


def test_xml_chunkers_preserve_offsets_and_metadata():
    feed_text = (
        "<?xml version=\"1.0\"?>\n"
        "<rss version=\"2.0\">\n"
        "  <channel>\n"
        "    <title>Demo</title>\n"
        "    <item>\n"
        "      <title>One</title>\n"
        "      <link>https://example.com/1</link>\n"
        "      <description>Hello</description>\n"
        "    </item>\n"
        "    <item>\n"
        "      <title>Two</title>\n"
        "      <link>https://example.com/2</link>\n"
        "      <description>World</description>\n"
        "    </item>\n"
        "  </channel>\n"
        "</rss>\n"
    )
    feed_chunks = XMLFeedChunker(chunk_size=240, chunk_overlap=40).split_documents(
        [Document(page_content=feed_text, metadata={"file_type": "xml"})]
    )
    _assert_offsets(feed_text, feed_chunks)
    assert any((c.metadata or {}).get("xml_feed_title") == "One" for c in feed_chunks)
    assert any((c.metadata or {}).get("xml_feed_title") == "Two" for c in feed_chunks)

    junit_text = (
        "<testsuite name=\"demo\">\n"
        "  <testcase classname=\"a\" name=\"t1\" time=\"0.1\"/>\n"
        "  <testcase classname=\"a\" name=\"t2\" time=\"0.2\">\n"
        "    <failure message=\"boom\">stack</failure>\n"
        "  </testcase>\n"
        "</testsuite>\n"
    )
    junit_chunks = JUnitXMLChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=junit_text, metadata={"file_type": "xml"})]
    )
    _assert_offsets(junit_text, junit_chunks)
    assert any((c.metadata or {}).get("junit_case") == "t1" for c in junit_chunks)
    assert any((c.metadata or {}).get("junit_case") == "t2" for c in junit_chunks)

    sitemap_text = (
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n"
        "  <url><loc>https://example.com/</loc></url>\n"
        "  <url><loc>https://example.com/a</loc></url>\n"
        "</urlset>\n"
    )
    sitemap_chunks = SitemapXMLChunker(chunk_size=180, chunk_overlap=40).split_documents(
        [Document(page_content=sitemap_text, metadata={"file_type": "xml"})]
    )
    _assert_offsets(sitemap_text, sitemap_chunks)
    assert any((c.metadata or {}).get("sitemap_loc") == "https://example.com/" for c in sitemap_chunks)

    pom_text = (
        "<project>\n"
        "  <modelVersion>4.0.0</modelVersion>\n"
        "  <groupId>com.example</groupId>\n"
        "  <artifactId>demo</artifactId>\n"
        "  <version>1.0</version>\n"
        "  <dependencies>\n"
        "    <dependency>\n"
        "      <groupId>org.slf4j</groupId>\n"
        "      <artifactId>slf4j-api</artifactId>\n"
        "      <version>2.0.9</version>\n"
        "    </dependency>\n"
        "    <dependency>\n"
        "      <groupId>junit</groupId>\n"
        "      <artifactId>junit</artifactId>\n"
        "      <version>4.13.2</version>\n"
        "    </dependency>\n"
        "  </dependencies>\n"
        "  <build>\n"
        "    <plugins>\n"
        "      <plugin>\n"
        "        <groupId>org.apache.maven.plugins</groupId>\n"
        "        <artifactId>maven-surefire-plugin</artifactId>\n"
        "        <version>3.1.2</version>\n"
        "      </plugin>\n"
        "    </plugins>\n"
        "  </build>\n"
        "</project>\n"
    )
    pom_chunks = MavenPOMChunker(chunk_size=260, chunk_overlap=60).split_documents(
        [Document(page_content=pom_text, metadata={"file_type": "xml"})]
    )
    _assert_offsets(pom_text, pom_chunks)
    all_artifacts = []
    for c in pom_chunks:
        all_artifacts.extend((c.metadata or {}).get("maven_artifacts") or [])
    assert any("org.slf4j:slf4j-api" in a for a in all_artifacts)


def test_log_and_report_chunkers_preserve_offsets_and_metadata():
    jsonl_text = (
        "{\"id\":1,\"msg\":\"a\"}\n"
        "{\"id\":2,\"msg\":\"b\"}\n"
        "{\"id\":3,\"msg\":\"c\"}\n"
        "{\"id\":4,\"msg\":\"d\"}\n"
        "{\"id\":5,\"msg\":\"e\"}\n"
    )
    jsonl_chunks = JsonlRecordsChunker(chunk_size=45, chunk_overlap=10).split_documents(
        [Document(page_content=jsonl_text, metadata={"file_type": "jsonl"})]
    )
    _assert_offsets(jsonl_text, jsonl_chunks)
    assert any(int((c.metadata or {}).get("jsonl_record_count") or 0) >= 1 for c in jsonl_chunks)

    commit_text = (
        "commit 1111111\n"
        "Author: A <a@example.com>\n"
        "Date:   Mon Jan 1 00:00:00 2024 +0000\n\n"
        "    first\n\n"
        "commit 2222222\n"
        "Author: B <b@example.com>\n"
        "Date:   Tue Jan 2 00:00:00 2024 +0000\n\n"
        "    second\n"
    )
    commit_chunks = GitCommitLogChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=commit_text, metadata={"file_type": "txt"})]
    )
    _assert_offsets(commit_text, commit_chunks)
    assert any((c.metadata or {}).get("git_commit") == "1111111" for c in commit_chunks)
    assert any((c.metadata or {}).get("git_commit") == "2222222" for c in commit_chunks)

    http_text = (
        "> GET /health HTTP/1.1\n"
        "> Host: example.com\n"
        ">\n"
        "< HTTP/1.1 200 OK\n"
        "< Content-Type: text/plain\n"
        "<\n"
        "ok\n\n"
        "> POST /items HTTP/1.1\n"
        "> Host: example.com\n"
        ">\n"
        "< HTTP/1.1 201 Created\n"
        "< Content-Type: application/json\n"
        "<\n"
        "{\"id\":1}\n"
    )
    http_chunks = HTTPTraceChunker(chunk_size=240, chunk_overlap=40).split_documents(
        [Document(page_content=http_text, metadata={"file_type": "log"})]
    )
    _assert_offsets(http_text, http_chunks)
    assert any((c.metadata or {}).get("http_method") == "GET" for c in http_chunks)
    assert any(int((c.metadata or {}).get("http_status") or 0) == 201 for c in http_chunks)

    plan_text = (
        "Terraform will perform the following actions:\n\n"
        "  # aws_s3_bucket.b will be created\n"
        "  + resource \"aws_s3_bucket\" \"b\" {\n"
        "      + bucket = \"demo\"\n"
        "    }\n\n"
        "  # aws_s3_bucket_policy.p will be updated in-place\n"
        "  ~ resource \"aws_s3_bucket_policy\" \"p\" {\n"
        "      ~ policy = \"x\"\n"
        "    }\n\n"
        "Plan: 1 to add, 1 to change, 0 to destroy.\n"
    )
    plan_chunks = TerraformPlanChunker(chunk_size=240, chunk_overlap=40).split_documents(
        [Document(page_content=plan_text, metadata={"file_type": "txt"})]
    )
    _assert_offsets(plan_text, plan_chunks)
    assert any((c.metadata or {}).get("terraform_action") for c in plan_chunks)

    postmortem_text = (
        "# Summary\n"
        + ("a " * 60).strip()
        + "\n\n# Impact\n"
        + ("b " * 60).strip()
        + "\n\n# Timeline\n"
        + ("c " * 60).strip()
        + "\n\n# Root Cause\n"
        + ("d " * 60).strip()
        + "\n\n# Detection\n"
        + ("e " * 60).strip()
        + "\n\n# Action Items\n"
        + ("f " * 60).strip()
        + "\n"
    )
    pm_chunks = PostmortemReportChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=postmortem_text, metadata={"file_type": "md"})]
    )
    _assert_offsets(postmortem_text, pm_chunks)
    assert any((c.metadata or {}).get("postmortem_section") for c in pm_chunks)

    fm_text = (
        "---\n"
        "title: Demo\n"
        "tags: [a, b]\n"
        "---\n\n"
        "# Heading\n"
        + ("x " * 80).strip()
        + "\n"
    )
    fm_chunks = MarkdownFrontmatterChunker(chunk_size=220, chunk_overlap=40).split_documents(
        [Document(page_content=fm_text, metadata={"file_type": "md"})]
    )
    _assert_offsets(fm_text, fm_chunks)
    assert any((c.metadata or {}).get("markdown_frontmatter") is True for c in fm_chunks)
    assert any((c.metadata or {}).get("frontmatter_present") is True for c in fm_chunks)

