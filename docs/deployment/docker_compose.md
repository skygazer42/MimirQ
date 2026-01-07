# Docker Compose 部署指南

本项目提供两套 Compose 配置，兼顾本地开发与生产部署：

- `docker-compose.yml`：默认栈（本地可直接用；无源码挂载；后端不启用 `--reload`）
- `docker-compose.override.yml`：开发覆盖（源码挂载 + `--reload`）
- `docker-compose.prod.yml`：生产栈（不暴露基础设施端口；`ENV=production` + `AUTH_MODE=jwt`）

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

默认使用基础栈（不含源码挂载）：

```bash
make up
make ps
make logs
```

如需源码挂载 + 热更新：

```bash
make up-dev
make ps
make logs
```

启动前端（可选）：

```bash
make up-web
```

---

## 3) 生产模式（推荐）

生产栈使用 `docker-compose.prod.yml`（并强制启用 JWT 校验）：

```bash
make up-prod
make ps
```

生产模式 + 前端（可选）：

```bash
make up-prod-web
```

---

## 4) 数据卷与清理

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

## 5) 常见排错

- 查看配置合并结果：`docker compose config`
- 查看后端日志：`docker compose logs -f backend`
- 就绪探针：`curl -fsS http://localhost:8000/api/v1/health/ready`
- Milvus 健康：`curl -fsS http://localhost:9091/healthz`

