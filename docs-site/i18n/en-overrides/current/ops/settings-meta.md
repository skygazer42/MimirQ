---
sidebar_label: "Configuration"
sidebar_position: 5
---

# Runtime configuration

MimirQ reads process environment variables and the repository-root `.env` through Pydantic Settings. The authoritative definitions are [`.env.example`](https://github.com/skygazer42/MimirQ/blob/main/.env.example) and `app/core/config.py`.

`make init` creates only missing `.env` / `web/.env.local` files and generates `SECRET_KEY` plus `MARKDOWN_IMAGE_PROXY_SECRET`. It does not overwrite existing values.

## Minimum real-model path

```dotenv
LLM_API_KEY=<your-siliconflow-api-key>
```

| Variable | Default / fallback | Purpose |
|:---|:---|:---|
| `LLM_API_BASE` | `https://api.siliconflow.cn/v1` | OpenAI-compatible LLM base URL |
| `LLM_MODEL` | `Qwen/Qwen3-32B` | Main chat model |
| `EMBEDDING_PROVIDER` | `openai_compatible` | Embedding implementation |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Default embedding model |
| `EMBEDDING_API_KEY` | Reuses `LLM_API_KEY` when empty | Set for a separate service |
| `EMBEDDING_API_BASE` | Reuses `LLM_API_BASE` when empty | Set for a separate service |
| `ENABLE_RERANKER` | `false` | Enables reranking when `true` |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | Default reranker model |
| `RERANKER_API_KEY` | Reuses `LLM_API_KEY` when empty | May share LLM credentials |
| `RERANKER_API_BASE` | `https://api.siliconflow.cn/v1/rerank` | Complete rerank request endpoint |

See [Quick Start](./getting-started) for separate-service examples. Reindex existing knowledge bases after changing the embedding model, provider, or dimension.

## Authentication and initial owner

`AUTH_MODE` defaults to `jwt`; `header` is only for controlled local debugging and is rejected in production. `make init` generates `SECRET_KEY`.

For unattended bootstrap, set `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_USERNAME`, and exactly one of `INITIAL_ADMIN_PASSWORD` or `INITIAL_ADMIN_PASSWORD_FILE`. Every initial replica must use identical values; remove them everywhere after bootstrap. `INITIAL_REGISTRATION_TOKEN` remains an optional protected manual-registration fallback.

## Host and Docker dependency variables

| Dependency | Host process | Compose container |
|:---|:---|:---|
| PostgreSQL | `DATABASE_URL` | Composed from `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` |
| Redis | `REDIS_URL` | `REDIS_URL_DOCKER` |
| Milvus | `MILVUS_HOST` / `MILVUS_PORT` | `MILVUS_HOST_DOCKER` / `MILVUS_PORT_DOCKER` |
| MinIO | `MINIO_*` | `MINIO_*_DOCKER` |
| Task queue | `TASK_QUEUE_ENABLED` | `TASK_QUEUE_ENABLED_DOCKER` |

Host mode defaults to `TASK_QUEUE_ENABLED=false` and handles bounded background work in the API process. Setting it to `true` requires `make worker`; Docker enables the queue and starts the worker by default. Do not expose Docker-internal service names to browsers or host processes.

## Frontend variables

`NEXT_PUBLIC_API_URL` is the host/browser backend URL. Docker Web normally uses same-origin `NEXT_PUBLIC_API_URL_DOCKER=/`, while SSR uses `API_INTERNAL_URL_DOCKER`. Every `NEXT_PUBLIC_*` value is public client-side configuration: never place secrets there, and rebuild production frontend images after changing it.

Backend `.env` values are loaded when API/worker processes start. The web Settings API manages only explicitly supported business settings and does not override arbitrary environment variables. Changing `SECRET_KEY` invalidates existing local JWTs.

Use Docker Secrets, Kubernetes Secrets, or an external secret manager for production database credentials, object-store credentials, model keys, and administrator passwords.

Related: [Quick Start](./getting-started) · [Deployment](./deployment) · [Health checks](./health-probes)
