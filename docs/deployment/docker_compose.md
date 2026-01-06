# Docker Compose 部署指南

本项目提供两套 Compose 配置，兼顾本地开发与生产部署：

- `docker-compose.yml`：生产友好（无源码挂载；后端不启用 `--reload`）
- `docker-compose.override.yml`：开发覆盖（默认会被 `docker compose up` 自动加载；开启后端热更新并挂载源码）

另外，前端服务 `web` 使用 `profiles: ["web"]`，默认不启动；需要时显式启用即可。

---

## 1) 环境准备

```bash
cp .env.example .env
cp web/.env.local.example web/.env.local
```

编辑 `.env`，至少配置：

- `LLM_API_KEY`（以及可选的 `LLM_API_BASE/LLM_MODEL`）
- 若启用生产 JWT：`AUTH_MODE=jwt` + `SECRET_KEY`（长度 >= 32）

---

## 2) 开发模式（默认）

开发模式会自动加载 `docker-compose.override.yml`：

```bash
make up
make ps
make logs
```

启动前端（可选）：

```bash
make up-web
```

---

## 3) 生产模式（仅使用 base compose）

生产模式不会加载 `docker-compose.override.yml`（避免源码挂载/热更新）：

```bash
make up-prod
make ps
```

生产模式 + 前端（可选）：

```bash
make up-prod-web
```

---

## 4) 依赖集合（镜像体积/构建速度）

后端 Docker 构建默认安装 `requirements-minimal.txt`（更小更快）。

如需 MagicPDF / Docling / 本地 Embedding 等重依赖，可在 `.env` 中设置：

```bash
BACKEND_REQUIREMENTS_FILE=requirements.txt
```

然后重新构建：

```bash
docker compose build --no-cache backend worker
```

---

## 5) 数据卷与清理

关键卷：

- `postgres_data`：PostgreSQL 数据
- `milvus_data` / `etcd_data` / `minio_data`：Milvus 相关数据
- `upload_data`：上传文件（后端容器内路径默认为 `/data/uploads`）

仅停止服务：

```bash
make down
```

重置所有数据（谨慎）：

```bash
docker compose down -v
```

---

## 6) 常见排错

- 查看配置合并结果：`docker compose config`
- 查看后端日志：`docker compose logs -f backend`
- 就绪探针：`curl -fsS http://localhost:8000/api/v1/health/ready`
- Milvus 健康：`curl -fsS http://localhost:9091/healthz`

