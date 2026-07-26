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

`make api-check` 会执行三类校验：

1. `web/scripts/check-api-contract.mjs`：前端代码里出现的 API 调用，必须在后端存在对应路由（防止“前端调了不存在的接口”）。
2. `web/scripts/check-api-coverage.mjs`：后端 `app/api/v1/*`（含 KG）里的路由，必须在 `web/lib/api-client.ts` 出现对应调用（防止“后端新增接口但前端没有入口”）。
3. `web/scripts/check-api-types-drift.mjs`：**字段级类型漂移检测**。报告 `web/lib/api/*.ts` 中仍手写 response/request 类型（而非消费生成类型 `@/types/backend`）的模块——这些手写类型在后端 schema 变更时会静默漂移。默认 **warning 级**（exit 0，不阻断 CI）；`cd web && node scripts/check-api-types-drift.mjs --strict --baseline scripts/api-types-drift-baseline.json`（即 `pnpm -C web api-types-drift`）会在手写类型模块数超过 baseline 时失败。随迁移推进应逐步收紧 `web/scripts/api-types-drift-baseline.json` 棘轮基线。

## 开发约定（新增/修改接口时）

- 后端：为接口补齐 `response_model`（以及必要的请求 schema），确保 `web/openapi.json` 能产出稳定类型。返回 `dict[str, Any]` 的接口**无法生成类型**，前端只能手写——务必定义 Pydantic schema（参考 `app/api/schemas/industry_rules.py`）。
- 前端：优先用 `openapiRequest({path, method})` + `@/types/backend` 的 `OpenApiSchema<'X'>` 别名，避免在 `web/lib/api/*.ts` 手写 type。新增后端 schema 后，在 `web/types/backend.ts` 加一行别名即可（如 `export type Foo = OpenApiSchema<'FooOut'>`）。
- 改动后端接口后**必跑** `make openapi-types` 重新生成 `web/types/openapi.ts` 并提交。

## 无 diff 策略（OpenAPI 生成物）

`make openapi-check` 会在生成后校验 `web/openapi.json` 和 `web/types/openapi.ts` **无差异**。
如果有 diff，请先执行 `make openapi-types` 并提交更新。

## 手写类型迁移进度（drift 治理）

`check-api-types-drift.mjs` 给出仍手写类型的模块清单作为治理 baseline。已迁移到生成类型的模块：`pipeline.ts`（BuiltinProcessingScript）、`industry-rules.ts`（全部 10 类型）。待迁移长尾（按手写类型数）：`settings.ts`、`rag.ts`、`evaluation.ts`、`parsing.ts`、`prompts.ts` 等——这些需要后端先补齐对应 `response_model`/schema 后再迁。
