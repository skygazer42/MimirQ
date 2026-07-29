---
sidebar_label: "Deployment"
sidebar_position: 4
---

# Deployment

MimirQ provides two ready-to-use paths: a complete Docker Web stack, or host API/Web processes with an optional Arq worker backed by Docker infrastructure. Kubernetes production deployments use the Helm chart in this repository.

Complete the [Quick Start](./getting-started) model and initial-owner configuration first.

## Docker stack

```bash
make init
# Edit .env and set at least LLM_API_KEY for real model calls
make up-web
make ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

`make up-web` starts Next.js, FastAPI, the Arq worker, PostgreSQL, Milvus, Etcd, Redis, and MinIO using the maintained Compose files. Do not replace them with a generic online Compose example or expose Docker-internal service names to browsers.

```bash
make ps
make logs
make down
```

Heavy parser profiles are optional and remain stopped by default. See the repository [Docker Compose guide](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md) for their exact commands.

### Stop or rebuild from scratch

| Goal | Command | Named volumes | Service images |
|:---|:---|:---:|:---:|
| Stop and keep data | `make down` | Kept | Kept |
| Rebuild from empty data | `make docker-reset` | Deleted | Kept |
| Rebuild images and data | `make docker-purge` | Deleted | Deleted |

The last two operations are destructive. MimirQ defaults to an isolated `mimirq` Compose project name, so Dify and other stacks are not treated as orphans. These commands do not delete `.env` or source files. See the [Docker Compose guide](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md#4-%E6%95%B0%E6%8D%AE%E5%8D%B7%E4%B8%8E%E6%B8%85%E7%90%86) for the exact database, upload, vector-index, parser-cache, and shared-image impact.

### Ownership checks and recovery

Check resource ownership in a terminal or PowerShell before deletion:

```powershell
docker compose ls
docker ps -a --filter "label=com.docker.compose.project=mimirq"
```

Only MimirQ services should appear under the `mimirq` project. Compose `[+] Running N/N` counts
container, volume, image, and network operations; it does not mean that N containers were running.
The standard Web stack contains eight containers when optional parsers are disabled.

If an older cleanup command removed Dify containers, stop immediately and do not run
`docker system prune` or `docker volume prune`. From the original Dify Compose directory, reuse its
original project name and run `docker compose up -d`. Verify Dify data before running `git pull`,
`make up-web`, `make ps`, and `make api-ping` from MimirQ. Legacy MimirQ `docker_*` volumes are not
automatically migrated to the new `mimirq_*` volumes; back up and migrate data before deleting them.
See the repository [Docker Compose guide](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md#4-%E6%95%B0%E6%8D%AE%E5%8D%B7%E4%B8%8E%E6%B8%85%E7%90%86) for complete PowerShell, project-name, and recovery steps.

## Host source processes

```bash
make init
# Edit .env
make setup-host
```

Run each process in its own terminal:

```bash
make backend
make web
```

Host mode defaults to `TASK_QUEUE_ENABLED=false`, so no separate worker is required. To use a separate queue, set `TASK_QUEUE_ENABLED=true`, restart the API, and run:

```bash
make worker
make worker-check
```

```bash
make infra-ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

After stopping the host processes, run `make infra-down`.

Host processes can use published `127.0.0.1` ports. Inside a container, `127.0.0.1` means that container; use Compose service names for infrastructure and a container-reachable host/LAN address for host model services. `DOCKER_BUILD_NETWORK=host` affects image builds only, not runtime model traffic.

## Production Compose

Production requires strong JWT, PostgreSQL, and object-store secrets; external schema migrations; a trusted tenant source; restricted CORS/hosts/proxy settings; and a secret manager. The supported order is:

```bash
make infra-up
make db-upgrade
make up-prod-web
make ps
```

Follow every guardrail in the [Docker Compose guide](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md), not only this summary.

## Helm / Kubernetes

The chart at `deploy/helm/mimirq` deploys the API and Arq worker; external infrastructure supplies PostgreSQL, Redis, the vector store, and object storage.

```bash
helm lint deploy/helm/mimirq
helm template mimirq deploy/helm/mimirq -f <values-file>
helm upgrade --install mimirq deploy/helm/mimirq \
  --namespace mimirq --create-namespace \
  -f <values-file>
```

Prefer `existingSecretName` with an externally managed Secret. See the complete [Helm guide](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/helm.md) for migrations, NetworkPolicy, multi-replica guards, and rollback.

## Acceptance check

```bash
curl -f http://localhost:8000/api/v1/health
curl -f http://localhost:8000/api/v1/health/ready
```

Readiness covers infrastructure, not external models. Also log in, upload a small document, wait for indexing, and run one cited query.

Related: [Configuration](./settings-meta) · [Health checks](./health-probes) · [Observability](./observability)
