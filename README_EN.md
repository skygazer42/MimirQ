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

## 🤔 Why another RAG project?

Most RAG tools just shrug when you ask "**why did it answer wrong?**" — you can't see how the document was chunked, what retrieval actually matched, or which sentence the answer was grounded in. Tuning feels like opening blind boxes.

**MimirQ opens every one of those boxes:**

- 📐 **WYSIWYG chunking** — upload a doc and preview chunk boundaries, splits, and scores in real time; tweak a parameter and it re-computes instantly. No more re-ingesting just to experiment.
- 🔬 **Fully traceable retrieval** — every Q&A carries a trace: which channels ran, which passages were hit, how reranking reordered them, and which source sentence each citation came from.
- 📊 **Quality measured in numbers** — built-in RAGAS evaluation + regression gates + a leaderboard, so every change is compared against a baseline instead of "it feels better now."
- 🇨🇳 **Chinese as a first-class citizen** — from Chinese tokenization and mixed-script PII redaction to industry rule packs for government/finance scenarios. Not an English project with Chinese bolted on.

> In one line: **MimirQ turns a "demo that runs" into a knowledge base system you dare to ship — and can root-cause when something goes wrong.**

---

## 📍 Proven in a Real Deployment

MimirQ is not a lab demo — it has been deployed in a **municipal government Q&A assistant**, spanning 7 district-level plus city-level real knowledge bases, and validated with an **800-question government benchmark using deterministic scoring (no LLM judge, fixed parameters)**.

<!-- Source: artifacts/dify_3way_benchmark_*_20260713/ (gitignored, kept on disk). All figures below are measured. -->

| Metric (800-question gov benchmark · same-params rerun, 2026-07-13) | Result |
|:---|:---|
| **Complete-run success rate** | **800 / 800** (old pipeline: 687 / 800) |
| **Paired mean latency (687 shared cases)** | **5.1 s** ← was 35.1 s (**↓ 85.5%**) |
| **Paired median latency (687 shared cases)** | **4.9 s** ← was 34.8 s (↓ 86.1%) |
| **Full 800-case mean latency** | **5.0 s** |
| **Answer usability rate** | 86.4% |
| **Answer clause coverage** | 80.2% |
| Scoring method | Deterministic evidence-clause matching with fixed parameters |

> 📝 **An honest note**: the firm conclusion of this same-params rerun is a **dramatic latency drop (35s → 5s) with all 800 questions passing**. Answer quality figures are current absolute values and have **not** yet surpassed the old version in a statistical sense (district-level +3pp, city-level -15.7pp due to an output-style change we're restoring). The full report and per-question results remain in the test machine's local `artifacts/` directory and are not published with this repository. Reproducible Chinese public benchmarks (MIRACL-zh / CFEVER) are described in the [Public Benchmarks guide](./docs/guides/public_benchmarks_zh.md).

**🔌 Plugs into the Dify ecosystem**: MimirQ exposes a [Dify External Knowledge API](./docs/guides/pipeline_plugins.md)-compatible endpoint, so it can serve as an **external knowledge base** wired directly into Dify workflows — existing Dify apps get MimirQ's hybrid retrieval, KG, and citation tracing with zero changes. The 800-question benchmark above was in fact run through the Dify HTTP link straight into MimirQ.

---

## 📑 Table of Contents

- [Why another RAG project?](#-why-another-rag-project)
- [Proven in a Real Deployment](#-proven-in-a-real-deployment)
- [Key Features](#-key-features)
- [Project Scale](#-project-scale)
- [System Architecture](#-system-architecture)
- [RAG Pipeline](#-rag-pipeline)
- [Tech Stack](#-tech-stack)
- [Quick Start](#-quick-start)
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

## ✨ Key Features

<div align="center">
  <img src="./docs/images/features.svg" alt="MimirQ Features" width="100%"/>
</div>

<br/>

<table>
  <tr>
    <td width="50%">

**🔍 Hybrid Retrieval Engine**

Out-of-the-box **Vector semantic + BM25 keyword** dual channels with RRF fusion — balancing "gets the meaning" and "matches the exact keyword." When you need stronger recall, turn on **SPLADE sparse retrieval, ColBERT late-interaction reranking, and LTR** — full capability, lean defaults.

</td>
    <td width="50%">

**📐 Visual Chunk Preview**

Preview on upload — no black-box chunking. Multiple strategies side by side (recursive / semantic / hierarchical / parent-child), visible boundaries, transparent scores, instant re-compute on parameter change. WYSIWYG.
→ [Guide](./docs/guides/chunk_preview.md)

</td>
  </tr>
  <tr>
    <td>

**🔄 Multi-Modal Document Parsing**

**30+ parsing backends** covering PDF / Markdown / HTML / mixed text-image. Integrates PyMuPDF, MinerU, ETL4LLM, Marker, Docling, PaddleOCR-VL, olmOCR, Qianfan-OCR — handles Chinese scans and complex layouts, extensible by design.

</td>
    <td>

**💬 RAG-Powered Q&A**

Streaming responses, sentence-level citation tracing, multi-turn memory. Built on LangChain Runnable architecture, with an optional LangGraph Agent pipeline (self-correcting strategies: Self-RAG / CRAG / FLARE).

</td>
  </tr>
  <tr>
    <td>

**🕸️ Knowledge Graph (KG)**

Auto-extracts entities / events / relations from documents; Force Graph visualization, multi-hop search, community detection. Going further: **precise snapshot diff + BFS impact analysis** — change one piece of knowledge and see which downstream nodes it touches. Feeds back into RAG for query expansion.
→ [Guide](./docs/guides/knowledge_graph.md)

</td>
    <td>

**📊 Evaluation Governance**

Built-in RAGAS (Faithfulness / Relevancy / Context Precision) + **regression gates + leaderboard + statistical significance tests** (t-test / Wilcoxon / Bootstrap). Every change gets a baseline comparison — quality proven in numbers.

</td>
  </tr>
  <tr>
    <td>

**🔒 Enterprise Security**

Document-level ACL (owner / member / team / inherited) + retrieval-side permission trimming to prevent unauthorized citations; RBAC + SCIM/SSO + SAML single sign-on; Chinese-scenario PII redaction, Input/Output guards, per-hop SSRF validation.
→ [Guide](./docs/guides/document_acl.md)

</td>
    <td>

**📑 Document Versioning**

Each document forms an independent version per pipeline config (`pipeline_hash`) — view, activate/rollback, delete history, switch and preview in the UI. Tune fearlessly; you can always return to the last version.
→ [Guide](./docs/guides/document_versions.md)

</td>
  </tr>
  <tr>
    <td>

**🔗 URL Import & Connectors**

Server-side URL fetching for ingestion, with batch import carrying status / stats / error attribution (Connector Run). Built-in SSRF protection and safety switches for confident public-web crawling.
→ [Guide](./docs/guides/url_ingest.md)

</td>
    <td>

**🏢 Production-Grade Architecture**

Milvus billion-scale vectors, PostgreSQL persistence, arq async task queue, OpenAI-compatible API. Docker Compose / Helm / K8s multi-form deployment, CI/CD + Prometheus + Grafana observability out of the box.

</td>
  </tr>
  <tr>
    <td>

**🔌 Dify Ecosystem Integration**

A Dify External Knowledge API-compatible endpoint lets MimirQ serve as an external knowledge base wired straight into Dify workflows. Existing Dify apps get MimirQ's hybrid retrieval, KG, and citation tracing with zero changes.
→ [Guide](./docs/guides/pipeline_plugins.md)

</td>
    <td>

**🏛️ Government / Vertical-Scenario Ready**

For serious scenarios like government and finance: built-in readiness gates, evidence audits, industry rule packs, and offline redaction — validated in a municipal government Q&A assistant.

</td>
  </tr>
</table>

---

## 📈 Project Scale

Not a toy — this is a full-stack system built with serious engineering:

| Dimension | Scale |
|:---|:---|
| **Backend code** | ~300K lines of first-party Python (excluding vendored parsers) |
| **Frontend code** | ~200K lines of TypeScript / React |
| **Parsing backends** | 30+ (PDF / OCR / layout / vision) |
| **Chunking strategies** | 78 (recursive / semantic / hierarchical / parent-child / RAPTOR / late chunking …) |
| **Rerankers** | 15 (RRF / ColBERT / LTR / LLM-based / long-context …) |
| **Tests** | 106 backend test files — 576 backend cases + 61 frontend cases + CI contract gates |

---

## 🔎 System Architecture

<div align="center">
  <img src="./docs/images/architecture.svg" alt="MimirQ Architecture" width="100%"/>
</div>

---

## 🔄 RAG Pipeline

<div align="center">
  <img src="./docs/images/rag-pipeline.svg" alt="RAG Pipeline" width="100%"/>
</div>

<details>
<summary><b>Pipeline Details</b></summary>

### Ingestion Pipeline

```
Document Upload → Format Parsing (PyMuPDF/MinerU/ETL4LLM/…) → Smart Chunking (Recursive/Semantic/Parent-Child)
→ Embedding (OpenAI/Ollama/Local) → Multi-Index Storage (Milvus + BM25, optional SPLADE)
→ [Optional] Knowledge Graph Extraction (Entity/Relation/Event)
```

### Retrieval & Generation Pipeline

```
User Query → Query Embedding → Hybrid Retrieval Top-K (Vector + BM25, optional SPLADE)
→ Fusion & Reranking (RRF, optional ColBERT/LTR) → Permission Trimming (Security Trimming)
→ Context Assembly → LLM Generation → Streaming Response + Sentence-level Citations + Retrieval Trace
```

> 💡 Advanced channels — SPLADE / ColBERT / LTR / HyDE / multi-query rewriting — are **off by default** and enabled explicitly in config. This keeps the out-of-the-box path predictable in latency and cost, with advanced capability available on demand.

</details>

---

## 🛠 Tech Stack

<div align="center">
  <img src="./docs/images/tech-stack.svg" alt="Tech Stack" width="100%"/>
</div>

<br/>

| Layer | Technologies |
|:---:|:---|
| **Frontend** | Next.js 14 (App Router) · React 19 · TypeScript · Tailwind CSS · shadcn/ui · Zustand · TanStack Query · Radix UI · Recharts · react-force-graph |
| **Backend** | FastAPI · Python 3.11+ · LangChain 1.x · LangGraph · SQLAlchemy · Alembic · arq Worker · RAGAS |
| **Retrieval** | Milvus (default) / FAISS / Chroma · BM25 · SPLADE · ColBERT · LTR · RRF Fusion |
| **Parsing** | PyMuPDF · MinerU · ETL4LLM · Marker · Docling · PaddleOCR-VL · olmOCR · Qianfan-OCR |
| **Storage** | PostgreSQL 15 · Redis 7 · MinIO · etcd |
| **Deployment** | Docker Compose · Helm / K8s · Prometheus · Grafana · GitHub Actions CI |

---

## 🚀 Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 20.10+ & [Docker Compose](https://docs.docker.com/compose/install/) 2.0+
- At least 4 CPU cores / 16 GB RAM / 50 GB disk

### One-Command Setup

```bash
git clone https://github.com/skygazer42/MimirQ.git
cd MimirQ

# 1. Generate local config files and a JWT SECRET_KEY
make init
# Windows (no make): python scripts/init_env.py

# 2. Start backend + infrastructure (Postgres / Milvus / MinIO / Redis)
make up

# 3. [Optional] Start frontend (Next.js production build)
make up-web
```

> Want a lighter first look? `make up-lite` swaps Milvus for Chroma/FAISS and skips MinIO — up in minutes.

The first Docker build downloads and verifies a pinned DeepDoc model bundle. Run `make models` before using local source-based parsing.

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
| **Standard + Web** | `make up-web` | Standard + Next.js frontend |
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

[FastAPI](https://fastapi.tiangolo.com/) · [LangChain](https://langchain.com/) · [LangGraph](https://langchain-ai.github.io/langgraph/) · [Milvus](https://milvus.io/) · [Next.js](https://nextjs.org/) · [PostgreSQL](https://www.postgresql.org/) · [RAGAS](https://docs.ragas.io/) · [PyMuPDF](https://pymupdf.readthedocs.io/) · [MinerU](https://github.com/opendatalab/MinerU) · [Tailwind CSS](https://tailwindcss.com/) · [shadcn/ui](https://ui.shadcn.com/)

---

<div align="center">

**If MimirQ took your RAG from "it runs" to "I'd ship it," please give us a ⭐ Star!**

Every star is fuel for us to keep opening the black box.

[![Star History Chart](https://api.star-history.com/svg?repos=skygazer42/MimirQ&type=Date)](https://star-history.com/#skygazer42/MimirQ&Date)

</div>
