# Ops Templates (Prometheus + Grafana)

This folder contains **copy-pasteable** operational templates for MimirQ:

- `prometheus-rule-mimirq.yaml`: a `PrometheusRule` (Kubernetes / Prometheus Operator) with baseline alerts
- `grafana-dashboard-mimirq.json`: a Grafana dashboard JSON for an “Ops Overview” view

## Prerequisites

1. Backend metrics enabled:
   - `PROMETHEUS_ENABLED=true`
   - `/metrics` is exposed (see `app/api/v1/metrics.py`)
2. Prometheus scrape configured:
   - For Kubernetes: `deploy/helm/mimirq/templates/servicemonitor.yaml` (requires Prometheus Operator)

## What’s covered

Alerts and dashboards are aligned to the built-in metrics shipped by MimirQ:

- **HTTP**
  - `http_requests_total`
  - `http_request_duration_seconds`
- **RAG SLIs (chat path)**
  - `rag_retrieval_elapsed_seconds`
  - `rag_zero_hit_total`
  - `rag_errors_total`
- **Evidence API (retrieval-only)**
  - `rag_evidence_retrieve_duration_seconds`
- **Ingestion**
  - `ingestion_runs_total`
  - `ingestion_run_duration_seconds`
- **Task queue (best-effort)**
  - `task_queue_broker_up`
  - `task_queue_depth`
  - `task_queue_workers_active`

## How to use

### PrometheusRule (K8s)

Apply the rule to the same namespace where Prometheus Operator watches for rules:

```bash
kubectl apply -f docs/ops/templates/prometheus-rule-mimirq.yaml
```

Notes:
- Thresholds are intentionally conservative defaults; tune to your workload.
- Alerts are intentionally low-cardinality (no per-tenant labels by default).

### Grafana Dashboard

1. Grafana → Dashboards → New → **Import**
2. Upload `docs/ops/templates/grafana-dashboard-mimirq.json`
3. Select your Prometheus datasource when prompted (`DS_PROMETHEUS`)

## Tuning notes

- If you enable tenant/dataset labels for RAG metrics (`PROMETHEUS_RAG_LABEL_TENANT_ID`, `PROMETHEUS_RAG_LABEL_DATASET_ID`),
  consider scoping alert queries (or using separate dashboards) to avoid noisy global alerts.

