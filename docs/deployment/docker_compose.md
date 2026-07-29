# Docker Compose 部署指南

本项目提供多套 Compose 配置：

- `docker/docker-compose.yml`：主栈（`mimirq-api`/`mimirq-worker` + Postgres/Milvus/Redis/MinIO；默认不暴露基础设施端口）
- `docker/docker-compose.lite.yml`：低资源栈（`mimirq-api`/`mimirq-worker` + Postgres/Redis；默认使用 Chroma 本地向量库，不启动 Milvus/MinIO）
- `docker/docker-compose.infra.yml`：仅基础设施（暴露端口，便于本地后端调试）
- `docker/docker-compose.parsers.yml`：可选外部解析服务（Marker/PaddleOCR-VL/olmOCR/Qianfan-OCR/MinerU/ETL4LLM/MagicPDF），用 `-f` 叠加并通过 `--profile` 按需启用

主栈的 `mimirq-api` 与 `mimirq-worker` 会只读挂载 `mineru_cache` 到
`/opt/mimirq-model-cache`，用于复用 MinerU / PDF-Extract-Kit 模型缓存。MagicPDF 通过
`mimirq-magicpdf` 独立服务运行；默认 API / worker 镜像不安装与主运行时依赖冲突的
`magic-pdf` CLI。本地 CLI 只适用于显式安装兼容依赖的宿主机或自定义镜像。

DeepDoc 的轻量解析模型不随源码仓库分发。Docker 构建会从
`qwqqwq/mimirq@118452f3ea3ccd09a41b2d39ea82d7de535e2908` 下载并校验模型，
因此首次构建需要访问 Hugging Face；镜像构建完成后，运行时不会联网下载模型。

另外，前端服务 `web` 放在 `docker/docker-compose.web.yml`，默认不启动；需要时用 `-f` 叠加即可（或直接 `make up-web`，它会启动后端、Worker、基础设施和前端整套 Docker Web 栈，而不是只启动前端）。

---

## 1) 环境准备

```bash
make init
# Windows without make: python scripts/init_env.py
```

编辑 `.env`。本地真实模型闭环最低只需填写 `LLM_API_KEY`；`make init` 已生成 `SECRET_KEY`，其余基础设施变量有本地默认值。

| 能力 | Docker 本地默认 | 需要修改的情况 |
|:---|:---|:---|
| LLM | 硅基流动 `Qwen/Qwen3-32B` | `LLM_API_KEY` 必填；其他供应商再改 `LLM_API_BASE` / `LLM_MODEL` |
| Embedding | `BAAI/bge-m3`，复用 LLM Key/Base URL | 独立服务才填写 `EMBEDDING_*` |
| Reranker | 关闭 | 设置 `ENABLE_RERANKER=true`；Key 可复用 LLM，但 Base URL 必须是完整 rerank 端点 |
| 首个管理员 | Web 手工注册 | 无人值守部署建议配置 `INITIAL_ADMIN_EMAIL`、`INITIAL_ADMIN_USERNAME` 和一种密码来源 |

LLM、Embedding 与 Reranker 分离部署、宿主机模型地址和管理员完整规则见[模型服务与首次管理员配置](../guides/model_services.md)。容器内基础设施地址应继续使用 `_DOCKER` 变量（如 `MILVUS_HOST_DOCKER`、`REDIS_URL_DOCKER`、`MINIO_ENDPOINT_DOCKER`），不要把它们与外部模型服务地址混淆。

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
| MagicPDF 服务解析 | `MAGIC_PDF_ENABLED=true`、`MAGIC_PDF_API_URL=http://mimirq-magicpdf:2095/convert`、GPU 服务器设置 `MAGIC_PDF_DEVICE_MODE=cuda`，并用 `--profile magicpdf` 启动服务 | `scripts/check_parsers.py` 应显示 `magicpdf ... configured (service)`，再做真实 PDF 预览/上传；默认 API / worker 镜像不包含本地 CLI |
| MinerU 本地 pipeline | `MINERU_LOCAL_SERVER_URL=http://mimirq-mineru:8000`，`MINERU_BACKEND=pipeline`，`--profile mineru` 启动本地服务 | 先单独启动 `mimirq-mineru`，健康后再跑 `parser_backend=mineru` 预览 |
| MinerU 本地 VLM | `MINERU_BACKEND=vlm-http-client`，`MINERU_VL_SERVER=http://mimirq-mineru-vlm:30000`，`MINERU_API_ALLOW_PUBLIC_HTTP_CLIENT=1`，同时启用 `--profile mineru --profile mineru-vlm` | 先检查 `mimirq-mineru-vlm` 健康和 `nvidia-smi` 显存占用，再跑大 PDF 预览；MinerU API 不要直接暴露公网 |
| MinerU 在线 API | `MINERU_API_TOKEN`；如需强制在线路径，不能同时配置 `MINERU_LOCAL_SERVER_URL` | 临时清空本地 URL 后用 `parser_backend=mineru` 做预览；注意外部 API token/额度/队列状态 |
| ETL4LLM / Marker / PaddleOCR-VL | 分别配置 `*_API_URL`，并按需启动 `docker/docker-compose.parsers.yml` 对应 profile | 显存紧张时分批启动，测完一个 profile 就 `docker compose ... stop <service>` |
| TextIn xParse | `TEXTIN_ENABLED=true`、`TEXTIN_API_URL`、`TEXTIN_APP_ID`、`TEXTIN_SECRET_CODE` | 只有 APP ID/Secret 都存在时才做真实 `parser_backend=textin` 预览；缺凭证时诊断会显示 missing |

前端（Docker）可选配置（`docker/docker-compose.web.yml` 使用）：

- `WEB_PORT`：前端端口（默认 `3000`）
- `NEXT_PUBLIC_API_URL_DOCKER`：浏览器访问后端的地址（默认同源 `/`）
- `API_INTERNAL_URL_DOCKER`：前端容器内（SSR）访问后端的地址（默认 `http://mimirq-api:8000`）
- `FORWARDED_ALLOW_IPS_DOCKER`：允许覆盖客户端 IP 的可信代理地址；默认仅包含回环和 `web` 容器固定地址，禁止设为 `*`
- `MIMIRQ_PROXY_SUBNET` / `WEB_PROXY_IP_DOCKER`：前后端代理专用网段及 `web` 地址；修改时必须同步更新 `FORWARDED_ALLOW_IPS_DOCKER`

> 注意：不要把 `NEXT_PUBLIC_API_URL_DOCKER` 设置成 `http://mimirq-api:8000`，因为浏览器无法解析 Docker 内部服务名；SSR 需要容器内地址时请改 `API_INTERNAL_URL_DOCKER`。

若在 Compose 外使用 Ingress 或反向代理，需把代理的实际来源 IP/CIDR 加入容器环境变量 `FORWARDED_ALLOW_IPS`。未列入的来源即使伪造 `X-Forwarded-For` 也不会改变审计、限流或 SCIM allowlist 使用的客户端 IP。

Compose 内置的 Web 入口会在 Next.js rewrite 前把 `X-Forwarded-For` 强制重写为其 TCP peer，客户端不能自行提供该值。外部 Ingress 经 Web 转发时后端只能看到 Ingress 地址；若 SCIM 必须按 IdP 的真实出口 IP allowlist，请让受信 Ingress 直连 `mimirq-api`，并仅把该 Ingress 的来源地址加入 `FORWARDED_ALLOW_IPS`。

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
make setup-host
make backend
```

启动本地热更新前端（可选）：

```bash
make web
```

如需直接启动完整 Docker Web 栈（后端、Worker、基础设施与前端一起跑），再使用：

```bash
make up-web
```

---

## 3) 生产模式（推荐）

生产部署仍使用 `docker/docker-compose.yml`，建议在 `.env` 中设置：
- `ENV=production`
- `AUTH_MODE=jwt`
- `SECRET_KEY`（长度 >= 32）
- `MIMIRQ_DB_CREATE_ALL_ON_STARTUP=false`
- `MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED=false`
- `UPLOAD_DEDUP_ENABLED_DOCKER=true`（默认已开启；仅在排查兼容性时临时关闭）
- `RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED_DOCKER=true`（默认已开启）
- `RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY_DOCKER=3`（保守默认；按实例 CPU / 上游模型吞吐再调）
- 二选一配置首个本地管理员：
  - `INITIAL_ADMIN_EMAIL` + `INITIAL_ADMIN_USERNAME` + `INITIAL_ADMIN_PASSWORD`
  - 或 `INITIAL_ADMIN_EMAIL` + `INITIAL_ADMIN_USERNAME` + `INITIAL_ADMIN_PASSWORD_FILE`
  - 适合无人值守部署；启动成功后会自动成为默认租户 owner，后续重启不会重置密码
  - 如果使用 `INITIAL_ADMIN_PASSWORD_FILE`，请通过 Compose override 或 Docker secret 把该文件挂载到 `mimirq-api` 容器内可读的位置，默认 Compose 不会自动提供任意密码文件路径
- 如果不使用自动管理员引导，则继续保留 `INITIAL_REGISTRATION_TOKEN` 作为手工首登 fallback（首个本地 owner 注册一次性 token，请通过 `X-Bootstrap-Token` 发送；支持 `sha256:<hex>`，初始化完成后可移除）
- `POSTGRES_PASSWORD`（强密码）
- `MINIO_ACCESS_KEY_DOCKER` / `MINIO_SECRET_KEY_DOCKER`（强凭据；不要保留 `minioadmin`）
- `JWT_TENANT_CLAIM`（推荐）或在可信网关会重写租户头时显式设 `TENANT_HEADER_TRUSTED=true`
- 若启用 `make up-prod-web`：`MARKDOWN_IMAGE_PROXY_SECRET` 必须非空，`FORWARDED_ALLOW_IPS_DOCKER` 只能填受信任代理 IP，禁止 `*`

```bash
make infra-up
make db-upgrade
make up-prod
make ps
```

如果使用环境变量自动引导首个管理员，可直接在 `.env` 中补：

```dotenv
INITIAL_ADMIN_EMAIL=owner@example.com
INITIAL_ADMIN_USERNAME=owner
INITIAL_ADMIN_PASSWORD_FILE=/run/secrets/mimirq_initial_admin_password
```

推荐把密码通过 Compose override / Docker secret 或宿主机只读文件挂载到 `mimirq-api` 容器内的 `INITIAL_ADMIN_PASSWORD_FILE` 路径，避免把明文密码留在 `.env`；默认 Compose 不会自动挂载这个文件。多实例必须使用完全相同的 `INITIAL_ADMIN_*`，初始化成功后再统一删除。若默认租户已有不同成员，API 会拒绝覆盖或自动提权并停止启动，此时应移除这些变量并使用现有 owner。

如果你走的是手工首登 fallback，首次创建 owner 时发送原始 bootstrap token（如果 `.env` 保存的是 `sha256:<hex>`，这里仍发送计算摘要前的原始 token）：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -H 'X-Bootstrap-Token: <raw-bootstrap-token>' \
  -d '{"email":"owner@example.com","username":"owner","password":"replace-with-a-strong-password"}'
```

创建成功后可从 `.env` 删除 `INITIAL_REGISTRATION_TOKEN` 并重启服务；后续注册请求仍会返回 `409`。

如果已经使用 `INITIAL_ADMIN_*` 自动创建了首个 owner，则不需要再调用上面的 `/auth/register` bootstrap 接口；`INITIAL_REGISTRATION_TOKEN` 可以完全留空。

生产前再核对一次：

- 不要使用 Compose 默认的 `postgres` / `minioadmin` 凭据
- 若确需回退旧行为，可在 `.env` 覆盖 `UPLOAD_DEDUP_ENABLED_DOCKER=false` 或 `RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED_DOCKER=false`
- 如果暴露前端，浏览器入口应走 HTTPS 终止的反向代理；只把受信任代理地址写入 `FORWARDED_ALLOW_IPS`
- `NEXT_PUBLIC_API_URL_DOCKER` 保持浏览器可达地址；SSR 走 `API_INTERNAL_URL_DOCKER`

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
- `vector_data`：lite 模式下的本地向量库持久化目录（`CHROMA_PERSIST_PATH_DOCKER=/app/vector_chroma`）
- `*_cache`：按需启动的解析器模型与运行缓存

从仓库根目录按需要选择一个命令：

| 目的 | 命令 | 容器 / 网络 | 数据卷 | 服务镜像 |
|:---|:---|:---:|:---:|:---:|
| 暂停并保留数据 | `make down` | 删除 | 保留 | 保留 |
| 清空数据后重建 | `make docker-reset` | 删除 | 删除 | 保留 |
| 完全重新拉取 / 构建 | `make docker-purge` | 删除 | 删除 | 删除 |

### 仅停止，保留数据

```bash
make down
```

该命令覆盖完整 Web 栈、主栈、可选解析器以及 lite / retrieval-dev 变体。PostgreSQL、
上传文件、向量索引、MinIO 对象和解析器模型缓存仍保存在命名卷中，下次
`make up-web` 可继续使用。

只停止某个轻量变体时仍可使用：

```bash
make down-lite
make down-retrieval-dev
```

### 清空数据，保留镜像

```bash
make docker-reset
make up-web
```

`make docker-reset` 会额外删除 MimirQ 的命名卷，包括数据库、上传文件、向量索引、
对象存储和解析器模型缓存。此操作不可恢复，但会保留已拉取或构建的镜像，适合首次管理员
状态异常、测试数据污染或需要从空库重新验证的本地环境。

### 删除数据和服务镜像

```bash
make docker-purge
make up-web
```

`make docker-purge` 在重置数据的基础上使用 `--rmi all`，删除这些 Compose 文件引用的
MimirQ API / Web / 解析器镜像以及 PostgreSQL、Redis、Milvus、MinIO 等依赖镜像。下次
启动会重新下载或构建。若同一镜像仍被其他容器引用，Docker 会保留它并报告冲突；该命令
也可能清掉其他项目复用的本地镜像缓存，因此只在确实需要完全重建时使用。

MimirQ 的默认 Compose 项目名固定为 `mimirq`，不会再使用目录名 `docker`。这是资源隔离边界：
同一台机器上的 Dify 或其他 Compose 应用即使也放在名为 `docker` 的目录中，也不会被
MimirQ 的停止或清理命令识别为同一项目。Make 目标还会显式传入项目名，并且不会使用
`--remove-orphans` 扫描未在 MimirQ 配置中声明的服务。

以上三个目标都只处理当前 `COMPOSE_PROJECT_NAME` 对应的 Compose 项目，
不会删除 `.env`、`web/.env.local`、源码、`.venv` 或宿主机上的模型目录，也不会执行
影响其他项目的 `docker system prune` / `docker builder prune`。BuildKit 全局构建缓存会保留。

### 直接使用 Docker Compose

`docker compose down` 可以使用，但必须复用启动时相同的 Compose 项目名和叠加文件；只写
`docker compose down` 可能遗漏 Web 或可选解析器。以完整栈为例，`make down` 的主清理步骤等价于：

```bash
docker compose --project-name mimirq --env-file .env \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.web.yml \
  -f docker/docker-compose.parsers.yml \
  --profile "*" down
```

在末尾增加 `--volumes` 等价于清空该配置声明的数据卷；再增加 `--rmi all` 会同时删除
服务镜像。项目也可能曾用 lite / retrieval-dev 配置启动，因此推荐使用 Make 目标，它们会
依次覆盖这些变体。如果显式自定义了 `COMPOSE_PROJECT_NAME` 或 `docker compose -p`，
清理时必须使用同一个值，并且不要与 Dify 等其他应用复用项目名。

---

## 5) 常见排错

- 查看配置合并结果：`docker compose config`
- 查看后端日志：`docker compose logs -f mimirq-api`
- 就绪探针：`curl -fsS http://localhost:8000/api/v1/health/ready`
- Milvus 健康：`curl -fsS http://localhost:9091/healthz`
