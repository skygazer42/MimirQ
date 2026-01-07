# 部署指南（Docker Compose）

## 1) 本地一键启动（默认）

适用于本机体验/联调，依赖服务会映射端口到宿主机（Postgres/Milvus/Redis/MinIO）。

```bash
cd docker
cp .env.example .env
docker compose up -d --build
docker compose --profile web up -d --build   # 可选：前端 UI（profile=web）
```

## 2) 本地开发（热更新 / 源码挂载）

仓库包含 `docker/docker-compose.dev.yml`（dev override）。推荐显式启动：

```bash
make up-dev
make up-dev-web
```

## 3) 生产部署（推荐）

生产栈使用 `docker/docker-compose.prod.yml`，默认不暴露基础设施端口（更安全），并启用 `ENV=production` 触发后端配置校验：

- 强制 `AUTH_MODE=jwt`
- 必须设置 `SECRET_KEY`（至少 32 字符）
- 必须设置 `POSTGRES_PASSWORD`

### 3.1 准备环境变量

```bash
cd docker
cp .env.example .env
```

然后编辑 `.env`，至少配置：
- `SECRET_KEY`
- `POSTGRES_PASSWORD`
- `LLM_API_KEY`（以及必要时的 `LLM_API_BASE` / `LLM_MODEL`）

### 3.2 启动

```bash
cd docker
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml --profile web up -d --build   # 可选：带前端 UI（profile=web）
```

Windows PowerShell 也可使用：

```powershell
Set-Location docker
Copy-Item .env.example .env -ErrorAction SilentlyContinue
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml --profile web up -d --build  # 可选：带前端（profile=web）
```

### 3.3 常用运维命令

```bash
cd docker
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f --tail=200 backend
docker compose -f docker-compose.prod.yml logs -f --tail=200 worker
```

## 4) 端口与访问

- 后端：`http://localhost:8000/docs`
- 前端：`http://localhost:3000`（需启用 `web` profile）

生产栈默认仅暴露 `8000/3000`（可通过 `BACKEND_PORT` / `WEB_PORT` 调整映射）。
