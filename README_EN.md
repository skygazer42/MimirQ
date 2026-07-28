<div align="center">

<img src="./images/logo.png" alt="MimirQ: an inspectable, regression-testable, governable open-source RAG knowledge base" width="100%"/>

<p><b>Full-stack open-source, Chinese-first enterprise RAG knowledge base</b><br/>From how a document gets chunked, to what retrieval actually hits, to why an answer is generated — the whole chain is inspectable, debuggable, and regression-testable.</p>

<p>
  <a href="#-quick-start"><b>Quick Start</b></a> ·
  <a href="#-product-screenshots"><b>Screenshots</b></a> ·
  <a href="#-dify-integration"><b>Dify Integration</b></a> ·
  <a href="#-proven-in-a-real-deployment"><b>800-question benchmark</b></a> ·
  <a href="./docs/releases/v1.0.0.md"><b>v1.0.0 Release Notes</b></a> ·
  <a href="https://skygazer42.github.io/MimirQ/"><b>API Docs</b></a>
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

## 💡 What is MimirQ

**MimirQ** (named after **Mímir**, the Norse guardian of the Well of Wisdom) is a RAG knowledge-base Q&A platform focused on **full-chain observability**. Frontend and backend are both open source, and it deploys via Docker Compose or Helm.

> Latest stable release: v1.0.0. See the [release notes](./docs/releases/v1.0.0.md) and [release index](./docs/releases/README.md).

<table>
  <tr>
    <td align="center" width="25%"><strong>30</strong><br/><sub>parsing backends</sub></td>
    <td align="center" width="25%"><strong>86</strong><br/><sub>chunking strategies</sub></td>
    <td align="center" width="25%"><strong>13</strong><br/><sub>rerankers</sub></td>
    <td align="center" width="25%"><strong>800</strong><br/><sub>fixed-set eval</sub></td>
  </tr>
</table>

<table>
  <tr>
    <td width="50%"><strong>See it</strong><br/><sub>parsed output, chunk boundaries, retrieval and rerank steps</sub></td>
    <td width="50%"><strong>Trace it</strong><br/><sub>sentence-level citations, versions, evidence, and full trace</sub></td>
  </tr>
  <tr>
    <td><strong>Guard it</strong><br/><sub>document ACL, RBAC, redaction, audit, and safety rails</sub></td>
    <td><strong>Regress it</strong><br/><sub>golden sets, evaluation dashboard, and release gates</sub></td>
  </tr>
</table>

<details>
<summary><b>Why build MimirQ?</b></summary>

MimirQ began with a concrete government-service Q&A project: the system could already answer questions, but when an answer was wrong it was hard to tell whether the root cause was in parsing, chunking, retrieval, reranking, or generation. Government knowledge also carries multi-region versions, policy updates, scanned pages, and tables — and a fluent answer grounded in an obsolete policy is more dangerous than an explicit "I don't know."

Existing platforms are strong at workflows or agents, but the parsing, indexing, retrieval, citation, and evaluation needed to diagnose RAG are usually scattered across separate components. MimirQ does not build yet another general-purpose node canvas; it focuses on an inspectable RAG path.

> **MimirQ is not trying to prove that RAG can run — it is trying to show why a RAG system deserves to be trusted.**

</details>

---

## 🚀 Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 20.10+ & [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- GNU Make; Docker startup also needs Python 3.9+ to generate local config
- Host source startup also needs Python 3.11+, Node.js 20+, and pnpm 10.26
- At least 4 CPU cores / 16 GB RAM / 50 GB disk

### Common setup

```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

`make init` generates the complete `.env` and a random JWT `SECRET_KEY`. The `.env` file is an advanced configuration reference, not a form to fill in line by line. With the default SiliconFlow setup, only one value is required:

```dotenv
# The only required value
LLM_API_KEY=<your-siliconflow-api-key>
```

| Startup mode | Best for | Where the app runs |
|:---|:---|:---|
| **Docker (recommended)** | First use and server deployment | Web, API, worker, and dependencies run in containers |
| **Host source** | Frontend/backend development and hot reload | Web, API, and worker run on the host; dependencies run in Docker |

### Option 1: Start everything with Docker

```bash
make up-web
make ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

`make up-web` starts the web app, API, worker, Postgres, Milvus, Etcd, MinIO, and Redis; existing configuration is never overwritten. Open [http://localhost:3000](http://localhost:3000) and create a local account to enter the system.

The first Docker build downloads and verifies a pinned DeepDoc model bundle. If a proxy only listens on the Linux host loopback, configure it in Docker locally or run `DOCKER_BUILD_NETWORK=host make up-web`; never commit proxy addresses. If Docker Hub is unavailable, set `MILVUS_IMAGE` in `.env` to the same image in a trusted registry.

Stop the complete web stack with:

```bash
docker compose --env-file .env \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.web.yml down
```

### Option 2: Run the frontend and backend on the host

Install host dependencies and start the infrastructure services:

```bash
make setup-host
```

`make setup-host` creates `.venv`, installs and validates the CPU backend and web dependencies, downloads the pinned parser models, and starts Postgres, Milvus, Etcd, MinIO, and Redis. Existing `.env` values are preserved.

Open three terminals:

```bash
# Terminal 1: FastAPI with hot reload
make backend

# Terminal 2: document parsing and indexing worker
make worker

# Terminal 3: Next.js with hot reload
make web
```

Verify the host services:

```bash
make infra-ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

After stopping the three host processes, run `make infra-down` to stop the dependency services.

### Service URLs

| Service | URL |
|:---:|:---|
| **Frontend UI** | [http://localhost:3000](http://localhost:3000) |
| **API Docs** | [http://localhost:8000/docs](http://localhost:8000/docs) |

> For a lighter setup, use `make up-lite`. It swaps Milvus for Chroma/FAISS and skips MinIO, but does not start the frontend by default; run `make web` separately when you need the UI. External LLM and embedding calls still require your own provider credentials.

| Scenario | Change | Required? |
|:---|:---|:---:|
| Default SiliconFlow LLM + embeddings | `LLM_API_KEY` | **Yes** |
| Different chat provider or model | `LLM_API_BASE`, `LLM_MODEL` | No |
| Separate embedding provider | `EMBEDDING_API_KEY`, `EMBEDDING_API_BASE`, `EMBEDDING_MODEL` | No; blank key and URL reuse the LLM settings |
| SiliconFlow reranker | `ENABLE_RERANKER=true` | No; disabled by default to avoid retrieval latency, reuses the LLM key |
| MinerU online PDF parsing | `MINERU_ENABLED=true`, `MINERU_API_TOKEN` | No; select `mineru` when uploading |
| Every other `.env` setting | Nothing | No; keep the defaults |

Model IDs must appear in SiliconFlow's `/v1/models` response. Verified chat models include `Qwen/Qwen3-32B` and `Qwen/Qwen3-8B`; verified embedding models include `BAAI/bge-m3` and `Qwen/Qwen3-Embedding-0.6B`; the verified reranker is `BAAI/bge-reranker-v2-m3`. Rebuild existing knowledge-base indexes after changing the embedding model; old and new vectors must not be mixed. Create credentials in the [SiliconFlow console](https://cloud.siliconflow.cn/account/ak) and at [MinerU](https://mineru.net/), and keep real keys only in the local `.env`.

### Run the government-service plugin sample

The repository includes the Changzhou government-service knowledge plugin with small public samples for six source families: service items, one-stop services, common questions, topic FAQs, department FAQs, and district FAQs. Validate governance, chunking, KG output, and the Golden draft without starting a database:

```bash
make changzhou-gov-plugin-test-report
make changzhou-gov-plugin-chunk-report
```

Reports are written under `/tmp/changzhou_gov_plugin_*`; these commands do not write to a database, vector store, or KG. See the [plugin guide](./plugins/pipelines/changzhou-gov-service-knowledge/README.md) for sample paths, plugin refs, and the real-corpus closed-loop command.

For advanced model, parser, and proxy settings, see [`.env.example`](./.env.example). Rebuild existing knowledge-base indexes after changing the embedding model. For more platforms and Windows instructions, see the [Development Guide](./docs/quickstart.md).

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

## 🔌 Dify Integration

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

The standard Dify external-knowledge endpoint is `POST /api/v1/integrations/dify/retrieval`; you can optionally use `POST /api/v1/integrations/dify/conversation-turns` to report answers, citations, and a conversation identifier. See [`.env.example`](./.env.example) for configuration, the [readiness gate](./scripts/README.md) for pre-deploy validation, and [Proven in a Real Deployment](#-proven-in-a-real-deployment) for measured results.

---

## 🧭 Core Feature Comparison

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

## 📍 Proven in a Real Deployment

MimirQ has powered a **municipal government Q&A assistant** across seven district-level and one city-level knowledge base. The latest direct-retrieval rerun used input SHA-256 `5a4c67...fac2`, with the following results:

| Latest result (2026-07-24) | Result |
|:---|---:|
| Successful execution | **800 / 800**, 0 timeouts |
| Accurate / partially accurate / insufficient evidence | **797 / 3 / 0** |
| Accuracy / usability | **99.6% / 100%** |
| Mean / P50 / P95 / P99 | **1.15s / 0.83s / 4.00s / 8.95s** |

This direct-retrieval run reached 99.7% evidence-clause coverage. Multi-knowledge-base retrieval across different embedding runtimes is sharded by a generic retrieval layer, with no domain hard-coding.

An independent E2E load test — reranker enabled, response cache bypassed per request — cut total wall time for 12 requests from 41.46s to 30.14s at retrieval concurrency 3, and for 6 requests from 54.61s to 31.60s at conversation concurrency 3, both with 0 errors. Concurrency raises per-request latency; what is validated here is same-batch throughput improvement, not a hardware capacity ceiling.

<details>
<summary><b>Expand the 2026-07-24 four-way same-question rerun</b></summary>

The same fixed 800 questions were rerun across four real integration paths:

<!-- Data source: artifacts/changzhou_dify_4way_800_20260724/comparison_report.json (2026-07-24T04:02:01Z); input SHA-256 5a4c67c42e8f8123774279d46af39ccc793da1b89fdea19a7359f63c8cb2fac2. -->

| Path | Successful execution | Accuracy / usability | Answer clause coverage | Answer evidence-supported | Wrong-evidence rate | Mean / P50 / P95 |
|:---|---:|---:|---:|---:|---:|---:|
| **MimirQ direct retrieval** | **800 / 800** | **99.6% / 100%** | **99.7%** | **99.8%** | 3.0% | **1.15s / 0.83s / 4.00s** |
| **Dify External → MimirQ** | **800 / 800** | 60.8% / 91.4% | 82.9% | **97.3%** | **2.7%** | 6.69s / 6.09s / 11.79s |
| **Dify HTTP → MimirQ** | **800 / 800** | **67.6% / 93.0%** | **85.6%** | 94.6% | 3.6% | 5.20s / 5.04s / 7.19s |
| **Dify native knowledge** | **800 / 800** | 38.8% / 74.9% | 66.0% | 85.6% | 79.1% | 10.34s / 8.28s / 26.49s |

Retrieval evidence coverage on MimirQ's two Dify paths was 99.7% / 96.8%, but generated-answer clause coverage was 82.9% / 85.6%: the main loss is in workflow answer generation, not knowledge recall. All four paths ran the full 800 questions at concurrency 3 in this round. Dify native knowledge does not go through MimirQ; two upstream Nginx 504 responses on its first pass recovered automatically, yielding 800 / 800 final successes.

</details>

[Full methodology, metric definitions, and historical reruns](./docs/benchmarks/changzhou_dify.md) · [Dify integration modes and real workflows](#-dify-integration)

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

> Auth convention: there is no global auth middleware — **every route must explicitly depend on `get_current_account_id`**; routes accessing tenant data must also depend on `get_tenant_id`. See [backend_structure.md](./docs/backend_structure.md).

Enable **Settings → Pages → GitHub Actions** on the repository; pushes to `main` run [`.github/workflows/api-docs.yml`](./.github/workflows/api-docs.yml).

---

## 📦 Deployment Options

From a local look to a production cluster:

| Mode | Command | Description |
|:---:|:---|:---|
| **Standard** | `make up` | Full stack: Postgres + Milvus + Etcd + MinIO + Redis + API + Worker |
| **Standard + Web** | `make up-web` | Recommended first run; initializes local config and starts the complete web stack |
| **Lite Mode** | `make up-lite` | Chroma/FAISS instead of Milvus, no MinIO — quick evaluation |
| **Dev Mode** | `make infra-up` | Infrastructure only, run backend/frontend locally |
| **Helm / K8s** | `helm install` | Production-grade with HPA, PDB, CronJob, PrometheusRule |
| **Parser Extensions** | `make up-etl4llm` | Enable ETL4LLM / Marker / MinerU / PaddleOCR-VL / Qianfan-OCR parsers |

<details>
<summary><b>Production Deployment Tips</b></summary>

```bash
# Edit .env for production settings
# ENV=production
# AUTH_MODE=jwt
# SECRET_KEY=<random string, 32+ chars>
# POSTGRES_PASSWORD=<strong password>

make up-prod
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
| [API overview](./docs/API.md) | OpenAPI SSOT navigation, sharded reference, and handbook entry |
| [Quick Start](./docs/quickstart.md) | Development from source |
| [Runbook](./docs/deployment/runbook.md) | Production operations & troubleshooting |

---

## ✅ Development

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

## 🗺 Roadmap

Delivered capabilities are in the comparison table above. Near-term plans:

- [ ] RAG-specific debugging orchestration (not a general agent canvas)
- [ ] More data-source connectors (Confluence / S3 / Notion)
- [ ] Cross-language retrieval
- [ ] Unified LLM-as-Judge (G-Eval + Self-Consistency)

> The roadmap is tracked publicly in [GitHub Issues](https://github.com/skygazer42/MimirQ/issues) — feature requests and votes welcome.

---

## 🤝 Contributing

Whether it's fixing a typo, filing a bug, or proposing a feature, please read [CONTRIBUTING.md](./.github/CONTRIBUTING.md) first. For the local development flow, see [Quick Start](./docs/quickstart.md), and run `make enterprise-checks` before pushing.

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
