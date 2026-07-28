---
sidebar_label: "快速开始"
sidebar_position: 2
---

# 从 `.env` 到首次登录

这页是新用户的配置入口。先生成 `.env`，确认模型服务和首个管理员方案，再选择 Docker 一键启动或主机源码启动。完整变量定义以仓库根目录的 [`.env.example`](https://github.com/skygazer42/MimirQ/blob/main/.env.example) 为准。

## 1. 生成本地配置

```bash
git clone --depth 1 --single-branch https://github.com/skygazer42/MimirQ.git
cd MimirQ
make init
```

没有 GNU Make 时运行 `python scripts/init_env.py`。该命令只创建缺失的 `.env` / `web/.env.local`，并自动生成 `SECRET_KEY` 与 `MARKDOWN_IMAGE_PROXY_SECRET`；不会覆盖已有值。

## 2. 填写最小模型配置

默认 SiliconFlow 方案完成真实 LLM 与 Embedding 调用只需填写：

```dotenv
LLM_API_KEY=<your-siliconflow-api-key>
```

| 能力 | 默认行为 | 什么时候修改 |
|:---|:---|:---|
| LLM | `Qwen/Qwen3-32B` | 换供应商时填写 `LLM_API_BASE` / `LLM_MODEL` |
| Embedding | `BAAI/bge-m3`，复用 LLM 的 Key/Base URL | 独立服务时填写 `EMBEDDING_API_KEY` / `EMBEDDING_API_BASE` / `EMBEDDING_MODEL` |
| Reranker | 默认关闭 | 设置 `ENABLE_RERANKER=true`；独立服务还要填写完整端点、Key 和模型 |
| 首个管理员 | 在 Web 页面手工注册 | 无人值守部署时配置 `INITIAL_ADMIN_*` |

`LLM_API_KEY` 是真实知识库闭环的最低要求，不是 API 进程存活的必要条件。未配置时健康探针仍可能通过，但聊天、向量化或入库会失败。默认 Reranker 地址已经是完整请求端点，Key 可复用 `LLM_API_KEY`。

## 3. 可选：自动创建首个 owner

```dotenv
INITIAL_ADMIN_EMAIL=owner@example.com
INITIAL_ADMIN_USERNAME=owner
INITIAL_ADMIN_PASSWORD=<strong-password>
# 生产环境可删除上一行，改用：
# INITIAL_ADMIN_PASSWORD_FILE=/run/secrets/mimirq_initial_admin_password
```

两个密码来源必须二选一。相同配置重启不会重置密码；默认租户已有其他成员时，后端会拒绝覆盖或自动提权。多实例必须使用相同值，并在首次初始化成功后从所有实例删除这些变量。

## 4. 三个模型使用独立服务

```dotenv
LLM_API_BASE=https://llm.example.com/v1
LLM_API_KEY=<llm-key>
LLM_MODEL=<chat-model>

EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_BASE=https://embedding.example.com/v1
EMBEDDING_API_KEY=<embedding-key>
EMBEDDING_MODEL=<embedding-model>

ENABLE_RERANKER=true
RERANKER_PROVIDER=openai
RERANKER_API_BASE=https://reranker.example.com/rerank
RERANKER_API_KEY=<reranker-key>
RERANKER_MODEL=<reranker-model>
```

`RERANKER_API_BASE` 是完整 rerank 请求 URL，不是普通 Chat Completions `/v1` 地址。更换 Embedding 模型、供应商或向量维度后，必须重新向量化已有知识库，不能混用不同 embedding space。

## 5. 选择启动方式

Docker 一键启动：

```bash
make up-web
make ps
curl --noproxy '*' -f http://localhost:8000/api/v1/health/ready
```

`make up-web` 会同时启动 Web、API、Arq Worker、Postgres、Milvus、Etcd、MinIO 与 Redis。

主机源码进程、Docker 基础设施：

```bash
make setup-host
# 分别在两个终端运行
make backend
make web
```

主机默认 `TASK_QUEUE_ENABLED=false`，后台任务由 API 进程内有界处理。需要独立队列时，先在 `.env` 设置 `TASK_QUEUE_ENABLED=true`，重启 API，再在第三个终端运行 `make worker`；可用 `make worker-check` 验证 Worker。Docker 一键启动默认启用队列。

## 6. 地址与验收

主机进程访问同机模型服务可使用 `127.0.0.1`；容器内的 `127.0.0.1` 指容器自身，应改用容器可达的局域网地址，Docker Desktop 也可使用 `host.docker.internal`。Linux 可能需要私有 Compose host-gateway override。

readiness 只验证基础设施，不证明外部模型可用。首次部署还应登录 Web、上传一份小文档、等待索引完成，并执行一次带引用的检索或问答。

相关入口：[配置参考](./settings-meta) · [部署指南](./deployment) · [健康检查](./health-probes)
