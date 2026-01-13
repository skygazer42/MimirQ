# MinerU（本地/在线）解析器集成

MimirQ 支持将 **MinerU** 作为可选 PDF 高级解析后端，支持两种模式：

- **在线 MinerU**：配置 `MINERU_API_TOKEN` 调用 `mineru.net`（返回 ZIP：Markdown + images）。
- **本地 MinerU**：启动 MinerU FastAPI（`/file_parse`，返回 ZIP：Markdown + images），MimirQ 通过 `MINERU_LOCAL_SERVER_URL` 调用。

---

## 本地 MinerU（推荐用于私有部署）

### 1) 启动 MinerU 服务

本项目已提供 Docker 镜像与 Compose 配置：

```bash
make up-mineru
```

等价于：

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.parsers.yml --profile mineru up -d --build
```

默认端口映射：宿主机 `30001 -> 容器 8000`。

### 2) 配置后端环境变量

后端跑在 Docker（推荐）：在 `docker/.env` 中设置：

```env
MINERU_ENABLED=true
MINERU_LOCAL_SERVER_URL=http://mimirq-mineru:8000
```

后端跑在本地（Python），MinerU 跑在 Docker：在仓库根目录 `.env` 中设置：

```env
MINERU_ENABLED=true
MINERU_LOCAL_SERVER_URL=http://localhost:30001
```

### 3) 使用方式

- 解析预览：在解析工作台选择解析器为 `mineru`
- 入库解析：上传文档时指定 `parser_backend=mineru`（或把默认解析器切到 `mineru`）

说明：MimirQ 调用本地 MinerU 时默认使用 `backend=pipeline`（无需额外 VLM Server）。

---

## 在线 MinerU（mineru.net）

在 `.env` / `docker/.env` 中配置：

```env
MINERU_ENABLED=true
MINERU_API_TOKEN=...
MINERU_API_BASE=https://mineru.net/api/v4
```

---

## Docker 镜像说明

- Dockerfile：`docker/mineru/Dockerfile`
- 参考：MinerU 上游项目（本环境路径：`/data/temp34/MinerU`）
- 注意：模型下载非常耗时/耗带宽；默认会在 build 阶段下载全量模型。

