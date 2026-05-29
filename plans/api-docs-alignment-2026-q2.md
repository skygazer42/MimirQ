# MimirQ API 文档对齐接口 plan

> 创建日期:2026-05-29
> 触发:用户要求"完善项目 API 文档,对齐接口"。范围=全面,重点=对齐最近改动 + 提升 /docs 质量。

## Context

MimirQ 的 API 文档体系**已相当成熟**:FastAPI `/openapi.json` + `/docs` + `/redoc` 全开;402 endpoint 100% 有 summary;导出/校验/CI 管线齐全(`make openapi-export` / `openapi-types` / `api-check`,`pnpm verify` 含 api-check,CI 有 `make openapi-check` + handbook-matrix `git diff --exit-code` 校验)。

但调研暴露 4 个真实缺口,其中第 1 个最紧迫:

1. **`web/openapi.json` 过期(停在 May 27)**:不含最近加的 `GET /api/v1/pipeline/governance-processing-scripts/builtins`。CI 的 handbook-matrix job 会因 `git diff --exit-code` 失败。`openapi.ts`(前端 51k 行生成类型)也跟着过期。**根因**。
2. **手写类型 drift**:`web/lib/api/` 32 模块中 21 个用 `apiClient` 直调 + 手写类型(72 个),不走 openapi 生成。其中 `industry-rules.ts`(10 类型)对应后端 `industry_rules.py` **返回 `dict[str,Any]` 完全无 response_model**,无法生成类型。
3. **description 覆盖率 59%**(165/402 endpoint 缺)、部分 endpoint 缺 response_model(`chat.py` 50%)。
4. **api-check 只检路由存在,不检字段级契约**。

用户选定:**范围=全面**,**重点=优先对齐最近改动 + 提升 /docs 质量**。

---

## 关键复用(不造新轮子)

| 资产 | 路径 | 复用方式 |
|---|---|---|
| OpenAPI 导出 | `scripts/export_openapi.py` + `web/scripts/export-openapi.mjs` | 直接跑 `make openapi-export` 重生成 |
| 类型生成 | `web/package.json` `gen:api-types`(openapi-typescript 7.13) | `make openapi-types` |
| 路由契约校验 | `web/scripts/check-api-contract.mjs` + `check-api-coverage.mjs` | 跑 `make api-check`,真相源是直接扫后端 decorator |
| OpenAPI 校验 | `scripts/openapi_check.py` + `web/scripts/check-openapi-coverage.mjs` | `make openapi-validate` |
| 类型别名层 | `web/types/backend.ts`(206 行 `OpenApiSchema<'X'>` 别名) | 手写类型迁移目标 |
| 现代调用风格 | `web/lib/api/pipeline.ts` 的 `openapiRequest({path,method})` | 迁移 B 类模块的范本 |
| 契约文档 | `docs/integration/API_CONTRACT.md` | 更新流程说明 |
| 静态文档站 | `docs/api/site/`(Redoc + openapi.json)+ `reference/`(28 手写 md) | 同步 openapi.json + 补 reference |

---

## 分层方案

### Layer 0 — 根因修复:重新生成 + drift 归零(必做,最高优先)

把过期的 openapi.json/ts 拉回与后端代码一致。

1. `make openapi-export` → 重生成 `web/openapi.json`(纳入 `governance-processing-scripts/builtins` + 最近所有 endpoint)
2. `make openapi-types` → 重生成 `web/types/openapi.ts`
3. 同步 `docs/api/site/openapi.json`(`make api-docs-build` 或手动 copy)
4. `make api-check` + `make openapi-validate` → 确认 0 路由 drift、0 coverage 缺口
5. 若 api-coverage 报 `governance-processing-scripts/builtins` 前端无入口 → 已有 `pipeline.ts::listBuiltinProcessingScripts`,确认路径匹配

**产出**:`git diff` 后 openapi.json/ts 更新提交,CI handbook-matrix 恢复绿。

### Layer 1 — 对齐最近改动(后端 schema 补全,高价值)

让最近几轮加的功能 API 全部可生成类型 + 文档完整。

| 改动模块 | 当前问题 | 动作 |
|---|---|---|
| **industry_rules** `app/api/v1/industry_rules.py` | 返回 `dict[str,Any]`,无 response_model,前端手写 10 类型 | 在 `app/api/schemas/` 新建 `industry_rules.py`,定义 `IndustryRulesetSummary/Detail/ListResponse/...` Pydantic schema(对照 `app/rag/industry_rules/` 的 dataclass),给每个 endpoint 加 `response_model=` |
| **governance-processing-scripts** | response_model 已就绪(我上轮加的 `BuiltinProcessingScriptListResponse`) | 仅需 Layer 0 重生成;补 endpoint description + 示例 |
| **prompt_templates** `app/api/v1/prompt_templates.py` | response_model 全有,但前端 `prompts.ts` 手写 `PromptTemplateCreate` 缺 6 字段(template_key/version/parent_id/ab_*) | 后端 schema 已全;此项归 Layer 3 前端迁移 |

### Layer 2 — 提升 /docs 自动文档质量(后端 endpoint 元数据)

description 59% → 目标核心模块 100%、整体显著提升。**务实策略:不逐个手写 165 个,按优先级批量补**。

优先级顺序(高→低):
1. **最近改动模块**:`prompt_templates.py`(8)、`pipeline.py` governance 相关(~10)、`industry_rules.py`(~10)
2. **核心高频模块**:`chat.py`(2,且补 response_model)、`documents.py`、`datasets.py`
3. **其余**:按路由文件逐个扫,补缺 description 的

每个 endpoint 的 description 统一风格:**做什么 + 关键参数语义 + 返回结构 + 典型错误场景**。缺 response_model 的(chat.py 等)补上。高频错误用 `responses={400:..., 404:..., 409:...}` 补错误码示例(已有部分模块用 `_DEFAULT_HTTP_EXCEPTION_RESPONSES`,复用)。

### Layer 3 — 前端手写类型 drift 根治

按"已就绪→需补后端"顺序迁移 B 类模块到 `openapiRequest` + 生成类型:

| 模块 | 难度 | 动作 |
|---|---|---|
| `pipeline.ts` `BuiltinProcessingScript` | 低(字段已对齐+后端有 schema) | Layer 0 后,改 import 自 `@/types` 别名,删手写 type |
| `prompts.ts`(5 类型) | 中(后端 schema 全,前端缺字段) | 迁到 `openapiRequest`,类型用生成的 `PromptTemplateOut` 等;补齐 Create 缺的 6 字段 |
| `industry-rules.ts`(10 类型) | 高(依赖 Layer 1 后端补 schema) | Layer 1 完成后迁移 |
| 其余 B 类(access/audit/dify/graph/ltr/scim/settings/observability 等) | 不在本次重点 | 列入后续渐进清单,不强行做完 |

### Layer 4 — 字段级 drift 检测 + 手写文档对齐(全面收口)

1. **新增 `web/scripts/check-api-types-drift.mjs`**:不只检路由存在,还对比 `web/lib/api/*.ts` 手写 type 与 `openapi.ts` 对应 schema 的字段集,报告字段级偏差。挂进 `make api-check`(warning 级,不阻断,逐步收紧)。
2. **`docs/api/reference/`**:更新受影响的 numbered md(提示词 / 治理 / 行业规则章节),加最近 endpoint。
3. **`docs/integration/API_CONTRACT.md`**:更新"加 endpoint 后必跑 `make openapi-types`"流程 + 新增字段级 drift 检测说明。

---

## 修改/新建文件清单

### 重新生成(Layer 0)
- `web/openapi.json`(2.1MB,重生成)
- `web/types/openapi.ts`(51k 行,重生成)
- `docs/api/site/openapi.json`(同步)

### Backend schema 补全(Layer 1-2)
- **新建** `app/api/schemas/industry_rules.py`(~150 行,10 个 Pydantic schema)
- `app/api/v1/industry_rules.py`(加 response_model + description)
- `app/api/v1/prompt_templates.py`(补 description/示例)
- `app/api/v1/pipeline.py`(governance-processing-scripts 等补 description)
- `app/api/v1/chat.py`(补 response_model + description)
- 其余路由文件按 Layer 2 优先级补 description(模式重复,代表:`documents.py` `datasets.py`)

### Frontend 类型迁移(Layer 3)
- `web/lib/api/pipeline.ts`(BuiltinProcessingScript → 生成类型)
- `web/lib/api/prompts.ts`(迁 openapiRequest)
- `web/lib/api/industry-rules.ts`(Layer 1 后迁移)
- `web/types/backend.ts`(加新 schema 别名)

### 工具 + 文档(Layer 4)
- **新建** `web/scripts/check-api-types-drift.mjs`(~120 行)
- `web/package.json` / `Makefile`(挂 drift 检测)
- `docs/api/reference/*.md`(更新受影响章节)
- `docs/integration/API_CONTRACT.md`(更新流程)

---

## YAGNI(本次不做)

- 不逐个手写补完全部 165 个 description(按优先级批量,核心 + 最近改动先达 100%,其余渐进)
- 不强行迁移全部 21 个 B 类手写模块(只迁最近改动相关 3 个 + 范本;其余列渐进清单)
- 不改 `scripts/export_openapi.py` / `check-api-contract.mjs` 等已工作的核心管线逻辑
- 不引入新文档框架(沿用 Redoc + reference md)
- 不动路由 URL / RBAC / 业务逻辑

---

## Verification

按序跑,任一失败停下修:

1. **重生成无遗漏**
   - `cd /data/temp34/MimirQ && make openapi-export`
   - `grep -c "governance-processing-scripts/builtins" web/openapi.json` 应 ≥ 1
   - `python3 -c "import json; d=json.load(open('web/openapi.json')); print('paths:', len(d['paths']))"` 路径数 ≥ 之前

2. **类型生成 + 编译**
   - `make openapi-types`(重生成 openapi.ts)
   - `cd web && pnpm typecheck`(确认生成类型无破坏)

3. **契约校验 0 drift**
   - `make api-check` → contract + coverage 都 0 报错
   - `make openapi-validate` → openapi_check.py 通过

4. **Layer 1 后端 schema**
   - `python3 -c "from app.api.schemas.industry_rules import IndustryRulesetListResponse; print('OK')"`
   - 启动后端 `curl localhost:8000/openapi.json | python3 -c "import json,sys; d=json.load(sys.stdin); p=d['paths']['/api/v1/industry-rules']['get']; print('response_model:', 'application/json' in p['responses']['200'].get('content',{}))"` 应 True
   - `ruff check app/api/schemas/industry_rules.py app/api/v1/industry_rules.py`

5. **description 提升量化**
   - 写一次性脚本统计 `make openapi-export` 后 description 覆盖率,核心模块(prompt_templates/pipeline/industry_rules/chat)应 100%,整体显著 > 59%

6. **前端迁移**
   - `cd web && pnpm typecheck && pnpm lint`
   - `pnpm test --run`(api 模块相关测试)

7. **字段级 drift 脚本**
   - `node web/scripts/check-api-types-drift.mjs` 跑通,输出字段偏差报告

8. **全量验证**
   - `make verify`(含 api-check)全绿
   - `cd web && pnpm verify`

---

## 工作量与时间线

| Layer | 内容 | 时长 |
|---|---|---|
| L0 根因修复 | 重生成 + drift 归零 | 0.5 天 |
| L1 对齐最近改动 | industry_rules schema + 最近 endpoint 元数据 | 1-1.5 天 |
| L2 /docs 质量 | 核心模块 description + response_model 批量补 | 2-3 天 |
| L3 前端迁移 | pipeline/prompts/industry-rules 3 模块 | 1 天 |
| L4 drift 脚本 + 文档 | check-api-types-drift + reference 更新 | 1 天 |
| **合计** | | **5.5-7 天**(L0-L1 是必做最小集,1.5-2 天可见对齐效果) |

## 风险

| 风险 | 缓解 |
|---|---|
| 重生成 openapi.ts 引入破坏性类型变更 | Layer 0 后立即 `pnpm typecheck`,有破坏先修再继续 |
| industry_rules schema 与 dataclass 字段对不上 | 补 schema 前先读 `app/rag/industry_rules/` 全部 dataclass,严格 1:1 |
| 批量补 description 风格不一 | 统一模板(做什么+参数+返回+错误),先定 1 个范本再扩 |
| 前端迁移破坏现有调用 | 每迁一个模块单独 typecheck + 该模块 source test |
| 字段级 drift 脚本误报多 | 首版 warning 级不阻断 CI,观察后再收紧为 error |
| openapi.json 重生成需要后端可 import | export_openapi.py 设 `MIMIRQ_OPENAPI_EXPORT=1` 避副作用,确认依赖可加载 |

## 与既有 plan 协同

| 既有 plan | 关系 |
|---|---|
| `plans/industry-rules-productization-2026-q2.md` | 本 plan Layer 1 补的 industry_rules response_model 是其 API 化的前置 |
| `docs/integration/API_CONTRACT.md` | 本 plan Layer 4 更新它 |
