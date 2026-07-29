---
sidebar_label: "部署"
sidebar_position: 4
---

# 部署指南

MimirQ 提供两条开箱即用路径：完整 Docker Web 栈，以及“基础设施在 Docker、API/Web（可选 Arq Worker）在主机”的源码模式。Kubernetes 生产部署使用仓库内 Helm Chart。

开始前先完成[快速开始](./getting-started)中的 `.env`、模型服务和首个管理员配置。

## 方式一：Docker 一键启动

```bash
make init
# 编辑 .env，真实模型路径至少填写 LLM_API_KEY
make up-web
make ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

`make up-web` 使用仓库维护的 Compose 文件，启动 Next.js Web、FastAPI API、Arq Worker、PostgreSQL、Milvus、Etcd、Redis 与 MinIO。无需复制网上的通用 Compose 示例，也不要把 Docker 内部服务名暴露给浏览器。

```bash
make ps
make logs
make down
```

默认主栈使用内置 DeepDoc，不会启动 GPU 解析器。Marker、ETL4LLM、MinerU、PaddleOCR-VL 等都是可选 profile，只启动业务需要的服务；完整命令见仓库的 [Docker Compose 指南](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md)。

### 停止与重新开始

| 目的 | 命令 | 数据卷 | 服务镜像 |
|:---|:---|:---:|:---:|
| 停止并保留数据 | `make down` | 保留 | 保留 |
| 清空数据重建 | `make docker-reset` | 删除 | 保留 |
| 从镜像开始完全重建 | `make docker-purge` | 删除 | 删除 |

后两项不可恢复。MimirQ 默认使用独立的 `mimirq` Compose 项目名，不会把 Dify 等其他栈当作 orphan；命令不会删除 `.env` 或源码。数据库、上传文件、向量索引、解析器缓存和共享镜像的完整影响范围见 [Docker Compose 指南](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md#4-%E6%95%B0%E6%8D%AE%E5%8D%B7%E4%B8%8E%E6%B8%85%E7%90%86)。

### 项目归属与异常恢复

删除前先在终端或 PowerShell 核对资源归属：

```powershell
docker compose ls
docker ps -a --filter "label=com.docker.compose.project=mimirq"
```

`mimirq` 项目下只能出现 MimirQ 服务。Compose 的 `[+] Running N/N` 是容器、卷、镜像和
网络等资源动作总数，并不表示启动了 N 个容器；未启用可选解析器时，标准 Web 栈为 8 个
容器。

如果旧版清理误删了 Dify 容器，立即停止操作，不要运行 `docker system prune` 或
`docker volume prune`。进入原 Dify Compose 目录并复用原项目名运行 `docker compose up -d`，
确认 Dify 数据后，再在 MimirQ 目录执行 `git pull`、`make up-web`、`make ps` 和
`make api-ping`。旧版 MimirQ 的 `docker_*` 卷不会自动迁移到新的 `mimirq_*` 卷；保留数据时
应先备份再迁移。PowerShell 完整命令、项目名判断和恢复细节见仓库的
[Docker Compose 指南](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md#4-%E6%95%B0%E6%8D%AE%E5%8D%B7%E4%B8%8E%E6%B8%85%E7%90%86)。

## 方式二：主机源码运行

该模式便于前后端热更新，PostgreSQL、Milvus、Etcd、Redis 与 MinIO 仍由 Docker 提供。

```bash
make init
# 编辑 .env
make setup-host
```

默认 `TASK_QUEUE_ENABLED=false`，分别在两个终端运行：

```bash
make backend
make web
```

需要独立队列时，先在 `.env` 设置 `TASK_QUEUE_ENABLED=true` 并重启 API，再于第三个终端运行：

```bash
make worker
make worker-check
```

验证：

```bash
make infra-ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

停止主机进程后，运行 `make infra-down` 停止依赖容器。

## 主机与容器地址边界

| 调用方 | 访问同一主机服务 | 访问 Compose 内部服务 |
|:---|:---|:---|
| 主机 API/Worker | `127.0.0.1:<published-port>` | 使用 Compose 暴露到主机的端口 |
| Docker API/Worker | 容器可达的主机地址；Docker Desktop 可用 `host.docker.internal` | 使用 `mimirq-*` 服务名和 `_DOCKER` 配置 |
| 浏览器 | `localhost`、域名或反向代理公开地址 | 不能解析 Docker 内部服务名 |

`DOCKER_BUILD_NETWORK=host` 只影响镜像构建阶段，不会改变运行时容器访问模型服务的方式。

## 生产 Compose

生产配置至少需要：

- `ENV=production`、`AUTH_MODE=jwt`、强 `SECRET_KEY`
- 强 `POSTGRES_PASSWORD` 与 MinIO 凭据
- `MIMIRQ_DB_CREATE_ALL_ON_STARTUP=false`、`MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED=false`
- `JWT_TENANT_CLAIM`，或在可信网关重写租户头时显式确认 `TENANT_HEADER_TRUSTED=true`
- 限定的 `CORS_ORIGINS`、`ALLOWED_HOSTS` 与受信代理列表
- Secret 管理，而不是提交生产凭据

部署顺序：

```bash
make infra-up
make db-upgrade
make up-prod-web
make ps
```

生产前按 [Docker Compose 指南](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/docker_compose.md) 完成全部 guardrail，不要只复制本页摘要。

## Helm / Kubernetes

Chart 位于 `deploy/helm/mimirq`，默认只部署 API 与 Arq Worker；PostgreSQL、Redis、向量库和对象存储由外部基础设施提供。

```bash
helm lint deploy/helm/mimirq
helm template mimirq deploy/helm/mimirq -f <values-file>
helm upgrade --install mimirq deploy/helm/mimirq \
  --namespace mimirq --create-namespace \
  -f <values-file>
```

生产环境优先通过 `existingSecretName` 引用外部 Secret。完整 values、NetworkPolicy、多副本 guardrail 与回滚步骤见 [Helm / Kubernetes 指南](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/helm.md)。

## 部署后验收

```bash
curl -f http://localhost:8000/api/v1/health
curl -f http://localhost:8000/api/v1/health/ready
```

就绪探针只证明运行依赖可用，不证明 LLM、Embedding 或 Reranker 已连通。还需要登录、上传小文档、等待索引完成并执行一次带引用问答。

相关页面：[配置参考](./settings-meta) · [健康检查](./health-probes) · [可观测性](./observability)
