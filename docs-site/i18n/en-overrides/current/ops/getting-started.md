---
sidebar_label: "Quick Start"
sidebar_position: 2
---

# From `.env` to the first login

The repository [`.env.example`](https://github.com/skygazer42/MimirQ/blob/main/.env.example) is the authoritative settings reference.

## 1. Initialize configuration

```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

Without GNU Make, run `python scripts/init_env.py`. This creates only missing `.env` / `web/.env.local` files and generates local secrets without overwriting existing values.

## 2. Set the minimum values

The default SiliconFlow setup needs one value for real LLM and embedding calls:

```dotenv
LLM_API_KEY=<your-siliconflow-api-key>
```

| Capability | Default | Change it when |
|:---|:---|:---|
| LLM | `Qwen/Qwen3-32B` | Another provider requires `LLM_API_BASE` / `LLM_MODEL` |
| Embedding | `BAAI/bge-m3`, reusing the LLM key/base URL | A separate service needs `EMBEDDING_API_KEY` / `EMBEDDING_API_BASE` / `EMBEDDING_MODEL` |
| Reranker | Disabled | Set `ENABLE_RERANKER=true`; a separate service also needs its complete endpoint, key, and model |
| First administrator | Register through the web UI | Set `INITIAL_ADMIN_*` for unattended deployment |

`RERANKER_API_BASE` is the complete rerank request endpoint, not a generic Chat Completions `/v1` URL. The SiliconFlow default is already correct and its key can reuse `LLM_API_KEY`.

## 3. Optional initial owner

```dotenv
INITIAL_ADMIN_EMAIL=owner@example.com
INITIAL_ADMIN_USERNAME=owner
INITIAL_ADMIN_PASSWORD=<strong-password>
# For production, replace the previous line with:
# INITIAL_ADMIN_PASSWORD_FILE=/run/secrets/mimirq_initial_admin_password
```

The two password sources are mutually exclusive. Repeated startup does not rotate the password; an existing different tenant member is never overwritten or elevated. Remove these variables from every replica after bootstrap.

## 4. Choose a startup mode

Docker:

```bash
make up-web
make ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

Host source processes with Docker infrastructure:

```bash
make setup-host
# Run each command in its own terminal
make backend
make web
```

Host mode defaults to `TASK_QUEUE_ENABLED=false`, so the API handles bounded background work in-process. To use a separate queue, set `TASK_QUEUE_ENABLED=true`, restart the API, and run `make worker` in a third terminal; verify it with `make worker-check`. The Docker stack enables the queue by default.

The web UI is available at `http://localhost:3000`.

## 5. Separate model services

```dotenv
LLM_API_BASE=https://llm.example.com/v1
LLM_API_KEY=<llm-key>
LLM_MODEL=<chat-model>

EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_BASE=https://embedding.example.com/v1
EMBEDDING_API_KEY=<embedding-key>
EMBEDDING_MODEL=<embedding-model>

ENABLE_RERANKER=true
RERANKER_PROVIDER=openai
RERANKER_API_BASE=https://reranker.example.com/rerank
RERANKER_API_KEY=<reranker-key>
RERANKER_MODEL=<reranker-model>
```

Inside Docker, `127.0.0.1` is the application container itself. Use a container-reachable LAN address or Docker Desktop's `host.docker.internal`; Linux may require a private Compose host-gateway override. Reindex existing knowledge bases after changing the embedding model, provider, or dimension.

The readiness endpoint verifies infrastructure, not external models. Before release, log in, upload a small document, wait for embedding, and run one cited query.

Next: [Full operation guide](../guide/welcome) · [Configuration](./settings-meta) · [Deployment](./deployment) · [Health checks](./health-probes)
