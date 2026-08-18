<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./web/public/brand/mimirq-lockup-image2-dark.png"/>
  <img src="./web/public/brand/mimirq-lockup-image2.png" alt="MimirQ: an inspectable, regression-testable, governable open-source RAG knowledge base" width="680"/>
</picture>

<p><b>Full-stack, open-source, Chinese-first enterprise RAG knowledge base</b><br/>Turns parsing, governance, chunking, retrieval, reranking, and citations into an inspectable, replaceable, regression-tested knowledge pipeline.</p>

<p>
  <a href="#why-mimirq"><b>Why MimirQ</b></a> ·
  <a href="#product-screenshots"><b>Screenshots</b></a> ·
  <a href="#quick-start"><b>Quick Start</b></a> ·
  <a href="#dify-integration"><b>Dify Integration</b></a> ·
  <a href="#real-world-validation"><b>800-question benchmark</b></a> ·
  <a href="./docs/releases/v1.0.1.md"><b>v1.0.1 Release Notes</b></a>
</p>

<p>
  <a href="https://www.apache.org/licenses/LICENSE-2.0"><img src="https://img.shields.io/badge/License-Apache_2.0-blue.svg" alt="License: Apache 2.0"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+"/></a>
  <img src="https://img.shields.io/badge/Dify-External_Knowledge_%2B_HTTP-1C64F2" alt="Dify External Knowledge and HTTP integration"/>
  <img src="https://img.shields.io/badge/Benchmark-800_questions-0F766E" alt="800-question benchmark"/>
</p>

<p>
  <a href="./README.md"><img src="https://img.shields.io/badge/简体中文-d9d9d9" alt="简体中文"/></a>
  <a href="./README_EN.md"><img src="https://img.shields.io/badge/English-d9d9d9" alt="English"/></a>
  <a href="./README_JA.md"><img src="https://img.shields.io/badge/日本語-d9d9d9" alt="日本語"/></a>
  <a href="./README_KO.md"><img src="https://img.shields.io/badge/한국어-d9d9d9" alt="한국어"/></a>
</p>

</div>

---

## Why MimirQ

**The hard part of an enterprise knowledge base is not embedding documents. It is locating failures, replacing strategies, and proving quality did not regress.**

MimirQ began with a real government knowledge-base delivery. When an answer was wrong, the team needed to determine whether parsing lost a table, governance missed a rule, chunking broke the meaning, retrieval missed the evidence, reranking misplaced it, or generation departed from its citations. Hiding that path behind an “upload and chat” button makes prototypes fast, but long-term delivery difficult to estimate, validate, and govern.

> **A controllable enterprise knowledge pipeline**
>
> `Assess data` → `Select parsers` → `Govern content` → `Chunk by domain`<br/>→ `Vector / full-text index` → `Hybrid retrieval` → `Rerank and cite` → `Golden regression`

A real project starts with representative samples: measure scanned pages, images, tables, formulas, and layout complexity; validate parser quality; and estimate compute and review costs. Complex layouts and scans can start with [MinerU](https://opendatalab.github.io/MinerU/) or [DeepDoc](https://github.com/infiniflow/ragflow/tree/main/deepdoc), formula-, table-, or layout-heavy material should include [Docling](https://docling-project.github.io/docling/) in the evaluation, and digitally born Office or plain-text files can begin with a lighter path such as [MarkItDown](https://github.com/microsoft/markitdown). High-risk corpora still require human review.

After scripts, rule DSLs, or plugins govern the parsed output, content is chunked by headings, sections, business records, or parent-child structure instead of one fixed length and overlap window. The index can combine Milvus or another vector store with BM25, vector retrieval, and reranking. The application above it can be Dify, LangGraph, PydanticAI, or a small API service.

MimirQ does not try to replace every platform:

- **For simple, stable, low-code applications**, Dify or RAGFlow is usually the faster path.
- **For an integrated DeepDoc and GraphRAG experience**, RAGFlow is a mature choice.
- **When the knowledge path must be replaceable, auditable, and regression-tested**, MimirQ keeps that capability independent from the chat application and can serve as Dify's external knowledge layer.

The repository currently covers 30 parsing backends, 86 chunking strategies, 13 reranker families, and a fixed 800-question evaluation trail. Those counts show breadth; the product goal is to inspect every stage, trace citations and versions, and protect releases with Golden sets. See the [enterprise knowledge-pipeline design principles](./docs/guides/rag_platform_design_principles.md).

> Latest stable release: v1.0.1. See the [release notes](./docs/releases/v1.0.1.md) and [release index](./docs/releases/README.md).

---

## Product Screenshots

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

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 20.10+ & [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- GNU Make; Docker startup also needs Python 3.9+ to generate local config
- Source development mode also needs Python 3.11+, Node.js 20+, and pnpm 10.26
- At least 4 CPU cores / 16 GB RAM / 50 GB disk

### Initialize

```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

`make init` creates only missing `.env` and `web/.env.local` files. Edit `.env` for the selected deployment:

- Default model calls: `LLM_API_KEY` (required)
- Custom LLM: `LLM_API_BASE`, `LLM_MODEL`
- Separate embedding service: `EMBEDDING_API_BASE`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`
- Reranker: `ENABLE_RERANKER`, `RERANKER_API_BASE`, `RERANKER_API_KEY`, `RERANKER_MODEL`
- Initial administrator: `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_USERNAME`, `INITIAL_ADMIN_PASSWORD`

See [Model Services and Initial Administrator Configuration](./docs/guides/model_services.md) for values, separate-service examples, and bootstrap rules.

For the full path from dataset creation and ingestion through retrieval, cited answers, governance, evaluation, Dify, and operations, use the [online operation guide](https://skygazer42.github.io/MimirQ/handbook/en/docs/guide/welcome).

| Startup mode | Best for | Where the app runs |
|:---|:---|:---|
| **Docker (recommended)** | First use and server deployment | Web, API, worker, and dependencies run in containers |
| **Source development** | Frontend/backend development and hot reload | `.venv` + pip run the API, pnpm runs the Web app, and Docker runs infrastructure |

### Option 1: Start everything with Docker

```bash
make up-web
make api-ping
```

Open [http://localhost:3000](http://localhost:3000) after startup. If no administrator was preconfigured, register the first account in the UI. First-build, proxy, production-secret, and network guidance is in the [Docker Compose deployment guide](./docs/deployment/docker_compose.md).

Use `make down` to stop the stack, `make docker-reset` to delete persisted data, or `make docker-purge` to also delete this project's service images. MimirQ uses the isolated Compose project name `mimirq`, so a Dify stack on the same host is not part of its cleanup scope. The last two commands are destructive; see the [Docker Compose deployment guide](./docs/deployment/docker_compose.md) for PowerShell commands, ownership checks, legacy-data migration, recovery, and the exact deletion scope.

<details>
<summary><b>Optional parsers by document workload</b></summary>

MimirQ uses built-in DeepDoc by default. Start other parsers only when required:

| Document workload | Recommended parser | Extra requirement | Start after the main stack |
|:---|:---|:---|:---|
| Regular PDF / Office / text | Built-in DeepDoc | None | No extra container |
| PDF to Markdown without a server GPU | Marker | CPU | `make up-marker` |
| Mixed layout, tables, and images | ETL4LLM | CPU | `make up-etl4llm` |
| Scans, OCR, and complex layouts | PaddleOCR-VL | NVIDIA GPU; reserve 10 GiB | `make up-paddlevl` |
| PDFs with many tables, formulas, and images | MinerU pipeline | NVIDIA GPU; first-run model download | `make up-mineru` |
| VLM-based complex PDFs | MinerU VLM | NVIDIA GPU; high resource use | `make up-mineru-vlm` |
| High-accuracy PDF OCR | olmOCR | NVIDIA GPU; 48-GiB-class VRAM recommended | `make up-olmocr` |
| Formula/table PDF to Markdown | MagicPDF | NVIDIA GPU | `make up-magicpdf` |
| PDF/image OCR through an external vision model | Qianfan-OCR | Upstream URL and API key; no local GPU | `make up-qianfanocr` |

See the [Docker Compose deployment guide](./docs/deployment/docker_compose.md) and [parser documentation](./docs/quickstart.md) for full settings and platform limits.

</details>

### Option 2: Develop from source (Python venv + pip + pnpm)

This is the conventional local-development path and does not require Conda. FastAPI runs from a Python `.venv`, Next.js runs with pnpm, and Docker is used only for infrastructure such as PostgreSQL, Redis, and Milvus:

```bash
make setup-host
```

`make setup-host` creates `.venv`, installs the pip and pnpm dependencies, prepares parser models, and starts the Docker infrastructure. The default in-process background mode requires two terminals:

```bash
# Terminal 1: FastAPI with hot reload
make backend

# Terminal 2: Next.js with hot reload
make web
```

See [Model Services and Initial Administrator Configuration](./docs/guides/model_services.md) for the optional worker configuration. Verify the host services with:

```bash
make api-ping
```

After stopping the host processes, run `make infra-down` to stop the dependency services.

### Service URLs

| Service | URL |
|:---:|:---|
| **Frontend UI** | [http://localhost:3000](http://localhost:3000) |
| **API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) |

> For a lighter setup, use `make up-lite`; run `make web` separately when the UI is required.

Advanced model, parser, proxy, and Windows guidance is in the [Development Guide](./docs/quickstart.md). The public government-service sample is documented in the [plugin guide](./plugins/pipelines/changzhou-gov-service-knowledge/README.md).

---

## Dify Integration

MimirQ can plug into existing Dify applications as a governable RAG layer, without re-implementing the workflow canvas. Two integration modes are supported today:

- **External Knowledge API**: Dify handles orchestration and generation; MimirQ handles document governance, retrieval, reranking, permission filtering, and evidence return.
- **Workflow HTTP node**: Dify handles custom routing and parameters; MimirQ returns evidence and a trace scoped to the requested knowledge range.

### Workflow HTTP node

<p align="center">
  <a href="./docs/images/screenshots/dify-mimirq-http-workflow.png">
    <img src="./docs/images/screenshots/dify-mimirq-http-workflow.png" alt="A Dify HTTP node calls MimirQ's retrieval API and merges the evidence" width="1100" style="max-width: 100%; height: auto;"/>
  </a>
  <br/>
  <sub>A real Dify HTTP sub-chain (redacted): safely build the JSON request → HTTP node calls MimirQ's retrieval endpoint → transform the result → merge knowledge evidence.</sub>
</p>

### External Knowledge API

<p align="center">
  <a href="./docs/images/screenshots/dify-mimirq-workflow.png">
    <img src="./docs/images/screenshots/dify-mimirq-workflow.png" alt="A Dify workflow routes by region into eight MimirQ government knowledge bases" width="560" style="max-width: 100%; height: auto;"/>
  </a>
  <br/>
  <sub>A real Dify Chatflow (redacted): the green knowledge-retrieval node calls MimirQ through the External Knowledge API, then merges evidence uniformly; click to view the full image.</sub>
</p>

> The regional routing in the diagram comes from the optional sample plugin; the MimirQ core ships no region, service-item, or industry rules.

The standard Dify external-knowledge endpoint is `POST /api/v1/integrations/dify/retrieval`; `POST /api/v1/integrations/dify/conversation-turns` optionally reports answers, citations, and a conversation identifier. See [`.env.example`](./.env.example) for configuration, the [readiness gate](./scripts/README.md) for pre-deploy validation, and [Real-world Validation](#real-world-validation) for measured results.

---

## Core Feature Comparison

<details>
<summary><b>Expand to compare with Dify, RAGFlow, FastGPT, AnythingLLM, and LangChain</b></summary>


| Capability | **MimirQ** | [Dify](https://github.com/langgenius/dify) | [RAGFlow](https://github.com/infiniflow/ragflow) | [FastGPT](https://github.com/labring/FastGPT) | [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | [LangChain](https://github.com/langchain-ai/langchain) |
|:---|:---|:---|:---|:---|:---|:---|
| **Document parsing** | **30 backends** for PDF, OCR, layout, tables, formulas, and VLM | Knowledge Pipeline for PDF, PPT, and other common formats | **DeepDoc** for complex layouts and scans; MinerU / Docling | PDF and scans with tables and formulas converted to Markdown | Document pipeline for PDF, TXT, DOCX, and more | Document Loaders and third-party parser integrations |
| **Chunking** | **86 strategies** including recursive, semantic, parent-child, RAPTOR, and late chunking; visual preview | General, parent-child, Q&A, and pipeline-defined processing | Template-based chunking with visual human intervention | Automatic, manual, Q&A, and enhanced processing | Automatic document-pipeline chunking | Text Splitters composed in application code |
| **Retrieval / reranking** | Milvus / FAISS / Chroma + BM25 / SPLADE / ColBERT / LTR / RRF; **13 rerankers** | Semantic, full-text, and hybrid retrieval with optional reranking | Multiple recall with fused reranking | Semantic, full-text, and hybrid retrieval + RRF + reranking | Multiple vector databases with source citations | Retriever and reranker components assembled by the application |
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

</details>

---

## Real-world Validation

MimirQ has powered a **municipal government Q&A assistant** across seven district-level and one city-level knowledge base. On 2026-07-27, the same fixed 800 questions were rerun with real self-hosted models; all five paths ultimately completed **800 / 800**.

<!-- Data sources: artifacts/dify_4way_800_20260727/comparison_report.json, artifacts/dify_4way_800_20260727/summary_for_sharing.md, and artifacts/changzhou_local_3model_800_20260727/summary.json; input SHA-256 5a4c67c42e8f8123774279d46af39ccc793da1b89fdea19a7359f63c8cb2fac2. -->

> **“Retrieval core” is not LLM question answering.** It runs embedding, hybrid retrieval, and reranking, then returns Top-K evidence directly. “RAG generation” continues by asking an LLM to produce the answer.

### Retrieval Core (No LLM Generation)

| Evidence path | Accuracy | Usability | Evidence coverage | Latency (mean / P95) |
|:---|---:|---:|---:|---:|
| **MimirQ retrieval core** | **98.9%** | **100%** | **99.5%** | **3.64s / 12.58s** |

### End-to-End Answers (With LLM Generation)

| Answer path | Accuracy | Usability | Coverage (evidence / answer) | Latency (mean / P95) |
|:---|---:|---:|---:|---:|
| **MimirQ RAG generation** | **90.9%** | **100%** | **99.7% / 96.6%** | **2.59s / 8.15s** |
| **Dify HTTP → MimirQ** | 64.3% | 92.1% | 96.3% / 83.6% | 13.15s / 17.33s |
| **Dify External → MimirQ** | 62.7% | 91.7% | **99.7%** / 83.8% | 12.14s / 23.49s |
| **Dify native knowledge¹** | 38.6% | 74.5% | 83.8% / 66.1% | 13.67s / 29.55s |

¹ Dify native knowledge does not use MimirQ. See the detailed report for accurate, partially accurate, and insufficient-evidence counts.

Dify HTTP / External reached 96.3% / 99.7% retrieval-evidence coverage, while generated-answer clause coverage was 83.6% / 83.8%. The main loss was in Dify answer generation rather than MimirQ retrieval.

<details>
<summary><b>Test boundary, concurrency, and generality notes</b></summary>

- The retrieval core returns evidence; the other four paths return generated answers. Accuracy and latency across the two tables are not direct like-for-like comparisons.
- Retrieval concurrency 5 initially triggered 15 configured admission-backpressure responses. Retrying only those cases at concurrency 3 restored 800 / 800.
- MimirQ contains no region, service-item, or question-specific special cases. A generic retrieval layer shards multi-dataset requests across different embedding runtimes.

</details>

[Full methodology, metric definitions, and historical reruns](./docs/benchmarks/changzhou_dify.md) · [Dify integration modes and real workflows](#dify-integration)

---

## Deployment Options

Supported deployment modes:

| Mode | Command | Description |
|:---:|:---|:---|
| **Standard** | `make up` | Full stack: Postgres + Milvus + Etcd + MinIO + Redis + API + Worker |
| **Standard + Web** | `make up-web` | Recommended first run; initializes local config and starts the complete web stack |
| **Lite Mode** | `make up-lite` | Chroma/FAISS instead of Milvus, no MinIO — quick evaluation |
| **Dev Mode** | `make infra-up` | Infrastructure only, run backend/frontend locally |
| **Helm / K8s** | `helm install` | Production-grade with HPA, PDB, CronJob, PrometheusRule |
| **Parser Extensions** | [Docker Compose guide](./docs/deployment/docker_compose.md) | Start CPU / GPU profiles as required |

See the [Docker Compose guide](./docs/deployment/docker_compose.md), [Helm guide](./docs/deployment/helm.md), and [runbook](./docs/deployment/runbook.md) for production settings and upgrade order.

---

## Feature Guides

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
| [Quick Start](./docs/quickstart.md) | Development from source |
| [Runbook](./docs/deployment/runbook.md) | Production operations & troubleshooting |

---

## Development

Run CI-consistent checks before pushing (backend + frontend):

```bash
# Full check (backend lint/test + frontend lint/test)
make enterprise-checks

# Backend only
make verify && make test

# Frontend only
cd web && pnpm lint && pnpm test
```

---

## Roadmap

Delivered capabilities are in the comparison table above. Near-term plans:

- [ ] RAG-specific debugging orchestration (not a general agent canvas)
- [ ] More data-source connectors (Confluence / S3 / Notion)
- [ ] Cross-language retrieval
- [ ] Unified LLM-as-Judge (G-Eval + Self-Consistency)

> The roadmap, feature requests, and voting are managed through [GitHub Issues](https://github.com/skygazer42/MimirQ/issues).

---

## Contributing

Before contributing code, reporting an issue, or proposing a feature, read [CONTRIBUTING.md](./.github/CONTRIBUTING.md). See [Quick Start](./docs/quickstart.md) for local development and run `make enterprise-checks` before pushing.

```bash
# Fork and clone
git clone https://github.com/<your-username>/MimirQ.git
cd MimirQ
make init

# Local development
make infra-up           # Start infrastructure
make models             # Download and verify the pinned DeepDoc models
cd web && pnpm dev      # Frontend dev
python main.py          # Backend dev

# Pre-push checks
make enterprise-checks
```

---

## License

This project is licensed under the [Apache License 2.0](LICENSE). Attribution for third-party components (including code vendored from RAGFlow/DeepDoc and build-provisioned model weights) is recorded in [NOTICE](NOTICE).

> **PyMuPDF (AGPL-3.0) notice**: Default PDF parsing may use PyMuPDF, which is licensed under AGPL-3.0 / commercial dual license. Offering this software as a network service (SaaS) may require release of the entire combined work under the AGPL network clause. To avoid this constraint, use a permissively licensed parsing backend (pypdf / pdfplumber). See NOTICE for details.

---

## Acknowledgements

MimirQ is built on the shoulders of outstanding open-source projects:

[Dify](https://github.com/langgenius/dify) · [RAGFlow](https://github.com/infiniflow/ragflow) · [FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

---

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
