---
sidebar_label: Overview
sidebar_position: 1
---

# Operations Handbook Overview

This handbook is for **operations engineers, SREs, and platform administrators**, covering MimirQ's deployment methods, health checks, observability, and routine operations.

## Service Overview

| Service | Default Port | Health Check Endpoint | Description |
| --- | --- | --- | --- |
| FastAPI (Main Service) | 8000 | `GET /health` | API gateway entry point |
| Celery Worker | — | Celery inspect ping | Async task execution |
| PostgreSQL | 5432 | `pg_isready` | Relational data storage |
| Milvus | 19530 | gRPC health check | Vector database |
| Redis | 6379 | `redis-cli ping` | Cache & message queue |
| MinIO | 9000 / 9001 | `GET /minio/health/live` | Object storage |

## Infrastructure Dependencies

```mermaid
graph TD
    API["FastAPI :8000"]
    WORKER["Celery Workers"]
    PG["PostgreSQL :5432"]
    MV["Milvus :19530"]
    RD["Redis :6379"]
    OS["MinIO :9000"]

    API --> PG
    API --> MV
    API --> RD
    API --> OS
    WORKER --> PG
    WORKER --> MV
    WORKER --> RD
    WORKER --> OS
    API -.->|"Task Dispatch"| WORKER
```

## Deployment Method Comparison

| Method | Use Case | Pros | Cons |
| --- | --- | --- | --- |
| **Docker Compose** | Local dev, PoC, small teams | One-click start, simple config | No auto-scaling, no HA |
| **Helm / K8s** | Production, multi-tenant | Elastic scaling, rolling updates, health probes | Higher operational complexity |
| **Source Deploy** | Deep debugging, custom dev | Full control | Manual dependency & process management |

:::tip Recommendation
For production, Helm / K8s deployment is recommended, paired with a PostgreSQL HA cluster and Milvus distributed mode. Use Docker Compose for local development.
:::

## Observability

### Prometheus Metrics

MimirQ exposes Prometheus-compatible metrics endpoints:

| Metric Category | Examples | Description |
| --- | --- | --- |
| HTTP Requests | `http_requests_total`, `http_request_duration_seconds` | Grouped by route, method, status code |
| Task Queue | `celery_tasks_total`, `celery_task_duration_seconds` | Grouped by task type, status |
| Database Connections | `sqlalchemy_pool_size`, `sqlalchemy_pool_checkedout` | Connection pool monitoring |
| Vector Search | `milvus_search_duration_seconds` | Search latency |

### Grafana Dashboard

Recommended panels:

- **API Overview** -- Request volume, latency P50/P95/P99, error rate
- **Task Queue** -- Pending count, execution duration, failure rate
- **Storage** -- PostgreSQL connection pool, Milvus query latency, Redis hit rate
- **Resources** -- CPU, memory, disk I/O

See [Observability Configuration](./observability) for details.

## Key Operations

| Operation | Documentation |
| --- | --- |
| Health Probe Configuration | [Health Checks](./health-probes) |
| Monitoring & Alerting | [Observability](./observability) |
| Deployment & Upgrades | [Deployment Guide](./deployment) |
| Configuration & Metadata | [Settings Management](./settings-meta) |

## Daily Inspection Checklist

:::note Daily Checks
1. Verify all service health endpoints return 200
2. Confirm Celery Worker process count matches expectations
3. Check PostgreSQL connection pool utilization < 80%
4. Confirm Milvus collection sync status is normal
5. Check disk usage (MinIO storage / PostgreSQL WAL)
6. Review Grafana alert panel for unresolved alerts
:::

## Key Configuration Files

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Docker Compose orchestration |
| `helm/` | Helm Chart templates |
| `app/core/config.py` | Application config (800+ entries) |
| `alembic.ini` | Database migration config |
| `.env` / `.env.production` | Environment variables |

:::warning Sensitive Configuration
Database passwords, JWT secrets, API keys, and other sensitive configuration should be injected via environment variables or Kubernetes Secrets. Never commit them to the code repository.
:::

## Related Links

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [Backend Overview](../backend/welcome)
- [Frontend Overview](../frontend/welcome)
- [Integration & E2E Overview](../integration/welcome)
- [SRE / Ops Role Guide](../integration/roles/sre-ops)
