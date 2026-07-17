<div align="center">

<img src="./images/logo.png" alt="MimirQ" width="100%"/>

<h3>The RAG You Can Actually See · Chinese-First Knowledge Base Platform</h3>

<p><b>Not just another black-box RAG</b> — how your docs get chunked, what retrieval actually hit, and why the answer says what it says: every step is laid bare for you to inspect and tune.</p>

<p>Deep Document Understanding · Hybrid Retrieval · Knowledge Graph · Visual Chunking · Evaluation Governance · Enterprise Security</p>

<p>
  <a href="https://github.com/skygazer42/MimirQ/wiki"><b>Docs</b></a> ·
  <a href="https://skygazer42.github.io/MimirQ/"><b>API (Pages)</b></a> ·
  <a href="./docs/api/README.md"><b>API Guide</b></a> ·
  <a href="#-quick-start"><b>Quick Start</b></a> ·
  <a href="https://github.com/skygazer42/MimirQ/issues"><b>Feedback</b></a> ·
  <a href="./.github/CONTRIBUTING.md"><b>Contributing</b></a>
</p>

<p>
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License: Apache 2.0"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"/></a>
  <a href="https://nextjs.org/"><img src="https://img.shields.io/badge/Next.js-14-black" alt="Next.js 14"/></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.135-009688.svg" alt="FastAPI"/></a>
  <a href="https://langchain.com/"><img src="https://img.shields.io/badge/LangChain-1.x-green" alt="LangChain"/></a>
  <a href="https://langchain-ai.github.io/langgraph/"><img src="https://img.shields.io/badge/LangGraph-1.0-1C3C3C" alt="LangGraph"/></a>
  <a href="https://milvus.io/"><img src="https://img.shields.io/badge/Milvus-2.3-00a1e0" alt="Milvus"/></a>
</p>

<p>
  <a href="https://github.com/skygazer42/MimirQ"><img src="https://img.shields.io/github/stars/skygazer42/MimirQ?style=social" alt="GitHub Stars"/></a>
  <a href="https://github.com/skygazer42/MimirQ/issues"><img src="https://img.shields.io/github/issues/skygazer42/MimirQ" alt="GitHub Issues"/></a>
  <a href="https://github.com/skygazer42/MimirQ/actions"><img src="https://img.shields.io/github/actions/workflow/status/skygazer42/MimirQ/ci.yml?label=CI" alt="CI Status"/></a>
</p>

<p>
  <a href="./README.md"><img src="https://img.shields.io/badge/简体中文-d9d9d9" alt="简体中文"/></a>
  <a href="./README_EN.md"><img src="https://img.shields.io/badge/English-d9d9d9" alt="English"/></a>
</p>

</div>

---

## 🤔 Why I Built MimirQ

MimirQ did not begin as an attempt to create another RAG framework or collect every fashionable model, agent, and GraphRAG technique in one repository. It began with a concrete government-service Q&A project. The knowledge bases existed and the system could answer questions, but whenever an answer was wrong, the team could not clearly explain where the failure happened. Was a scanned page parsed incorrectly? Did chunking separate an eligibility rule from its exception? Did retrieval miss the newer document? Did reranking bury the actual authority? Or did the model receive the right evidence and ignore it? Most systems exposed only the final answer, so diagnosis meant changing parameters, rebuilding the index, and asking again.

That black box is especially risky in government-service knowledge. The same service may have city-level and district-level versions, policies change, old documents are superseded, and critical conditions often sit inside tables, attachments, or scanned pages. Users rarely ask for a document title; they ask whether their situation qualifies, which materials are missing, or which department is responsible. A fluent answer grounded in an obsolete policy can be worse than an explicit refusal. The real problem is therefore not merely making a model sound more natural. The system must be able to show whether the source was read correctly, what entered the index, why particular evidence was retrieved, whether the user was allowed to see it, and which source sentence supports the final answer.

I tried assembling this path with existing platforms. Each has real strengths: some are excellent workflow builders, some focus on document parsing, and others make agents easy to prototype. In production diagnosis, however, parsing, chunking, indexing, retrieval, reranking, citations, and evaluation often live in separate components. When quality moves, tracing the cause across one request is difficult. Adding another retrieval leg or model call may improve recall while immediately increasing latency and cost. I did not want to build another general-purpose node canvas, or trade more online work for every quality gain. MimirQ therefore focuses on the RAG path itself: move work to ingestion where possible, improve the existing candidate set, and leave inspectable evidence at every stage.

That decision shaped the system. During ingestion, you can inspect parsed output and chunk boundaries. After indexing, you can review metadata, versions, and permissions. During a query, you can follow each retrieval channel, fusion step, reranking decision, and sentence-level citation. The knowledge graph is not a disconnected showcase; it contributes entity relationships and multi-hop evidence. Evaluation is not a score produced once before release; the same questions can be rerun after every change. MimirQ covers a broad path not because it is trying to become an everything platform, but because the root cause of a wrong answer can cross that entire path.

I am open-sourcing it to keep a working, inspectable reference implementation available. The public repository contains no production knowledge bases or private environment details. It includes a reduced government-service plugin sample, reproducible processing paths, and the tests needed to understand the behavior. You can run it as a complete system or reuse only the parser, chunking preview, retrieval tracing, Dify external-knowledge integration, or KG pieces. It does not claim to outperform every project on every dataset. Its more practical goal is this: when quality improves, you can explain why; when it regresses, you can find the cause.

> **MimirQ is not trying to prove that RAG can run. It is trying to show why a RAG system deserves to be trusted.**

---

## 📑 Table of Contents

- [Why I Built MimirQ](#-why-i-built-mimirq)
- [What is MimirQ?](#-what-is-mimirq)
- [Product Screenshots](#-product-screenshots)
- [Quick Start](#-quick-start)
- [Core feature comparison](#-core-feature-comparison)
- [Proven in a Real Deployment](#-proven-in-a-real-deployment)
- [API Reference (OpenAPI / GitHub Pages)](#-api-reference-openapi--github-pages)
- [Deployment Options](#-deployment-options)
- [Feature Guides](#-feature-guides)
- [Development](#-development)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)
- [Acknowledgements](#-acknowledgements)

---

## 💡 What is MimirQ?

**MimirQ** (named after **Mímir**, the Norse guardian of the Well of Wisdom) is a **full-stack, open-source, Chinese-first** RAG knowledge base Q&A platform. It combines **deep document understanding, hybrid retrieval, knowledge graphs, visual chunking, evaluation governance, and enterprise security** into one system you can actually run — frontend and backend both open source, up and running with a single Docker command.

It's built for teams that:

- want a knowledge base that's **production-ready**, not just a working demo;
- are tired of RAG tuning by superstition and want a **visible, reproducible, baseline-driven** way to iterate;
- work with **Chinese documents** (contracts, government filings, finance, technical manuals) and need real Chinese parsing and compliance.

---

## 🖼️ Product Screenshots

These screens use the public government-service plugin samples included in the repository. No production knowledge-base data is shown.

<table>
  <tr>
    <td colspan="2" align="center">
      <img src="./docs/images/screenshots/knowledge-graph.png" alt="MimirQ knowledge graph interface" width="100%"/>
      <br/><strong>Knowledge Graph</strong>
      <br/><sub>Search and analyze entities, events, and relations on one canvas.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/dataset-management.png" alt="MimirQ dataset management interface" width="100%"/>
      <br/><strong>Dataset Management</strong>
      <br/><sub>Track datasets, documents, chunks, and ingestion status in one place.</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/rag-evaluation.png" alt="MimirQ Golden regression evaluation interface" width="100%"/>
      <br/><strong>Golden Regression Evaluation</strong>
      <br/><sub>Inspect golden cases, run history, Recall, MRR, and related metrics together.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/settings.png" alt="MimirQ system settings interface" width="100%"/>
      <br/><strong>System Settings</strong>
      <br/><sub>Review dependency health, parsing capabilities, and model-service integrations.</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/chat-history.png" alt="MimirQ conversation history and evidence review interface" width="100%"/>
      <br/><strong>Conversation History and Evidence</strong>
      <br/><sub>Search previous sessions and review complete answers, sources, and feedback controls.</sub>
    </td>
  </tr>
  <tr>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/ingestion-monitor.png" alt="MimirQ ingestion execution monitor" width="100%"/>
      <br/><strong>Ingestion Execution Monitor</strong>
      <br/><sub>Track parsing, chunking, governance, export, and retry status per dataset.</sub>
    </td>
    <td width="50%" align="center">
      <img src="./docs/images/screenshots/data-governance.png" alt="MimirQ data governance workspace" width="100%"/>
      <br/><strong>Data Governance</strong>
      <br/><sub>Preview documents and run quality checks, cleaning, and annotation in one workspace.</sub>
    </td>
  </tr>
</table>

---

## 🚀 Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 20.10+ & [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- GNU Make and Python 3.9+ (used only for idempotent local config and secret generation)
- At least 4 CPU cores / 16 GB RAM / 50 GB disk

### Minimum Setup

```bash
git clone https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

`make init` creates the complete `.env` and a random JWT `SECRET_KEY`. The file is an advanced configuration reference, not a form to fill in line by line. With the default SiliconFlow setup, only one value is required:

```dotenv
# The only required value
LLM_API_KEY=<your-siliconflow-api-key>
```

Then start the stack:

```bash
make up-web
```

`make up-web` starts the web app, API, worker, Postgres, Milvus, MinIO, and Redis. Existing configuration is never overwritten. Open [http://localhost:3000](http://localhost:3000) and create a local account.

> Want a lighter first look? `make up-lite` swaps Milvus for Chroma/FAISS and skips MinIO. External LLM and embedding calls still require credentials for your own model provider; MimirQ never ships or commits provider secrets.

The first Docker build downloads and verifies a pinned DeepDoc model bundle. Run `make models` before using local source-based parsing. If a proxy only listens on the Linux host loopback, configure it in Docker locally and run `DOCKER_BUILD_NETWORK=host make up-web`; never commit proxy addresses.

| Scenario | Change | Required? |
|:---|:---|:---:|
| Default SiliconFlow LLM + embeddings | `LLM_API_KEY` | **Yes** |
| Different chat provider or model | `LLM_API_BASE`, `LLM_MODEL` | No |
| Separate embedding provider | `EMBEDDING_API_KEY`, `EMBEDDING_API_BASE`, `EMBEDDING_MODEL` | No; blank key and URL reuse the LLM settings |
| SiliconFlow reranker | `ENABLE_RERANKER=true` | No; disabled by default to avoid retrieval latency, and reuses the LLM key |
| MinerU online PDF parsing | `MINERU_ENABLED=true`, `MINERU_API_TOKEN` | No; select `mineru` when uploading |
| Every other `.env` setting | Nothing | No; keep the defaults |

Model IDs must appear in SiliconFlow's `/v1/models` response. Verified chat models include `Qwen/Qwen3-32B` and `Qwen/Qwen3-8B`; verified embedding models include `BAAI/bge-m3` and `Qwen/Qwen3-Embedding-0.6B`; the verified reranker is `BAAI/bge-reranker-v2-m3`. Rebuild existing knowledge-base indexes after changing the embedding model; old and new vectors must not be mixed.

Create credentials in the [SiliconFlow console](https://cloud.siliconflow.cn/account/ak) and at [MinerU](https://mineru.net/). Keep real keys only in the local `.env`; never commit them.

### Run the government-service plugin sample

The repository includes the Changzhou government-service knowledge plugin with small public samples for six source families: service items, one-stop services, common questions, topic FAQs, department FAQs, and district FAQs. Validate governance, chunking, KG output, and the Golden draft without starting a database:

```bash
make changzhou-gov-plugin-test-report
make changzhou-gov-plugin-chunk-report
```

Reports are written under `/tmp/changzhou_gov_plugin_*`; these commands do not write to a database, vector store, or KG. See the [plugin guide](./plugins/pipelines/changzhou-gov-service-knowledge/README.md) for sample paths, plugin refs, and the real-corpus closed-loop command.

### Verify Services

```bash
# Check service status
make ps

# Health checks
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/ready
```

After startup:

| Service | URL |
|:---:|:---|
| **Frontend UI** | [http://localhost:3000](http://localhost:3000) |
| **API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) |
| **Health Check** | [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health) |

> For source-code deployment or local development, see the [Development Guide](./docs/quickstart.md)

---

## 🧭 Core Feature Comparison

| Capability | **MimirQ** | [Dify](https://github.com/langgenius/dify) | [RAGFlow](https://github.com/infiniflow/ragflow) | [FastGPT](https://github.com/labring/FastGPT) | [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | [LangChain](https://github.com/langchain-ai/langchain) |
|:---|:---|:---|:---|:---|:---|:---|
| **Document parsing** | **30+ backends** for PDF, OCR, layout, tables, formulas, and VLM | Knowledge Pipeline for PDF, PPT, and other common formats | **DeepDoc** for complex layouts and scans; MinerU / Docling | PDF and scans with tables and formulas converted to Markdown | Document pipeline for PDF, TXT, DOCX, and more | Document Loaders and third-party parser integrations |
| **Chunking** | **78 strategies** including recursive, semantic, parent-child, RAPTOR, and late chunking; visual preview | General, parent-child, Q&A, and pipeline-defined processing | Template-based chunking with visual human intervention | Automatic, manual, Q&A, and enhanced processing | Automatic document-pipeline chunking | Text Splitters composed in application code |
| **Retrieval / reranking** | Milvus / FAISS / Chroma + BM25 / SPLADE / ColBERT / LTR / RRF; **15 rerankers** | Semantic, full-text, and hybrid retrieval with optional reranking | Multiple recall with fused reranking | Semantic, full-text, and hybrid retrieval + RRF + reranking | Multiple vector databases with source citations | Retriever and reranker components assembled by the application |
| **Knowledge graph** | Entity, relation, and event extraction; entity resolution, community discovery, and multi-hop retrieval | Connected through workflows, plugins, or external services | Built-in GraphRAG | Connected through workflows or external services | Connected through agents or tools | Graph integrations and custom chains |
| **Agents / MCP** | LangGraph agents, Self-RAG / CRAG / FLARE, and MCP client / server | Function Calling / ReAct agents, tools, and MCP | Agentic Workflow, MCP, and code executor | Agent V2, tools, MCP, and VM execution | No-code Agent Builder, MCP, and scheduled tasks | Agents / LangGraph / MCP with a code-first model |
| **Visual workflows** | **No general node canvas**; focused on RAG debugging, governance screens, and APIs | **Core feature** for application and agent orchestration | Agent and ingestion-pipeline orchestration | **Core feature** with flow-node orchestration | No-code Agent Builder | No built-in product UI; supplied by the application |
| **Evaluation / governance** | RAGAS, regression gates, leaderboard, significance tests, and evidence audits | Run logs, observability, and human annotations | Retrieval tests, chunk inspection, and citation tracing | Runtime details, retrieval debugging, and logs | Source citations; no built-in RAG regression gate | Requires LangSmith or a custom evaluation stack |
| **Safety guards** | InputGuard / OutputGuard, PII / secret redaction, and hop-by-hop SSRF validation | Moderation nodes and workflow rules | Sandboxed code execution; business guards require configuration | Workflow-based content review and VM sandbox | Local-first deployment and agent-tool permissions | Implemented through application middleware and deployment boundaries |
| **Enterprise access / compliance** | Document ACL + Security Trimming, RBAC, SCIM / SSO / SAML, and audit logs | Workspace permissions; organization and SSO features in enterprise editions | Account and API authentication; fine-grained compliance is deployment-specific | ABAC + RBAC for teams, groups, and resources | Multi-user permissions in the Docker edition | Not supplied by the framework; implemented by the application |
| **RAG debugging UI** | Chunk preview, retrieval trace, rerank steps, sentence citations, KG, and evaluation dashboards | Dataset tests, workflow traces, and application logs | Chunk visualization, matched passages, and citations | Knowledge-base tests and workflow runtime details | Workspaces, source citations, and chat UI | No built-in UI; connect an observability platform |
| **Dify external knowledge** | **Native Dify External Knowledge API compatibility** | Native external-knowledge consumer | Requires an API adapter | Requires an API adapter | Requires an API adapter | Build an adapter in application code |
| **Getting started** | Docker Compose / Helm with a complete enterprise RAG stack | Docker Compose / Cloud | Docker Compose; official baseline is 4 cores / 16 GB / 50 GB | Docker / Cloud | Desktop / Docker | Python / JS library; assemble the application yourself |

> This comparison reflects the capability surface directly exposed by public releases and official documentation as of 2026-07; it is **not a uniform benchmark**. Plugins, commercial editions, and later releases may change individual entries.

---

## 📍 Proven in a Real Deployment

MimirQ is not a lab demo: it has powered a **municipal government Q&A assistant** across seven district-level and city-level knowledge bases. Validation has two layers: a same-dataset comparison of four real integration paths, followed by a strict before/after pairing on the same Dify HTTP path.

### Four-Way Dify Quality Comparison

<!-- Source: artifacts/changzhou_dify_4way_partial/summary_for_sharing.md; complete_4way_1100=true, generated 2026-07-09T22:30:03Z. -->

| Path | Actual call path | Cases | Answer usability | Answer evidence coverage |
|:---|:---|---:|---:|---:|
| **MimirQ direct retrieval** | Client → MimirQ External Knowledge retrieval API (no LLM generation) | 1100 | **88.9%** | **88.7%** |
| **Dify External → MimirQ** | Dify generates; MimirQ serves as the External Knowledge retriever | 1100 | 67.4% | 65.9% |
| **Dify HTTP → MimirQ** | A Dify Workflow HTTP node calls MimirQ's complete Q&A API | 1100 | 69.6% | 67.9% |
| **Dify native knowledge** | Native Dify ingestion, retrieval, and generation | 1100 | 50.6% | 49.7% |

The 1,100 cases comprise 800 simulated user questions, 200 direct service questions, and 100 exact Q&A cases. All use deterministic evidence-clause matching with no LLM judge. Direct retrieval treats its top-three evidence records as output, while the other paths evaluate generated answers. Because these paths perform different work, their latency is not compared. Latency results will be published after a rerun with a fixed environment, concurrency, and cache state.

### Same-Parameter Dify HTTP Before/After Rerun

<!-- Source: artifacts/dify_3way_benchmark_ab_overlap_20260713/; same app, input SHA, truth SHA, and 687 mutually successful case IDs. -->

| Metric (2026-07-13) | Before upgrade | Final | Change |
|:---|---:|---:|---:|
| Complete execution | 687 / 800 | **800 / 800** | +113 cases |
| Paired answer-clause coverage | **84.4%** | 80.5% | -3.9pp |
| Paired answer usability | **91.8%** | 86.5% | -5.4pp |
| Final full 800 cases | — | 80.2% clause coverage / 86.4% usability | — |
| Latency | — | Pending a controlled rerun | — |

> 📝 **An honest note**: the paired rerun proves a **completion-rate improvement**, not an overall answer-quality gain. Aggregate clause coverage across the seven district knowledge bases rose by 3.0pp, while the city-level base fell by 15.7pp because the new output became shorter, offsetting the district gains. Each version was run once and Dify generation had no fixed random seed, so this is a controlled observation rather than a statistical-significance claim; latency conclusions are pending a controlled rerun. Per-case artifacts remain in the local `artifacts/` directory and are not published; see the [Public Chinese Benchmarks guide](./docs/guides/public_benchmarks_zh.md) for reproducible tests.

Choose [Dify External Knowledge API](./docs/guides/pipeline_plugins.md) when **Dify should retain prompt and answer-generation control**. Use a Dify Workflow HTTP node when **MimirQ should perform retrieval, governance, and final answer generation**.

---

## 📡 API Reference (OpenAPI / GitHub Pages)

| Resource | Link / notes |
|:---|:---|
| **Hosted API browser (GitHub Pages)** | [https://skygazer42.github.io/MimirQ/](https://skygazer42.github.io/MimirQ/) (Redoc + full `openapi.json`; use `https://<owner>.github.io/<repo>/` after fork) |
| **Repository guide** | [docs/api/README.md](./docs/api/README.md) (auth, base path, full OpenAPI tag map) |
| **Scenario flows** | [docs/api/workflows.md](./docs/api/workflows.md) |
| **Local Swagger** | [http://localhost:8000/docs](http://localhost:8000/docs) when the backend is running |
| **Export OpenAPI** | `make openapi-export` → `web/openapi.json` |
| **Build static site** | `make api-docs-build` → `docs/api/site/` |

> Auth convention: there is no global auth middleware — **every route must explicitly depend on `get_current_account_id`**; routes accessing tenant data must also depend on `get_tenant_id`. See [backend_structure.md](./docs/backend_structure.md#添加新-api-路由).

Enable **Settings → Pages → GitHub Actions** on the repository; pushes to `main` run [`.github/workflows/api-docs.yml`](./.github/workflows/api-docs.yml).

---

## 📦 Deployment Options

From a local look to a production cluster:

| Mode | Command | Description |
|:---:|:---|:---|
| **Standard** | `make up` | Full stack: Postgres + Milvus + MinIO + Redis + API + Worker |
| **Standard + Web** | `make up-web` | Recommended first run; initializes local config and starts the complete web stack |
| **Lite Mode** | `make up-lite` | Chroma/FAISS instead of Milvus, no MinIO — quick evaluation |
| **Dev Mode** | `make up-infra` | Infrastructure only, run backend/frontend locally |
| **Helm / K8s** | `helm install` | Production-grade with HPA, PDB, CronJob, PrometheusRule |
| **Parser Extensions** | `make up-etl4llm` | Enable ETL4LLM / Marker / MinerU / PaddleOCR-VL / Qianfan-OCR parsers |

<details>
<summary><b>Production Deployment Tips</b></summary>

```bash
# Edit docker/.env for production settings
# ENV=production
# AUTH_MODE=jwt
# SECRET_KEY=<random string, 32+ chars>
# POSTGRES_PASSWORD=<strong password>

make up
```

For Kubernetes production deployment, see the [Helm Guide](./docs/deployment/helm.md) and [Runbook](./docs/deployment/runbook.md).

</details>

---

## 📖 Feature Guides

| Guide | Description |
|:---|:---|
| [Chunk Preview](./docs/guides/chunk_preview.md) | Visual document chunking and parameter tuning |
| [Knowledge Graph](./docs/guides/knowledge_graph.md) | KG extraction, visualization, and RAG enhancement |
| [Document ACL](./docs/guides/document_acl.md) | Document-level access control & security trimming |
| [URL Import](./docs/guides/url_ingest.md) | Remote URL fetching and batch import |
| [Document Versions](./docs/guides/document_versions.md) | Pipeline version management and rollback |
| [Sparse Retrieval](./docs/guides/sparse_retrieval.md) | SPLADE sparse retrieval channel |
| [ColBERT Reranking](./docs/guides/reranking_colbert.md) | ColBERT late-interaction reranking |
| [RAG Optimization](./docs/guides/rag_optimization.md) | Retrieval and answer quality optimization |
| [Retrieval Debugging](./docs/guides/retrieval_debugging.md) | Retrieval issue diagnosis |
| [SAML SSO](./docs/guides/saml_sso.md) | SAML single sign-on integration |
| [Public Benchmarks](./docs/guides/public_benchmarks_zh.md) | Reproducible Chinese benchmarks (MIRACL-zh / CFEVER) |
| [API guide](./docs/api/README.md) | OpenAPI tag map, Pages link, static build |
| [API workflows](./docs/api/workflows.md) | Endpoint order by scenario |
| [API tutorial](./docs/API.md) | Quick start and code-oriented examples |
| [Quick Start](./docs/quickstart.md) | Development from source |
| [Runbook](./docs/deployment/runbook.md) | Production operations & troubleshooting |

---

## ✅ Development

Run CI-consistent checks before pushing:

```bash
# Full check (backend lint/test + frontend lint/test)
make enterprise-checks

# Backend only
make verify && make test

# Frontend only
cd web && pnpm lint && pnpm test
```

---

## 🗺 Roadmap

**Delivered:**

- [x] Hybrid Retrieval (Vector + BM25, optional SPLADE / ColBERT / LTR)
- [x] Visual Chunk Preview (side-by-side strategies + boundary scoring)
- [x] Knowledge Graph (extraction + visualization + search + snapshot-diff impact analysis)
- [x] Evaluation Governance (RAGAS + regression gates + statistical significance tests)
- [x] Document-Level ACL (Security Trimming)
- [x] Document Version Management (Pipeline Versions)
- [x] URL Connectors & Batch Import
- [x] Self-correcting Agent pipelines (Self-RAG / CRAG / FLARE)
- [x] Chinese PII redaction & safety guards

**Planned:**

- [ ] Visual RAG Workflow Editor
- [ ] More Data Source Connectors (Confluence / S3 / Notion)
- [ ] Cross-language Retrieval
- [ ] Unified LLM-as-Judge (G-Eval + Self-Consistency)

> Follow the public roadmap in [GitHub Issues](https://github.com/skygazer42/MimirQ/issues) — feature requests and votes welcome.

---

## 🤝 Contributing

Whether it's fixing a typo, filing a bug, or proposing a feature — contributions of all kinds are welcome! See [CONTRIBUTING.md](./.github/CONTRIBUTING.md).

```bash
# Fork and clone
git clone https://github.com/<your-username>/MimirQ.git
cd MimirQ
make init

# Local development
make up-infra          # Start infrastructure
make models            # Download and verify the pinned DeepDoc models
cd web && pnpm dev     # Frontend dev
python main.py         # Backend dev

# Pre-push checks
make enterprise-checks
```

---

## 📜 License

This project is licensed under the [Apache License 2.0](LICENSE). Attribution for third-party components (including code vendored from RAGFlow/DeepDoc and build-provisioned model weights) is recorded in [NOTICE](NOTICE).

> ⚠️ **PyMuPDF (AGPL-3.0) notice**: Default PDF parsing may use PyMuPDF, which is licensed under AGPL-3.0 / commercial dual license. If you offer this software as a network service (SaaS), the AGPL network clause may require you to release the source of the entire combined work. To avoid this, switch to a permissively-licensed parsing backend (pypdf / pdfplumber). See NOTICE for details.

---

## 🙏 Acknowledgements

MimirQ is built on the shoulders of outstanding open-source projects:

[Dify](https://github.com/langgenius/dify) · [RAGFlow](https://github.com/infiniflow/ragflow) · [FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

Thanks to [SiliconFlow](https://siliconflow.cn/) for providing CNY 50 in API trial credit for MimirQ's public integration testing.

---

<div align="center">

**If MimirQ took your RAG from "it runs" to "I'd ship it," please give us a ⭐ Star!**

Every star is fuel for us to keep opening the black box.

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
