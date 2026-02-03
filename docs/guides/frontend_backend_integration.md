# 前后端联调指南（Frontend + Backend Integration）

这份文档用于本地开发时快速把 Next.js 前端和 FastAPI 后端跑起来，并提供常见联调排查路径。

## 1. 推荐方式：Docker Compose（后端 + 依赖）

从仓库根目录：

```bash
make init
make up
```

启动后访问：

- 后端 OpenAPI 文档：`http://localhost:8000/docs`
- 后端健康检查：`http://localhost:8000/api/v1/health`

## 2. 前端本地开发（Next.js）

```bash
cd web
pnpm install
pnpm dev
```

访问：`http://localhost:3000`

## 3. API Base URL / 环境变量

前端默认把后端当作 `http://localhost:8000`：

- `NEXT_PUBLIC_API_URL`：浏览器请求使用（默认 `http://localhost:8000`）
- `API_INTERNAL_URL`：SSR 场景可选（Docker 下 Next.js 容器内访问后端容器 DNS）

实现见：`web/lib/env.ts`。

### 常见坑：0.0.0.0 / 127.0.0.1 / localhost

- 浏览器无法访问 `http://0.0.0.0:8000`（只能访问 `localhost`/具体 IP）
- 如果你用局域网 IP 打开前端（如 `http://192.168.x.x:3000`），而 `NEXT_PUBLIC_API_URL` 仍是 `localhost`，手机/其它机器将无法访问后端

前端的 `web/lib/env.ts` 会对这些 loopback host 做尽力修正，但建议仍显式设置：

```bash
NEXT_PUBLIC_API_URL=http://<your-host-ip>:8000
```

## 4. CORS（跨域）说明

后端通过 `CORS_ORIGINS` 控制允许的来源；开发环境会自动扩展 `localhost/127.0.0.1/0.0.0.0` 的同端口别名，减少本地联调摩擦。

如果遇到 CORS 报错，优先检查：

1. 后端是否启动在你配置的端口（默认 8000）
2. `CORS_ORIGINS` 是否包含前端来源（默认 3000）

## 5. 联调自检命令（强烈建议）

### 5.1 前端一键自检

```bash
cd web
pnpm run verify
```

包含：lint + ui-check + typecheck + tests + api-check。

### 5.2 前后端路由契约检查（静态）

从仓库根目录：

```bash
make api-check
```

- `api-contract`: web 中实际调用的路由必须在后端存在
- `api-coverage`: 后端公开路由必须在 `web/lib/api-client.ts` 中有对应封装

### 5.3 OpenAPI 导出 + 前端类型同步

```bash
make openapi-check
```

会重新生成：

- `web/openapi.json`
- `web/types/openapi.ts`

## 6. UI 内置诊断页

前端提供 `/diagnostics` 页面展示：

- Backend Health / Ready
- Backend Meta
- Frontend Env（API_BASE_URL 等）

用于快速判断“前端是否在打到正确的后端”。

