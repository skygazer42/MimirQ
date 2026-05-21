# 全接口冒烟（API Smoke）

目标：在 **前后端深度联调** 场景下，对后端 **OpenAPI 全量接口** 做一轮端到端冒烟，确保：

- OpenAPI 中的每个 `METHOD + PATH` 都被覆盖（`Missing: 0`）
- 所有调用都返回符合预期的状态码（`Failures: 0`）

本仓库的冒烟入口是 `scripts/api_smoke.py`。

## 一键跑通（Docker 后端）

0) 准备 `.env`（可从 `.env.example` 复制并按需修改）

1) 启动后端（含依赖）

```bash
make up
```

> 若本机 `8000` 端口冲突，可临时改端口（示例：映射到 `18000`）：
>
> ```bash
> BACKEND_PORT=18000 make up
> ```

2) 运行全接口冒烟

```bash
make api-smoke
```

`make api-smoke` 会在 backend 容器内执行 `scripts/api_smoke.py`，并输出：

- `Calls: ...`
- `Failures: ...`
- `Missing: ...`

当 `Failures: 0` 且 `Missing: 0` 时，认为全接口冒烟通过。

## 结合前后端契约检查（推荐）

```bash
make api-check
```

该命令会校验：

- 前端调用的路由都在后端存在（防止“前端调了不存在的接口”）
- 后端暴露的路由都在前端 API Client 有入口（防止“后端新增接口但前端没对接”）

## 关于 LLM/Embedding

当前默认栈不再包含本地 `mock-openai`。要跑通涉及 Chat / RAG / Embedding 的接口，请在 `.env` 中配置可用的：

- `LLM_API_BASE` / `LLM_API_KEY`
- 以及必要时的 `EMBEDDING_*`
