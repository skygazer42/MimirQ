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

后端跑在 Docker（推荐）：在 `.env` 中设置：

```env
MINERU_ENABLED=true
MINERU_MODEL_SOURCE=local
MINERU_LOCAL_SERVER_URL=http://mimirq-mineru:8000
```

后端跑在本地（Python），MinerU 跑在 Docker：在仓库根目录 `.env` 中设置：

```env
MINERU_ENABLED=true
MINERU_MODEL_SOURCE=local
MINERU_LOCAL_SERVER_URL=http://localhost:30001
```

### 2.1) 本地模型模式（MinerU 2.5 Pro local）

如果你希望 MinerU 明确走**本地缓存模型**而不是在运行时再向 HuggingFace / ModelScope 拉取，
建议同时设置：

```env
MINERU_MODEL_SOURCE=local
```

当前仓库的本地 `mineru-api` 启动链路会在 `MINERU_MODEL_SOURCE=local` 时自动检查
容器内缓存目录，并生成 `/root/mineru.json`，把已缓存模型写入：

- `models-dir.pipeline`
- `models-dir.vlm`

当前实测可用的缓存根目录形态为：

- `/root/.cache/huggingface/hub/models--opendatalab--PDF-Extract-Kit-1.0/snapshots/...`
- `/root/.cache/huggingface/hub/models--opendatalab--MinerU2.5-2509-1.2B/snapshots/...`

### 3) 使用方式

- 解析预览：在解析工作台选择解析器为 `mineru`
- 入库解析：上传文档时指定 `parser_backend=mineru`（或把默认解析器切到 `mineru`）

说明：MimirQ 调用本地 MinerU 时默认使用 `backend=pipeline`（无需额外 VLM Server）。如果你希望明确只走本地缓存模型，而不是 HuggingFace/ModelScope 在线拉取，请同时设置 `MINERU_MODEL_SOURCE=local`。

## 显存 / 资源说明

基于当前仓库这轮 rebuilt runtime 实测：

- 本地 `mineru-api` 的 `file_parse` 已成功跑通
- 当前验证使用的是 **`backend=pipeline`**
- 在这条验证链路里，**没有观测到独立的本地 GPU 峰值分配**

但这并不等于 MinerU 在任何模式下都“完全不吃 GPU”。如果你后续切换：

- 不同 backend
- 不同模型源
- 不同模型规格

都建议你重新量测。保守做法是：

- MinerU 仍然**单独部署**
- 并为该服务预留一段独立 GPU 资源窗口
- 如果要和别的 OCR/VLM parser 共卡，先做单独压测再混跑

---

## 在线 MinerU（mineru.net）

在 `.env` 中配置：

```env
MINERU_ENABLED=true
MINERU_API_TOKEN=...
MINERU_API_BASE=https://mineru.net/api/v4
```

---

## Docker 镜像说明

- Dockerfile：`docker/mineru/Dockerfile`
- 参考：MinerU 上游项目（本环境路径：`/data/temp34/MinerU`）
- 注意：模型下载非常耗时/耗带宽；默认会在首次使用时从 HuggingFace/ModelScope 按需下载并缓存（`docker-compose.parsers.yml` 默认挂载 `/root/.cache`）。
- 如需离线/内网环境：可在 build 时预下载（`MINERU_PREFETCH_MODELS=1`，并按需设置 `MINERU_MODEL_DOWNLOAD_SOURCE/MINERU_MODEL_DOWNLOAD_TYPE`）。
