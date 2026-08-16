# Helm / Kubernetes 部署指南（MimirQ）

本指南提供一个 **最小可用** 的 Helm Chart，用于在 Kubernetes 中部署：

- `mimirq-api`（FastAPI 服务）
- `mimirq-worker`（Arq 后台 worker）

本 Chart **默认不安装数据库/向量库/Redis/MinIO**，而是以“企业常见做法”对齐：依赖外部基础设施（自建或云托管）。

Chart 目录：`deploy/helm/mimirq`

上线前建议对照交付验收清单：

- `docs/deployment/private_delivery_checklist.md`

---

## 1) 前置条件

- Kubernetes 1.22+（建议更高）
- Helm 3.x
- 你已准备好（或计划自建）以下依赖：
  - Postgres（必需）
  - Redis（建议：用于任务队列/缓存）
  - 向量库（Milvus / Chroma 等，取决于 `VECTOR_BACKEND`）
  - MinIO（可选：图片/文档对象存储，取决于 `MINIO_ENABLED` / `MINIO_DOCUMENTS_ENABLED`）

后端就绪探针（readiness）使用：

- `GET /api/v1/health/ready`（依赖可用且外部管理的数据库位于当前镜像 Alembic head 时返回 200，否则 503）

---

## 2) 构建并推送镜像

Chart 默认使用 `mimirq/mimirq:<tag>`，你需要替换为自己的镜像仓库：

```bash
docker build -f docker/Dockerfile -t <your-registry>/mimirq:<tag> .
docker push <your-registry>/mimirq:<tag>
```

---

## 3) 准备 Kubernetes Secret（推荐：外部创建）

**强烈建议**：在集群外部（Vault/KMS/External Secrets Operator）创建 Secret，并在 values 里通过 `existingSecretName` 引用。

最小示例（仅用于测试环境）：

```bash
kubectl create namespace mimirq

kubectl -n mimirq create secret generic mimirq-env \
  --from-literal=ENV=production \
  --from-literal=AUTH_MODE=jwt \
  --from-literal=SECRET_KEY="<>=32 chars random>" \
  --from-literal=JWT_TENANT_CLAIM="tenant_id" \
  --from-literal=CORS_ORIGINS="https://mimirq.example.com" \
  --from-literal=DATABASE_URL="postgresql://user:pass@postgres:5432/mimirq" \
  --from-literal=DB_CREATE_ALL_ON_STARTUP=false \
  --from-literal=DB_RUNTIME_MIGRATIONS_ENABLED=false \
  --from-literal=REDIS_URL="redis://redis:6379/0" \
  --from-literal=VECTOR_BACKEND="milvus" \
  --from-literal=MILVUS_HOST="milvus" \
  --from-literal=MILVUS_PORT="19530" \
  --from-literal=UPLOAD_DEDUP_ENABLED=true \
  --from-literal=RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED=true \
  --from-literal=RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY=3 \
  --from-literal=MINIO_ENABLED=true \
  --from-literal=MINIO_DOCUMENTS_ENABLED=true \
  --from-literal=MINIO_ACCESS_KEY="<strong-minio-access-key>" \
  --from-literal=MINIO_SECRET_KEY="<strong-minio-secret-key>" \
  --from-literal=LLM_API_KEY="<your-key>" \
  --from-literal=UPLOAD_DIR="/data/uploads"
```

---

## 4) values 覆盖（生产建议）

创建 `values-prod.yaml`：

```yaml
image:
  repository: <your-registry>/mimirq
  tag: "<tag>"

existingSecretName: mimirq-env

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: mimirq.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: mimirq-example-com-tls
      hosts:
        - mimirq.example.com

runtimeGuards:
  environment: "production"
  vectorBackend: "milvus"
  minioEnabled: "true"
  minioDocumentsEnabled: "true"
  dbCreateAllOnStartup: "false"
  dbRuntimeMigrationsEnabled: "false"

networkPolicy:
  enabled: true
  api:
    ingress:
      allowSameNamespace: false
      extraFrom:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress-nginx
          podSelector:
            matchLabels:
              app.kubernetes.io/name: ingress-nginx
  worker:
    ingress:
      allowSameNamespace: false
      extraFrom: []
  egress:
    restrict: true
    allowDNS: true
    rules:
      - to:
          - namespaceSelector:
              matchLabels:
                kubernetes.io/metadata.name: data
            podSelector:
              matchLabels:
                app.kubernetes.io/name: postgres
        ports:
          - protocol: TCP
            port: 5432
      - to:
          - ipBlock:
              cidr: 198.51.100.10/32
        ports:
          - protocol: TCP
            port: 443

api:
  replicas: 2
  extraEnv:
    - name: ENV
      value: "production"
    - name: DB_CREATE_ALL_ON_STARTUP
      value: "false"
    - name: DB_RUNTIME_MIGRATIONS_ENABLED
      value: "false"
    - name: RATE_LIMIT_REDIS_ENABLED
      value: "true"
    - name: BM25_INDEX_ENABLED
      value: "false"
    - name: UPLOAD_DEDUP_ENABLED
      value: "true"
    - name: RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED
      value: "true"
    - name: RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY
      value: "3"

worker:
  replicas: 2
  extraEnv:
    - name: ENV
      value: "production"
    - name: DB_CREATE_ALL_ON_STARTUP
      value: "false"
    - name: DB_RUNTIME_MIGRATIONS_ENABLED
      value: "false"
    - name: UPLOAD_DEDUP_ENABLED
      value: "true"
    - name: RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED
      value: "true"
    - name: RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY
      value: "3"

persistence:
  uploads:
    enabled: true
    size: 50Gi

migrations:
  enabled: true
```

说明：

- `runtimeGuards.*` 只用于 Helm 渲染期校验。使用 `existingSecretName` 时，Chart 读不到外部 Secret，必须靠这些提示值判断多副本部署边界。
- 生产基线默认显式开启 `UPLOAD_DEDUP_ENABLED=true` 与 `RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED=true`，并把 `RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY` 设为保守的 `3`；如需更高吞吐，再按实例 CPU、上游模型延迟与 Redis 观测结果上调。
- 多副本 API / worker 会 fail-fast 要求：
  - `ENV=production`
  - `DB_CREATE_ALL_ON_STARTUP=false`
  - `DB_RUNTIME_MIGRATIONS_ENABLED=false`
  - 不使用 `VECTOR_BACKEND=faiss/chroma`
  - 若未启用 `MINIO_ENABLED=true` 且 `MINIO_DOCUMENTS_ENABLED=true`，则 `persistence.uploads.accessModes` 必须包含 `ReadWriteMany`
- `migrations.enabled=true` 只支持配合 `existingSecretName` 使用；pre-install hook 早于 chart 管理的 Secret 创建，不能安全依赖内置 Secret。
- API 在 `DB_CREATE_ALL_ON_STARTUP=false` 且 `DB_RUNTIME_MIGRATIONS_ENABLED=false` 时会校验 `alembic_version`；迁移 Job 未执行或版本落后时 readiness 会保持 503，不会让 schema 不兼容的 Pod 接流量。

你也可以直接从内置示例开始（推荐先复制一份再改）：

- `deploy/helm/mimirq/examples/values-prod.yaml`
- `deploy/helm/mimirq/examples/values-hardened.yaml`

推荐顺序：

- 先复制 `values-prod.yaml` 作为可运行生产基线。
- 再按需合并 `values-hardened.yaml` 中的安全加固项。
- 不要直接把 chart 默认值当成生产 values；默认值保留了单机/开发便利。

生产环境至少还要确认：

- 外部 Secret 中已提供强 `SECRET_KEY`、Postgres 凭据、MinIO 凭据、`JWT_TENANT_CLAIM`、`CORS_ORIGINS`
- 若要临时回退旧行为，可把 `UPLOAD_DEDUP_ENABLED=false` 或 `RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED=false` 放进 Secret / `extraEnv`
- `ingress.tls` 已配置真实证书
- `networkPolicy.egress.rules` 已替换为你集群里的真实依赖 allowlist

如果你要配置 Ingress：

```yaml
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: mimirq.example.com
      paths:
        - path: /
          pathType: Prefix
```

### 4.1 安全基线

Chart 默认启用 `security.hardened=true`，为官方非 root 镜像合并安全的 `securityContext`（非 root、drop capabilities、seccomp 等）。如果自定义镜像与这些约束不兼容，可显式设置 `security.hardened=false`；`readOnlyRootFilesystem` 仍不会被默认开启。

常见配置示例：

```yaml
security:
  hardened: true
  # 若你启用 readOnlyRootFilesystem（自行在 *securityContext 里设置），建议开启：
  tmpEmptyDir:
    enabled: true

# 默认值为 false：不挂载 K8s ServiceAccount token（更安全）。
automountServiceAccountToken: false

# 可选：使用 chart 创建专用 SA（或引用已有 SA）
serviceAccount:
  create: true
  # name: "mimirq-sa"

# 可选：限制网络访问（生产推荐开启；见 4.3）
networkPolicy:
  enabled: true
```

### 4.2 可观测（Prometheus / Grafana，可选）

前提：后端必须开启 `/metrics`（通过 env）：

- `PROMETHEUS_ENABLED=true`（推荐由外部 Secret 提供）
- `METRICS_BEARER_TOKEN=<token>`（推荐由外部 Secret 提供；支持原始 token 或 `sha256:<hex>`）

Kubernetes / Prometheus Operator 环境下，你可以用 Helm 一键启用：

```yaml
prometheus:
  serviceMonitor:
    enabled: true

  # PrometheusRule CRD（告警规则）
  prometheusRule:
    enabled: true
    # 你的 Prometheus Operator 可能用 label selector 选择规则；
    # 这里填入它要求的 labels（如 release: prometheus）。
    additionalLabels: {}

grafana:
  dashboard:
    enabled: true
    # Grafana sidecar 通常通过 label 发现 dashboards（如 grafana_dashboard=1）。
    labels:
      grafana_dashboard: "1"
```

### 4.3 NetworkPolicy（生产推荐）

当 `networkPolicy.enabled=true` 时：

- `api`：默认允许 **同 namespace** 的 ingress（你需要根据 Ingress Controller 所在 namespace 调整）
- `worker`：默认拒绝 ingress
- `egress`：只有 `networkPolicy.egress.restrict=true` 才会变成 allowlist 模式；生产建议开启并补全规则

更多配方与注意事项见：`docs/deployment/security_baseline.md`。

---

### 4.4 周期巡检 CronJobs（Periodic Audits / Access Review，可选）

Chart 内置了一组 **可选 CronJob**，用于把“健康巡检/合规审查”做成可复用的运维自动化：

- `cronjobs.indexAudit`：每日 index 一致性巡检汇总（写入审计日志：`observability.index_audit.daily`）
- `cronjobs.evidenceDriftAudit`：每日 evidence reference drift 巡检汇总（写入审计日志：`evidence.drift_audit.daily`）
- `cronjobs.accessReviewSummary`：每日 access review 汇总（写入审计日志：`compliance.access_review.daily`）

特点：

- **默认 PII-safe**：只写入计数/ID（无文档内容、无 query 原文）。
- **Bounded**：每次运行都有上限参数（如 `maxDatasets` / `maxCheckIds`），避免无限扫描。
- **审计可追溯**：结果会进入 audit logs（可用于 SIEM 或合规导出）。

推荐 values（示例，复制即用；建议先 `execute=false` 验证，再切换为 `true`）：

```yaml
cronjobs:
  indexAudit:
    enabled: true
    schedule: "0 2 * * *"
    execute: false
    # 作用域（互斥）：allTenants=true 或 tenantId="<uuid>"
    allTenants: true
    # Bounds（按规模调参）
    maxDatasets: 50
    maxCheckIds: 5000
    milvusListLimit: 2000
    sampleLimit: 20

  evidenceDriftAudit:
    enabled: true
    schedule: "30 2 * * *"
    execute: false
    allTenants: true
    maxDatasets: 50
    sliceTopN: 20
    includeArchivedItems: false
    includeDetails: false

  accessReviewSummary:
    enabled: true
    schedule: "0 3 * * *"
    execute: false
    allTenants: true
```

补充说明：

- Cron schedule 由 K8s 控制面解释（通常是 UTC）；请结合你的时区调整。
- Job 输出会体现在审计日志中；结合 `/api/v1/observability/periodic-jobs/freshness` 可做 “新鲜度” 监控。
- 完整示例文件：`deploy/helm/mimirq/examples/values-periodic-audits.yaml`

## 5) 安装 / 升级

### 5.1 Helm 模板自检（推荐）

安装前建议先做一次渲染检查（能提前发现 values/模板语法错误）：

```bash
make helm-template
make helm-lint
```

如果开启了 `migrations.enabled=true`，渲染阶段会额外校验：

- 必须设置 `existingSecretName`
- 必须把 `DB_CREATE_ALL_ON_STARTUP` / `DB_RUNTIME_MIGRATIONS_ENABLED` 关闭
- 多副本场景下不得使用本地 `faiss/chroma`
- 多副本 + 本地文档存储时，uploads PVC 必须声明 `ReadWriteMany`

```bash
helm upgrade --install mimirq deploy/helm/mimirq \
  -n mimirq --create-namespace \
  -f values-prod.yaml
```

检查状态：

```bash
kubectl -n mimirq get pods
kubectl -n mimirq get svc
kubectl -n mimirq logs deploy/mimirq-mimirq-api -f
kubectl -n mimirq logs deploy/mimirq-mimirq-worker -f
```

---

## 6) 快速验证

若未启用 Ingress，可先端口转发：

```bash
kubectl -n mimirq port-forward svc/mimirq-mimirq 8000:8000
curl -fsS http://localhost:8000/api/v1/health/ready
```

---

## 7) 常见问题 / 排错

- **readiness 503**：表示依赖不可用（Postgres/Redis/向量库/MinIO）。请检查对应服务地址与网络策略。
- **worker 不处理任务**：检查 `TASK_QUEUE_ENABLED=true`、`REDIS_URL` 是否可达，以及 worker 日志里是否有连接异常。
- **上传/解析报错**：检查 `UPLOAD_DIR=/data/uploads`，以及 PVC 是否可写。
