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

- `GET /api/v1/health/ready`（依赖可用时返回 200，否则 503）

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
  --from-literal=AUTH_MODE=jwt \
  --from-literal=SECRET_KEY="<>=32 chars random>" \
  --from-literal=DATABASE_URL="postgresql://user:pass@postgres:5432/mimirq" \
  --from-literal=REDIS_URL="redis://redis:6379/0" \
  --from-literal=VECTOR_BACKEND="milvus" \
  --from-literal=MILVUS_HOST="milvus" \
  --from-literal=MILVUS_PORT="19530" \
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

persistence:
  uploads:
    enabled: true
    size: 50Gi
```

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

---

## 5) 安装 / 升级

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
