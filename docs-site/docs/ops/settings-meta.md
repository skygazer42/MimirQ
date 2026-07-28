---
sidebar_label: "配置参考"
sidebar_position: 5
---

# 运行配置参考

MimirQ 使用 Pydantic Settings 从进程环境和仓库根目录 `.env` 读取配置。变量全集与注释以 [`.env.example`](https://github.com/skygazer42/MimirQ/blob/main/.env.example) 和 `app/core/config.py` 为准。

:::info 初始化行为
`make init` 只创建缺失的 `.env` / `web/.env.local`，自动填充 `SECRET_KEY` 和 `MARKDOWN_IMAGE_PROXY_SECRET`，不会覆盖已有配置。
:::

## 最小真实模型闭环

```dotenv
LLM_API_KEY=<your-siliconflow-api-key>
```

| 变量 | 默认值 / 回退规则 | 说明 |
|:---|:---|:---|
| `LLM_API_BASE` | `https://api.siliconflow.cn/v1` | OpenAI-compatible LLM Base URL |
| `LLM_MODEL` | `Qwen/Qwen3-32B` | 主模型名称 |
| `EMBEDDING_PROVIDER` | `openai_compatible` | 默认远程兼容接口 |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | 默认向量模型 |
| `EMBEDDING_API_KEY` | 空时复用 `LLM_API_KEY` | 独立服务时显式填写 |
| `EMBEDDING_API_BASE` | 空时复用 `LLM_API_BASE` | 独立服务时显式填写 |
| `ENABLE_RERANKER` | `false` | 设为 `true` 才启用重排 |
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | 默认重排模型 |
| `RERANKER_API_KEY` | 空时复用 `LLM_API_KEY` | 可与 LLM 共用凭据 |
| `RERANKER_API_BASE` | `https://api.siliconflow.cn/v1/rerank` | 完整 rerank 请求端点，不是普通 `/v1` Base URL |

三个服务分离时的可复制示例见[快速开始](./getting-started)。修改 Embedding 模型、供应商或维度后，必须重新向量化已有知识库。

## 认证与首个管理员

| 变量 | 本地默认 / 用途 |
|:---|:---|
| `AUTH_MODE` | 默认 `jwt`；`header` 仅限受控本机调试，生产禁止 |
| `SECRET_KEY` | JWT 签名密钥，`make init` 自动生成 |
| `INITIAL_ADMIN_EMAIL` | 可选，首次自动创建 owner 的邮箱 |
| `INITIAL_ADMIN_USERNAME` | 可选，首次自动创建 owner 的用户名 |
| `INITIAL_ADMIN_PASSWORD` | 本地可用的密码来源 |
| `INITIAL_ADMIN_PASSWORD_FILE` | 生产推荐的文件 / Secret 密码来源，与明文密码二选一 |
| `INITIAL_REGISTRATION_TOKEN` | 不使用自动管理员时的可选手工首登保护 |

只要填写任意 `INITIAL_ADMIN_*`，就必须同时提供邮箱、用户名以及恰好一种密码来源。多实例首次启动必须使用相同值，成功后统一删除。

## 数据与任务依赖

| 依赖 | 主机变量 | Docker 变量 |
|:---|:---|:---|
| PostgreSQL | `DATABASE_URL` | 由 `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` 组装容器连接串 |
| Redis | `REDIS_URL` | `REDIS_URL_DOCKER` |
| Milvus | `MILVUS_HOST` / `MILVUS_PORT` | `MILVUS_HOST_DOCKER` / `MILVUS_PORT_DOCKER` |
| MinIO | `MINIO_*` | `MINIO_*_DOCKER` |
| 任务队列 | `TASK_QUEUE_ENABLED` | `TASK_QUEUE_ENABLED_DOCKER` |

主机默认 `TASK_QUEUE_ENABLED=false`，由 API 进程内有界处理后台任务，不需要 Worker；改为 `true` 后必须同时运行 `make worker`。Docker 默认启用队列并启动 Worker。不要把 Docker 内部服务名填进浏览器或主机进程使用的地址。

## 前端变量

| 变量 | 用途 |
|:---|:---|
| `NEXT_PUBLIC_API_URL` | 主机前端 / 浏览器访问后端的 URL，默认 `http://localhost:8000` |
| `NEXT_PUBLIC_API_URL_DOCKER` | Docker Web 给浏览器使用的地址，默认同源 `/` |
| `API_INTERNAL_URL_DOCKER` | Docker Web 的 SSR 在容器内访问 API 的地址 |
| `NEXT_PUBLIC_API_TIMEOUT_MS` | 常规前端请求超时 |
| `NEXT_PUBLIC_API_LONG_TIMEOUT_MS` | 上传、解析等长任务超时 |

`NEXT_PUBLIC_*` 会进入客户端产物，禁止放置密钥。修改后需要重新启动开发服务或重新构建前端镜像。

## 配置何时生效

- `.env` 中的后端变量在 API / Worker 启动时加载；修改后重启对应进程或容器。
- Web 设置页面或 Settings API 只管理其明确支持的业务设置，不能覆盖任意环境变量。
- 修改 Embedding 配置还需要为受影响知识库重新向量化。
- 修改 `SECRET_KEY` 会让已有本地 JWT 失效。

生产环境应使用 Docker Secret、Kubernetes Secret 或外部 Secret Manager 注入数据库密码、对象存储凭据、模型 Key 和管理员密码，不要把真实密钥提交到仓库或镜像层。

相关页面：[快速开始](./getting-started) · [部署指南](./deployment) · [健康检查](./health-probes)
