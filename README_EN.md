<div align="center">

# 🔮 MimirQ

### Next‑Gen AI Knowledge Base (RAG) System

FastAPI + LangChain/LangGraph backend, Next.js 14 frontend, with PostgreSQL + Milvus + BM25 hybrid retrieval.

[English](./README_EN.md) | [简体中文](./README.md)

</div>

---

## What It Is

MimirQ is a full‑stack knowledge base Q&A system built around RAG (Retrieval‑Augmented Generation). It supports:

- Document ingestion (PDF/Markdown/TXT and more)
- URL ingestion (server-side fetch) and batch URL import via connector runs (optional; gated by `URL_INGEST_ENABLED`)
- Chunking + embeddings + indexing
- Hybrid retrieval (Vector + BM25)
- Streaming chat with citations
- Document-level access control (security trimming) on top of dataset permissions
- Optional MinIO image storage and background workers (Redis + arq)

## Tech Stack

- **Frontend**: Next.js 14 (App Router), TypeScript, Tailwind, shadcn/ui
- **Backend**: FastAPI (Python 3.11+), LangChain 1.x, LangGraph
- **Storage**: PostgreSQL, Milvus, BM25 index, MinIO (optional)
- **Queue (optional)**: Redis + arq worker for async ingestion

## Quick Start (Docker Compose)

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Node.js 20+ (optional, for local frontend dev)
- Python 3.11+ (optional, for local backend dev)

### 1) Configure env files

```bash
# Create local env files (.env / docker/.env / web/.env.local) without overwriting:
make init

# Windows (no `make`) alternative:
python scripts/init_env.py

# Or copy manually:
# cp docker/.env.example docker/.env
# cp web/.env.local.example web/.env.local
```

Edit `docker/.env` and set your LLM/Embedding keys (OpenAI-compatible API is supported).

### 2) Start backend services

```bash
make up
make ps

# or
cd docker
docker compose up -d --build
docker compose ps
cd ..

# production (recommended)
# edit docker/.env: ENV=production, AUTH_MODE=jwt, SECRET_KEY (>=32), POSTGRES_PASSWORD, then run the same `make up`
```

### 3) Start frontend (optional)

```bash
# Option A) Docker (production build)
make up-web

# Option B) Local dev
# cd web; pnpm install; pnpm dev
```

### 4) Open

- Backend API docs: `http://localhost:8000/docs`
- Frontend UI: `http://localhost:3000`

## Python Dependencies (optional)

- Unified deps: `pip install -r requirements.txt`

## Health Checks

- Lightweight: `GET /api/v1/health`
- Readiness probe: `GET /api/v1/health/ready` (returns `503` when deps are down)
- Detailed status: `GET /health`

## Docs

See `docs/README.md` for docs and guides.
- Chunk preview guide (CN): `docs/guides/chunk_preview.md`
- URL ingestion (CN): `docs/guides/url_ingest.md`
- Document ACL / security trimming (CN): `docs/guides/document_acl.md`

## Acknowledgements

This project is inspired by and references ideas from the following open source projects (no official affiliation):

- [Dify](https://github.com/langgenius/dify)
- [RAGFlow](https://github.com/infiniflow/ragflow)
- [Bisheng](https://github.com/dataelement/bisheng)
