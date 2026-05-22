# Docker Compose 部署指南

本项目提供多套 Compose 配置：

- `docker/docker-compose.yml`：主栈（`mimirq-api`/`mimirq-worker` + Postgres/Milvus/Redis/MinIO；默认不暴露基础设施端口）
- `docker/docker-compose.lite.yml`：低资源栈（`mimirq-api`/`mimirq-worker` + Postgres/Redis；默认使用 Chroma 本地向量库，不启动 Milvus/MinIO）
- `docker/docker-compose.infra.yml`：仅基础设施（暴露端口，便于本地后端调试）
- `docker/docker-compose.parsers.yml`：可选外部解析服务（Marker/PaddleOCR-VL/olmOCR/Qianfan-OCR/MinerU/ETL4LLM/MagicPDF），用 `-f` 叠加并通过 `--profile` 按需启用

主栈的 `mimirq-api` 与 `mimirq-worker` 会只读挂载 `mineru_cache` 到
`/opt/mimirq-model-cache`，用于复用 MinerU / PDF-Extract-Kit 模型缓存。MagicPDF 推荐通过
`mimirq-magicpdf` 独立服务运行；本地 CLI 兜底模式仍依赖这个挂载或显式
`MAGIC_PDF_MODELS_DIR`，未找到模型时会在诊断中显示 `missing models`。

另外，前端服务 `web` 放在 `docker/docker-compose.web.yml`，默认不启动；需要时用 `-f` 叠加即可（或直接 `make up-web`）。

---

## 1) 环境准备

```bash
cp .env.example .env
cp web/.env.local.example web/.env.local
```

编辑 `.env`，至少配置：

- `LLM_API_KEY`（以及可选的 `LLM_API_BASE/LLM_MODEL`）
- 若启用生产 JWT：`AUTH_MODE=jwt` + `SECRET_KEY`（长度 >= 32）

若使用 DashScope / 通义千问的 OpenAI-compatible 接口，示例：

```env
LLM_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus
LLM_MODEL_FAST=qwen-plus
LLM_MODEL_HEAVY=qwen3-max
```

注意：不同账号/套餐可用模型不同；如果聊天或 KG 抽取返回 403/404，请先在容器内探测
当前 `LLM_MODEL` 是否有权限，再重启 `mimirq-api` / `mimirq-worker`。不要把带密钥的
`.env` 提交到仓库。

根目录 `.env.example` 是完整环境变量模板；本地启动可直接复制为 `.env`，未用到的高级能力保持默认即可。

### 解析器 / KG 关键依赖

以下能力不是“打开开关就一定可用”，需要对应容器、凭证或模型缓存同时满足：

| 能力 | 必要配置 | Docker 验证建议 |
| --- | --- | --- |
| KG 知识抽取 | `KG_ENABLED=true`、可用 `LLM_API_KEY/LLM_API_BASE/LLM_MODEL`、主栈 Milvus；如需事件/实体向量，保持 `EVENT_VECTOR_ENABLED=true` / `ENTITY_VECTOR_ENABLED=true` | 上传时传 `kg_enabled=true`，等待 `/api/v1/kg/stats?document_ids=...` 出现 events/entities，并检查 Milvus `kg_events` / `kg_entities` collection 有数据 |
| LlamaIndex 分块 | `LLAMA_INDEX_ENABLED=true`，上传/工作台选择 `chunk_strategy=llama_index` | 用真实上传或 `/documents/preview` 验证 chunk 不因 metadata 过长失败 |
| MagicPDF 服务解析 | `MAGIC_PDF_ENABLED=true`、`MAGIC_PDF_API_URL=http://mimirq-magicpdf:2095/convert`、GPU 服务器设置 `MAGIC_PDF_DEVICE_MODE=cuda`，并用 `--profile magicpdf` 启动服务；如走本地 CLI 兜底，还需要 `magic-pdf` CLI 与 PDF-Extract-Kit 模型缓存 | `scripts/check_parsers.py` 应显示 `magicpdf ... configured (service)` 或 `configured (models: ...)`，再做真实 PDF 预览/上传 |
| MinerU 本地 pipeline | `MINERU_LOCAL_SERVER_URL=http://mimirq-mineru:8000`，`MINERU_BACKEND=pipeline`，`--profile mineru` 启动本地服务 | 先单独启动 `mimirq-mineru`，健康后再跑 `parser_backend=mineru` 预览 |
| MinerU 本地 VLM | `MINERU_BACKEND=vlm-http-client`，`MINERU_VL_SERVER=http://mimirq-mineru-vlm:30000`，`MINERU_API_ALLOW_PUBLIC_HTTP_CLIENT=1`，同时启用 `--profile mineru --profile mineru-vlm` | 先检查 `mimirq-mineru-vlm` 健康和 `nvidia-smi` 显存占用，再跑大 PDF 预览；MinerU API 不要直接暴露公网 |
| MinerU 在线 API | `MINERU_API_TOKEN`；如需强制在线路径，不能同时配置 `MINERU_LOCAL_SERVER_URL` | 临时清空本地 URL 后用 `parser_backend=mineru` 做预览；注意外部 API token/额度/队列状态 |
| ETL4LLM / Marker / PaddleOCR-VL | 分别配置 `*_API_URL`，并按需启动 `docker/docker-compose.parsers.yml` 对应 profile | 显存紧张时分批启动，测完一个 profile 就 `docker compose ... stop <service>` |
| TextIn xParse | `TEXTIN_ENABLED=true`、`TEXTIN_API_URL`、`TEXTIN_APP_ID`、`TEXTIN_SECRET_CODE` | 只有 APP ID/Secret 都存在时才做真实 `parser_backend=textin` 预览；缺凭证时诊断会显示 missing |

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

生产部署仍使用 `docker/docker-compose.yml`，建议在 `.env` 中设置：
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
