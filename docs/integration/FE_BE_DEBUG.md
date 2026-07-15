# 前后端联调排障清单（从“能跑”到“可用 + 可排障”）

目标：当你在 `web/` 里看到“连不上后端 / 500 / 401 / CORS / SSE 断流”等问题时，用一套最短路径快速定位到 **是前端配置**、**后端服务**、还是 **依赖组件**（Postgres/Milvus/Redis/MinIO）导致。

---

## 0) 先确认你是哪种启动方式

### A. 全 Docker（推荐）
- 后端 + worker + infra：`make up`
- 前端（可选）：`make up-web`

### B. 本地后端 + Docker 跑依赖（开发常用）
- 依赖：`make infra-up`
- 本地后端：`pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt` → `python main.py`
- 本地前端：`cd web; pnpm dev`

不同启动方式下，前端访问后端的地址不同（见下文“API URL”）。

---

## 1) 后端是否真的“就绪”？

优先看 readiness（会检查 DB / Milvus / Redis / MinIO）：
- `GET http://localhost:8000/api/v1/health/ready`

快速健康检查：
- `GET http://localhost:8000/api/v1/health`

也可以用一键 ping（更适合排查“前端连不上后端”这类问题）：
- `make api-ping`（可用 `BACKEND_BASE_URL=...` 覆盖默认 `http://localhost:8000`）

如果 `health/ready` 返回 `503`：
- 看 `database/vector/redis/minio` 的 `status` 字段
- Docker：`make logs` 或 `docker compose -f docker/docker-compose.yml logs -f mimirq-api`

也可以直接在前端打开诊断页：
- `GET http://localhost:3000/diagnostics`

---

## 2) 前端的 API URL 是否正确？

前端默认读环境变量：
- `NEXT_PUBLIC_API_URL`（浏览器用）
- `API_INTERNAL_URL`（仅 SSR/容器内用，**不会**暴露给浏览器）

### 浏览器必须能访问到的地址
一般是：
- `NEXT_PUBLIC_API_URL=http://localhost:8000`

> 不要把 `NEXT_PUBLIC_API_URL` 配成 `http://mimirq-api:8000`（这是 Docker 内部 DNS，浏览器不认识）。

### Docker 前端（SSR）需要容器内地址时
在 `.env` 配：
- `API_INTERNAL_URL_DOCKER=http://mimirq-api:8000`

对应代码逻辑见：`web/lib/env.ts`

---

## 3) 常见错误速查

### ① 前端提示“网络错误/无法连接后端”
- 后端没起：先测 `http://localhost:8000/api/v1/health/ready`
- 端口不对：检查 `.env` 里的 `BACKEND_PORT`（若你改过）
- 前端 API URL 不对：检查 `NEXT_PUBLIC_API_URL`

### ② CORS 报错
Docker 默认允许：
- `http://localhost:3000,http://localhost:3001`

检查：
- `docker/docker-compose.yml` 里的 `CORS_ORIGINS`
- 或后端配置项 `CORS_ORIGINS`

### ③ 401/403（未授权/无权限）
若你显式使用 `AUTH_MODE=header`（仅限本地开发）：
- 前端会发 `X-User-ID`（来自 `NEXT_PUBLIC_USER_ID` 或 localStorage）
- 租户用 `X-Tenant-ID`（来自 `NEXT_PUBLIC_TENANT_ID` 或 localStorage）

若你用 `AUTH_MODE=jwt`：
- 需要先登录拿 token（前端会写入 `localStorage.mimirq_access_token`）

### ④ 422（参数错误）
看后端返回的 `detail`，并留意 `X-Request-ID`：
- 前端会为每个请求生成并透传 `X-Request-ID`
- 后端错误响应也会带 request_id（便于日志定位）

---

## 4) “接口对不上 / 前端调了不存在的 API”

运行契约检查（会校验前端调用与后端路由一一对应）：
- `make api-check`

生成 OpenAPI 类型（前端 types）：
- `make openapi-types`

相关说明：`docs/integration/API_CONTRACT.md`
