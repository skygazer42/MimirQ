---
sidebar_label: "部署"
sidebar_position: 4
---

# 部署指南

MimirQ 支持三种部署方式：Docker Compose（开发/测试）、Helm Chart（生产 K8s）和源码部署（本地开发）。

## 架构拓扑

```mermaid
graph TB
    LB[Load Balancer / Ingress] --> API1[MimirQ API :8000]
    LB --> API2[MimirQ API :8000]
    API1 & API2 --> PG[(PostgreSQL :5432)]
    API1 & API2 --> MV[(Milvus :19530)]
    API1 & API2 --> RD[(Redis :6379)]
    API1 & API2 --> MIO[(MinIO :9000)]
    WORKER[Task Worker] --> PG
    WORKER --> MV
    WORKER --> RD
    WORKER --> MIO
```

## 端口映射

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| MimirQ API | 8000 | HTTP | 主服务 + WebSocket |
| PostgreSQL | 5432 | TCP | 关系型存储 |
| Milvus | 19530 | gRPC | 向量检索 |
| Redis | 6379 | TCP | 缓存 + 任务队列 |
| MinIO | 9000 / 9001 | HTTP | 对象存储 / 管理控制台 |

## 资源需求

| 规格 | CPU | 内存 | 磁盘 | 适用场景 |
|------|-----|------|------|----------|
| 最低 | 4 核 | 8 GB | 50 GB | 本地开发 / 试用 |
| 推荐 | 8 核 | 16 GB | 200 GB | 中小团队（≤50 用户） |
| 生产 | 16+ 核 | 32+ GB | 500+ GB SSD | 企业级（高可用） |

:::info
使用 GPU Embedding（`EMBEDDING_DEVICE=cuda`）时，额外需要 NVIDIA GPU（≥8 GB 显存）。
:::

## 方式一：Docker Compose

适用于快速启动、开发测试和小规模部署。

```yaml
# docker-compose.yml
version: "3.8"
services:
  api:
    image: mimirq/api:latest
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      milvus:
        condition: service_started
      redis:
        condition: service_healthy

  worker:
    image: mimirq/api:latest
    command: ["celery", "-A", "app.tasks", "worker", "--loglevel=info"]
    env_file: .env
    depends_on:
      - api

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: mimirq
      POSTGRES_USER: mimirq
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mimirq"]
      interval: 5s

  milvus:
    image: milvusdb/milvus:v2.4-latest
    ports:
      - "19530:19530"
    volumes:
      - milvus_data:/var/lib/milvus

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data

volumes:
  pg_data:
  milvus_data:
  minio_data:
```

```bash
# 启动
docker compose up -d

# 查看日志
docker compose logs -f api

# 停止
docker compose down
```

## 方式二：Helm Chart

适用于 Kubernetes 生产环境。

```bash
# 添加 Helm 仓库
helm repo add mimirq https://charts.mimirq.io
helm repo update

# 安装（使用自定义 values）
helm install mimirq mimirq/mimirq \
  --namespace mimirq --create-namespace \
  -f values.yaml
```

`values.yaml` 关键配置：

```yaml
replicaCount: 2

image:
  repository: mimirq/api
  tag: "1.4.0"

resources:
  requests:
    cpu: "2"
    memory: "4Gi"
  limits:
    cpu: "4"
    memory: "8Gi"

env:
  DATABASE_URL: postgresql://mimirq:pass@postgres:5432/mimirq
  MILVUS_URI: milvus:19530
  REDIS_URL: redis://redis:6379/0

ingress:
  enabled: true
  className: nginx
  hosts:
    - host: mimirq.example.com
      paths:
        - path: /
          pathType: Prefix

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 70
```

:::tip
生产部署建议将 PostgreSQL、Milvus、Redis 使用独立的 Helm Chart 或托管服务部署，而非内嵌到 MimirQ Chart 中。
:::

## 方式三：源码部署

适用于本地开发和调试。

```bash
# 1. 克隆仓库
git clone https://github.com/skygazer42/MimirQ.git
cd MimirQ

# 2. 安装 Python 依赖
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际配置

# 4. 初始化数据库
alembic upgrade head

# 5. 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 6. 启动 Worker（另一终端）
celery -A app.tasks worker --loglevel=info
```

:::warning
源码部署需自行准备 PostgreSQL、Milvus、Redis、MinIO 服务。可使用 `docker compose up postgres milvus redis minio` 仅启动依赖服务。
:::

## 升级策略

| 部署方式 | 升级命令 | 回滚方式 |
|----------|----------|----------|
| Docker Compose | `docker compose pull && docker compose up -d` | 指定旧版本 tag 重新部署 |
| Helm | `helm upgrade mimirq mimirq/mimirq -f values.yaml` | `helm rollback mimirq` |
| 源码 | `git pull && pip install -r requirements.txt && alembic upgrade head` | `git checkout <tag>` |

升级前检查清单：

1. 阅读 Release Notes 确认是否有 Breaking Changes
2. 备份 PostgreSQL 数据库
3. 执行 `alembic upgrade head` 运行数据库迁移
4. 验证 `/health` 端点返回 `healthy`

:::danger
跨大版本升级（如 1.x → 2.x）可能涉及数据迁移脚本，务必参考版本发布说明逐步操作。
:::

---

**相关链接**

- [运行时配置](./settings-meta.md) — 环境变量与配置管理
- [健康探针](./health-probes.md) — 部署后健康检查验证
- [可观测性](./observability.md) — 监控与告警配置
