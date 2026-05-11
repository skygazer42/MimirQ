# Docker Compose 部署指南

本项目提供多套 Compose 配置：

- `docker/docker-compose.yml`：主栈（`mimirq-api`/`mimirq-worker` + Postgres/Milvus/Redis/MinIO；默认不暴露基础设施端口）
- `docker/docker-compose.lite.yml`：低资源栈（`mimirq-api`/`mimirq-worker` + Postgres/Redis；默认使用 Chroma 本地向量库，不启动 Milvus/MinIO）
- `docker/docker-compose.infra.yml`：仅基础设施（暴露端口，便于本地后端调试）
- `docker/docker-compose.parsers.yml`：可选外部解析服务（Marker/PaddleOCR-VL/olmOCR/Qianfan-OCR/MinerU/ETL4LLM），用 `-f` 叠加并通过 `--profile` 按需启用

另外，前端服务 `web` 放在 `docker/docker-compose.web.yml`，默认不启动；需要时用 `-f` 叠加即可（或直接 `make up-web`）。

---

## 1) 环境准备

```bash
cd docker
cp .env.example .env
cd ..
cp web/.env.local.example web/.env.local
```

编辑 `docker/.env`，至少配置：

- `LLM_API_KEY`（以及可选的 `LLM_API_BASE/LLM_MODEL`）
- 若启用生产 JWT：`AUTH_MODE=jwt` + `SECRET_KEY`（长度 >= 32）

根目录 `.env.example` 是本地启动最小模板；解析、RAG、KG、可观测性等高级项见 `config/env/*.env.example`。

前端（Docker）可选配置（`docker/docker-compose.web.yml` 使用）：

- `WEB_PORT`：前端端口（默认 `3000`）
- `NEXT_PUBLIC_API_URL`：浏览器访问后端的地址（默认 `http://localhost:8000`）
- `API_INTERNAL_URL_DOCKER`：前端容器内（SSR）访问后端的地址（默认 `http://mimirq-api:8000`）

> 注意：不要把 `NEXT_PUBLIC_API_URL` 设置成 `http://mimirq-api:8000`，因为浏览器无法解析 Docker 内部服务名；SSR 需要容器内地址时请改 `API_INTERNAL_URL_DOCKER`。

---

## 2) 开发模式（默认）

使用主栈（不含源码挂载）：

```bash
make up
make ps
make logs
```

低资源（lite）模式（可选，适合小内存机器/快速试跑）：

```bash
make up-lite
make ps-lite
make logs-lite
```

如需本地开发后端（推荐）：只启动基础设施，然后本地运行后端：

```bash
make infra-up

pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
python main.py
```

启动前端（可选）：

```bash
make up-web
```

---

## 3) 生产模式（推荐）

生产部署仍使用 `docker/docker-compose.yml`，建议在 `docker/.env` 中设置：
- `ENV=production`
- `AUTH_MODE=jwt`
- `SECRET_KEY`（长度 >= 32）
- `POSTGRES_PASSWORD`

```bash
make up
make ps
```

生产模式 + 前端（可选）：

```bash
make up-web
```

---

## 4) 数据卷与清理

关键卷：

- `postgres_data`：PostgreSQL 数据
- `milvus_data` / `etcd_data` / `minio_data`：Milvus 相关数据
- `upload_data`：上传文件（后端容器内路径默认为 `/data/uploads`）
- `vector_data`：lite 模式下的本地向量库持久化目录（`CHROMA_PERSIST_PATH_DOCKER=/data/vector_chroma`）

仅停止服务：

```bash
make down
```

仅停止 lite 栈：

```bash
make down-lite
```

重置所有数据（谨慎）：

```bash
cd docker
docker compose down -v
```

如需重置 lite 栈数据（谨慎）：

```bash
cd docker
docker compose -f docker-compose.lite.yml down -v
```

---

## 5) 常见排错

- 查看配置合并结果：`docker compose config`
- 查看后端日志：`docker compose logs -f mimirq-api`
- 就绪探针：`curl -fsS http://localhost:8000/api/v1/health/ready`
- Milvus 健康：`curl -fsS http://localhost:9091/healthz`
