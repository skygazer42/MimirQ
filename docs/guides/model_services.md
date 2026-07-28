# 模型服务与首次管理员配置

本文说明新部署在启动前需要修改哪些 `.env` 项，以及 LLM、Embedding、Reranker 和首个管理员之间的关系。完整变量定义以仓库根目录的 [`.env.example`](../../.env.example) 为准。

> `LLM_API_KEY` 是完成真实模型调用与知识库闭环的最低要求，但不是 FastAPI 进程存活检查的必要条件。未配置真实模型时，服务可能正常启动，聊天、向量化或入库仍会失败。

## 1. 生成本地配置

```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

没有 GNU Make 时运行 `python scripts/init_env.py`。`make init` 只创建缺失的 `.env` 与 `web/.env.local`，并填充随机 `SECRET_KEY` 和 `MARKDOWN_IMAGE_PROXY_SECRET`；不会覆盖已有值。真实密钥不要提交到仓库。

## 2. 默认配置：一个 Key 完成 LLM 与 Embedding

默认使用硅基流动 OpenAI-compatible 接口：LLM 为 `Qwen/Qwen3-32B`，Embedding 为 `BAAI/bge-m3`，Reranker 默认关闭。本地真实模型闭环只需填写：

```dotenv
LLM_API_KEY=<your-siliconflow-api-key>
```

`EMBEDDING_API_KEY` 与 `EMBEDDING_API_BASE` 留空时会分别复用 `LLM_API_KEY` 与 `LLM_API_BASE`。如需启用默认 Reranker，再增加：

```dotenv
ENABLE_RERANKER=true
```

默认 `RERANKER_API_BASE=https://api.siliconflow.cn/v1/rerank` 已经是完整请求端点，`RERANKER_API_KEY` 留空时会复用 `LLM_API_KEY`。

## 3. 三个模型服务使用独立地址

```dotenv
# Chat / generation：OpenAI-compatible Base URL
LLM_API_BASE=https://llm.example.com/v1
LLM_API_KEY=<llm-key>
LLM_MODEL=<chat-model>

# Embedding：OpenAI-compatible Base URL
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_BASE=https://embedding.example.com/v1
EMBEDDING_API_KEY=<embedding-key>
EMBEDDING_MODEL=<embedding-model>

# Reranker：完整 rerank 请求 URL，不是普通 /v1 Base URL
ENABLE_RERANKER=true
RERANKER_PROVIDER=openai
RERANKER_API_BASE=https://reranker.example.com/rerank
RERANKER_API_KEY=<reranker-key>
RERANKER_MODEL=<reranker-model>
```

- `LLM_API_KEY` 必须非空；若可信的本地兼容网关不校验鉴权，也需要填写它接受的占位值。
- 模型 ID 必须与对应供应商实际暴露的名称一致。
- 修改 Embedding 模型、供应商或向量维度后，必须重新向量化已有知识库，不能在同一索引中混用不同 Embedding space。

## 4. 主机与 Docker 地址

| 模型服务位置 | 主机源码启动 | Docker 一键启动 |
|:---|:---|:---|
| 公网 / 局域网服务 | `https://models.example.com/v1` | 相同地址 |
| 当前主机上的服务 | `http://127.0.0.1:<port>/v1` | Docker Desktop 使用 `http://host.docker.internal:<port>/v1` |
| 另一台内网机器 | `http://<lan-ip>:<port>/v1` | 相同地址，但必须允许容器所在主机访问 |

Linux Docker 默认不保证解析 `host.docker.internal`。此时使用主机可达的局域网 IP，或在私有 Compose override 中添加 `host.docker.internal:host-gateway`。`DOCKER_BUILD_NETWORK=host` 只影响镜像构建阶段，不会改变容器运行时访问模型服务的网络方式。

## 5. 配置首个管理员

不配置 `INITIAL_ADMIN_*` 时，启动后在 Web 页面注册第一个本地账号即可。无人值守部署可配置：

```dotenv
INITIAL_ADMIN_EMAIL=owner@example.com
INITIAL_ADMIN_USERNAME=owner
INITIAL_ADMIN_PASSWORD=<strong-password>
# 生产可删除上一行，改用：
# INITIAL_ADMIN_PASSWORD_FILE=/run/secrets/mimirq_initial_admin_password
```

- 两个密码来源必须二选一。
- 密码文件路径是 API 进程或容器内路径；Docker 需要通过只读挂载或 Secret 提供。
- 相同配置再次启动不会重置密码；已有其他成员或冲突身份时系统会拒绝覆盖和自动提权。
- 多实例首次启动必须使用完全相同的值，创建成功后应从所有实例统一删除这些变量。

## 6. 启动与验证

Docker 一键启动：

```bash
make up-web
make ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

主机运行应用、Docker 运行基础设施：

```bash
make setup-host
# 默认 TASK_QUEUE_ENABLED=false，只需分别运行 API 与 Web
make backend
make web
```

需要独立队列时，先在 `.env` 设置 `TASK_QUEUE_ENABLED=true`，重启 API，再在第三个终端运行 `make worker`；可用 `make worker-check` 检查存活标记。Docker 一键启动默认启用队列并自动启动 Worker。

`/api/v1/health/ready` 只验证数据库、向量库、Redis、MinIO 等运行依赖，不代表外部模型已经连通。首次部署还应登录 Web、上传一份小文档、等待向量化完成，并执行一次带引用的检索或问答；启用 Reranker 时同时检查上游没有 401、404、429 或超时。

更多部署细节见 [快速入门](../quickstart.md) 与 [Docker Compose 部署指南](../deployment/docker_compose.md)。
