# 前后端接口契约（API Contract）

目标：保证 **后端提供的每个 API** 都在前端有明确的“对应入口”（统一放在 `web/lib/api-client.ts`），并且前端不会调用不存在的后端路由。

## 一键检查

```bash
# 1) 导出 OpenAPI + 生成前端 types
make openapi-types

# 2) 校验接口对应关系
make api-check
```

前端侧（在 `web/` 目录）也可直接运行：

```bash
pnpm run openapi-types
pnpm run api-check
```

`make api-check` 会执行两类校验：

1. `web/scripts/check-api-contract.mjs`：前端代码里出现的 API 调用，必须在后端存在对应路由（防止“前端调了不存在的接口”）。
2. `web/scripts/check-api-coverage.mjs`：后端 `app/api/v1/*`（含 KG）里的路由，必须在 `web/lib/api-client.ts` 出现对应调用（防止“后端新增接口但前端没有入口”）。

## 开发约定（新增/修改接口时）

- 后端：为接口补齐 `response_model`（以及必要的请求 schema），确保 `web/openapi.json` 能产出稳定类型。
- 前端：在 `web/lib/api-client.ts` 增加/更新对应方法，并让页面/Hook 优先走该方法。

## 无 diff 策略（OpenAPI 生成物）

`make openapi-check` 会在生成后校验 `web/openapi.json` 和 `web/types/openapi.ts` **无差异**。
如果有 diff，请先执行 `make openapi-types` 并提交更新。
