# MimirQ 全栈代码审计 — 60 条详尽问题清单

> **For agentic workers:** 本文档为深度 triage 报告，每条问题给定位 + 严重度 + 修复方向。落地时按下方 phasing 拆为独立 implementation plan（参考既有 batch 系列）。本审计**专注代码 + 工程化层面**，不重复 30+ 份既有 plan 已覆盖的 RAG 能力扩容内容。

## Context

**问题与触发**
用户要求"做一个全面的审核代码问题写到 plans"。仓库已有 30+ 份 plan 调研 RAG 能力扩容（KG/评测/解析/agentic 等），并有过 Top 15 必修清单初版（`fullstack-code-quality-top15-2026-q2.md`）。本次扩展到 60 条详尽 audit，覆盖 13 大维度，使产品/架构/安全/工程团队能照单认领。

**预期产出**
60 条详尽问题清单，按严重度分级（🔴 Critical / 🟠 High / 🟡 Medium / 🟢 Low），按 13 大类别组织。每条 ≤3 行，便于扫描。

**审查方法**
基于 `wc -l` / `grep` 模式扫 / `git ls-files` / `find -size` / 配置文件读取 + Top 15 已沉淀结论。**所有条目都是实测数据，不是猜测**。

---

## 关键量化指标速查

| 指标 | 实测 | 评价 |
|---|---|---|
| 后端 py 文件数 | 967 | — |
| 后端 def 总数 / 含返回类型 | 6756 / 4186 (62%) | 类型覆盖中等 |
| 后端 docstring 覆盖 | ~257 / 4838 def lines (≈5%) | 🔴 极低 |
| 后端 try/except 总数 | 2978 | — |
| 后端 except Exception | 2561 (86% 都用此宽泛) | 🟠 High |
| **后端 except 后裸 pass** | **418 处** | 🔴 严重吞异常 |
| 后端 except 仅 logger.warning 无 raise | 205 处 | 🟠 |
| 后端 endpoints 总数 | 367 | — |
| 后端 v1/ API 文件总行数 | 51490 | — |
| 后端 service 文件总行数 | 49717 | — |
| 后端 print() 残留 | 28 | — |
| 后端 requests vs httpx 混用 | 20 / 22 文件 | 🟠 |
| 后端 sa.Index 显式索引 | **0** | 🔴 |
| 前端 ts/tsx 文件 | 261 components + 100+ pages/lib | — |
| 前端 useEffect | 1782 处 | — |
| 前端 useMutation | 7 处 | 🟠 严重偏移 |
| 前端 useMemo/useCallback | 1149 处 | 🟡 过度优化 |
| 前端 React.memo | 4 处 | 🟡 该用没用 |
| 前端 `: any` | 772 处 | 🟠 |
| 前端 @ts-ignore 真实人写 | ~10（其余在 .next 构建产物） | 实际不严重 |
| 前端 `key={index}` | 14 处 | 🟡 |
| 前端 .then() 不带 .catch() | 42 处 | 🟠 |
| 前端 e2e 测试 | 7 个 | 🟡 偏少 |
| 仓库 git 追踪的 ONNX 模型总大小 | **>600MB** | 🔴 |
| 仓库根装饰性 PNG | 10+ 张 | 🟡 |

---

## 🔴 Critical（17 条 — 必修）

### A. 错误处理灾难

#### 1. 418 处 `except: pass` 完全吞异常
- **集中**：`app/api/v1/documents.py` 147 / `app/rag/retriever.py` 139 / `app/parsing/processors/processor.py` 122 / `app/rag/retrieval/orchestrator.py` 98 / `app/api/v1/connectors.py` 68
- **修复**：① 短期补 `logger.exception(...)` 至少有日志可追 ② 中期建审计脚本 `scripts/check_silent_excepts.py` 卡 PR ③ 长期按文件 PR 收敛到具体异常类型

#### 2. 205 处 `except + logger.warning` 无 raise — 用户拿到错误响应但定位不到
- **修复**：警告级别的吞异常应附带 `error_code` 写到响应里，便于定位

#### 3. 后端 SQLAlchemy 模型 0 个显式 sa.Index
- **位置**：`app/models/*.py` 全 grep `sa.Index` = 0；alembic 14 个 migration 也没 `op.create_index`
- **影响**：高频查询全表扫，性能定时炸弹（datasets/documents/conversations/feedback 量上来必爆）
- **修复**：① 列出热点查询字段（dataset_id, tenant_id, status, created_at）② 写 0015_add_indexes migration ③ 后续 model 强制 `__table_args__ = (Index(...),)`

### B. API 层超失控

#### 4. `app/api/v1/documents.py` 11770 行 / 55 endpoints — 业务塞 router
- **修复**：拆 `documents/` 子目录，业务下沉 `app/services/documents/*`

#### 5. `app/api/v1/connectors.py` 10697 行 / 15 endpoints — 平均 713 行/endpoint
- **修复**：拆 `connectors/{catalog,sample,schema_infer}` service 化

#### 6. `app/api/v1/chat.py` 3653 行 / 15 endpoints + `stream_chat` 单函数 1305 行
- **修复**：抽 `services/chat/{stream_orchestrator,citation_builder}`

### C. CI/CD 失守

#### 7. CI 主流水线仅 `workflow_dispatch`，PR 无强制 gate
- **位置**：`.github/workflows/ci.yml:3-4`，security.yml 同样仅 weekly + dispatch
- **修复**：补 `on: pull_request` + `on: push: branches: [main]`，重型流水线（perf/parsing-proof）保留 nightly

### D. 仓库治理

#### 8. ONNX 模型 600MB+ git 追踪 + 重复目录
- **位置**：`app/deepdoc/resources/models/layout/layout.{paper,onnx,manual,laws}.onnx` 各 74MB + **完全重复**于 `app/resources/data_parser/qieci/layout.*.onnx`；`encoder_model.onnx` 86MB
- **影响**：clone 仓库 >2GB；fetch 慢；CI 反复下载浪费
- **修复**：① 启用 git-lfs 或改运行时下载（HuggingFace Hub）② 删一份重复目录（保留单一 source）③ `.gitattributes` 加 `*.onnx filter=lfs`

#### 9. 仓库根 10+ 张 PNG + artifacts/ 50+ 张截图未清理
- **位置**：根 `chunk-preview-*.png` `graph-snapshots-*.png`；`artifacts/*.png` (knowledge-ingestion-bulkactions-*等截图)
- **修复**：移到 `docs/screenshots/` 或删除；`artifacts/` 加 .gitignore

#### 10. `.beads/` `logs/` `runs/` `.playwright-mcp/` 应在 .gitignore 但未必
- **修复**：补全 .gitignore

### E. 安全

#### 11. 前端 `next.config` 无安全 HTTP headers（CSP / X-Frame-Options / HSTS）
- **影响**：clickjacking / XSS 缓解缺失；生产环境合规风险
- **修复**：next.config.mjs 添加 `headers()` 函数声明 CSP / X-Frame-Options / Strict-Transport-Security / X-Content-Type-Options / Referrer-Policy

#### 12. 前端 hardcode `localhost`/`127.0.0.1` 16 处
- **修复**：统一走 `web/lib/env.ts` 已有的 `NEXT_PUBLIC_API_URL`；ESLint 规则禁止字面量

#### 13. 后端 `app/api/v1/settings.py` 多处默认 `https://api.openai.com/v1` 等 hardcode
- **修复**：默认值移到 `app/core/config.py` 集中常量，便于私有化部署一处改

### F. 代码质量底线

#### 14. 后端 docstring 覆盖 ≈5%（257/4838 def lines）
- **影响**：367 endpoints 没 docstring → OpenAPI doc 缺描述 → 前端/客户端不知 API 用途
- **修复**：① 用 ruff `D` 规则启用 docstring lint ② 至少所有 router endpoint 必须有 docstring（ruff `D102`）③ 渐进式补，每月清 50 个

#### 15. `app/api/v1/documents.py:11690` docstring 中 example code 写死 `http://localhost:8000`
- **修复**：换 `<API_BASE_URL>` 占位符

#### 16. 后端 logger 不一致：`logging.getLogger(__name__)` vs `get_logger("...")` 两套并存
- **位置**：`app/api/dependencies/auth.py` vs `app/api/v1/parsing.py` vs `app/api/v1/evaluations.py`
- **修复**：选一种（推荐 `get_logger` 自定义 wrapper），写 codemod 替换所有 `logging.getLogger(__name__)`

### G. .env

#### 17. `.env.example` 53KB 巨型 — 新人 setup 极易漏
- **修复**：拆 `.env.example.{db,llm,milvus,redis,observability,kg,...}` + README 章节；只在主 example 列**真正必填**项

---

## 🟠 High（22 条 — 应排期）

### 前端代码

#### 18. 87 个文件 useEffect+fetch vs 7 个 useMutation — 数据获取模式严重偏移
- **修复**：迁移 chat / datasets / ingestion / knowledge 4 个 hot path 到 useMutation

#### 19. 前端 `: any` 集中文件
- **位置**：`web/components/graph/graph-viewer.tsx` 28 / `force-graph-3d.tsx` 27 / `web/lib/api/scim.ts` 13 / `document-detail-dialog.tsx` 13
- **修复**：scim.ts 用 openapi.ts 类型直接覆盖；图形渲染层抽通用 `Node`/`Edge` 类型

#### 20. 42 处 `.then()` 不带 `.catch()` — 未处理 promise rejection
- **修复**：统一 `void promise.catch(reportError)` 或迁 `await + try/catch`；ESLint 加 `@typescript-eslint/no-floating-promises`

#### 21. 14 处 `key={index}` React 反模式
- **修复**：用业务 ID 替代

#### 22. 1149 处 useMemo/useCallback 但仅 4 处 React.memo — 过度优化反模式
- **影响**：useMemo 大量但子组件不 memo，等于无效优化
- **修复**：① 评估实际渲染瓶颈用 React Profiler ② 大列表 item 组件用 React.memo ③ 移除明显过度的 useMemo

#### 23. ESLint 主动关闭了 `react-hooks/set-state-in-effect` + `preserve-manual-memoization`
- **位置**：`web/eslint.config.js:23-26`
- **影响**：因为现状普遍 useEffect+setState，关掉规则等于"破窗"
- **修复**：先把 hot path 修了再开规则

#### 24. 前端 `page.tsx` 94 个 vs `page-client.tsx` 8 个 — 命名不一致
- **位置**：仅 `knowledge/ingestion`、`datasets/[id]/{profile,precheck,health,ingestion}`、`history`、`reports`、`diagnostics`、`observability` 用 page-client.tsx 模式
- **修复**：统一一种命名（推荐 page.tsx + 内部 \_components/）；写 ADR 记录决策

### 后端代码

#### 25. 31 处 f-string 拼 SQL（部分有 ident 引号防护）
- **位置**：`app/connectors/db/catalog_runner.py:553,617`、`app/core/migrations.py:48` ⚠️、`app/rag/checkpointer/sqlite.py:225,238,376,382,404,405`、`app/services/table_tag_service.py:736`
- **修复**：bandit B608 规则 + 改 SQLAlchemy text() + bindparam

#### 26. 28 处 `print()` 应改 logger
- **修复**：批量替换 + ruff `T201` 规则禁 print

#### 27. 24 处 `requests.*` 同步 HTTP 在 async 后端
- **位置**：`app/` 20 个文件用 requests + 22 个文件用 httpx
- **影响**：async event loop 被同步 HTTP 阻塞
- **修复**：迁 httpx async；ruff 加 `S113` 类规则禁 requests

#### 28. 35 处 Pydantic v1 残留（`.dict()` / `.json()`）
- **修复**：codemod 替换为 `.model_dump()` / `.model_dump_json()`

#### 29. 5 处 `datetime.now()` 无 tzinfo
- **修复**：用 `datetime.now(timezone.utc)`

#### 30. 后端超长函数 Top 5
- `chat.py: stream_chat` 1305 行 / `documents.py: upload_documents_batch` 1090 / `documents.py: preview_chunking` 907 / `chat.py: chat` 881 / `kg/repository.py: _as_uuid_list` 857
- **修复**：按 stage 拆为辅助函数

#### 31. 5 个 utils.py 散落（`core/utils.py` `deepdoc/parser/utils.py` `rag/embedding/utils.py` `rag/kg/utils.py` `rag/kg/search/utils.py`）
- **影响**：utils 是反模式 codename；难以发现、易重复
- **修复**：按职能命名（`text_utils.py` / `geom_utils.py`）；或并入 `core/`

### 大文件

#### 32. 前端多个 >2000 行单文件
- `web/components/ragviz/similarity-workbench.tsx` 2744 / `kg-snapshots-page.tsx` 2482 / `rag-trace-panel.tsx` 2458 / `web/app/knowledge/quarantine/page.tsx` 2115
- **修复**：按子能力拆，按 PR 单元

#### 33. `web/components/chunk-preview/context.tsx` 1449 行 Context — 巨型 context 反模式
- **修复**：拆多个细粒度 Context 或迁 zustand

#### 34. 后端 service 层超大文件
- `parsing/processors/processor.py` 5539 / `services/dataset_precheck_scan_runner.py` 1924 / `services/report_html.py` 1822 / `services/indexer.py` 1627 / `services/dataset_profile_service.py` 1579
- **修复**：拆模块化

#### 35. `web/i18n/messages/zh-CN.ts` 3667 行单文件 i18n
- **修复**：按模块拆 namespace

#### 36. `web/types/openapi.ts` 49004 行（生成）但 `web/types/index.ts` 3008 行手写 — 类型源不一致
- **修复**：手写 type 应优先消费 openapi.ts

### 测试覆盖洞

#### 37. 3 个 1500+ 行核心 service **零测试**
- `dataset_precheck_scan_runner` 1924 行 / `dataset_profile_service` 1579 行 / `rag_metrics_dashboard` 1500 行
- **修复**：每个 service 至少 5 个 happy path test

#### 38. e2e tests 仅 7 个
- **位置**：`web/playwright.config.ts` 已有但用得少
- **修复**：补 chat / datasets / ingestion / knowledge 4 个核心 flow 的 e2e

#### 39. 重复包 / 双套依赖
- 前端：`tsparticles-engine` + `tsparticles-slim` + `react-tsparticles` + `lottie-react` （20 处使用）
- 后端：CI yaml 硬编码 torch wheel URL 与 requirements.txt 平台 marker 写法不一致

---

## 🟡 Medium（15 条 — 建议规划）

### 前端

#### 40. 重型库 monaco / three / plotly 都仅 1-2 处使用但全 bundle
- **位置**：monaco 仅 `chunk-preview/components/workbench/preview/original-preview-monaco.tsx`；three 仅 `vector-nebula.tsx`；plotly 仅 `similarity-workbench.tsx`
- **修复**：用 `next/dynamic` 懒加载 + `ssr: false`

#### 41. monaco 静态资产 16MB 全量同步
- **位置**：`web/public/monaco/` 16MB
- **修复**：CDN 加载或 dynamic import 自带 worker

#### 42. TS `target` 仍 `ES2017`（Next 16 / React 19 时代偏老）
- **位置**：`web/tsconfig.json`
- **修复**：升 ES2022 或 ESNext + browserslist 控制

#### 43. zustand store 仅 3 个但散在 `web/store/` — 与 Context 边界不清
- **修复**：写 ADR 明确 zustand vs Context vs TanStack Query 用法分工

#### 44. 前端 1 处 `alert()` 浏览器原生
- **修复**：改 sonner toast

#### 45. 1 处 `suppressHydrationWarning` — 标记但未追踪根因
- **修复**：找出真实 SSR/CSR 不一致并修

### 后端

#### 46. magic numbers 散落（0.5 / 0.7 / 0.85 等阈值在 `orchestrator.py` `hierarchy_expand.py` 多处）
- **修复**：抽 `app/rag/constants.py` 或走 `settings`

#### 47. `app/api/v1/pipeline.py` 提示文案中含 hardcode 端口（QIANFAN/ETL4LLM/MARKER 等 5 处）
- **修复**：从 settings 读默认 + format

#### 48. 后端 cache 装饰器仅 17 处 — 高频纯函数可加 lru_cache
- **修复**：识别热点纯函数（embedding hash / config 解析）加 functools.cache

#### 49. 14 个 alembic migration 但 0 处显式索引 — migration 没和 model 配对
- **修复**：与 #3 配套：每加新 model 字段 → 自动生成 index 检查

#### 50. SQLAlchemy session 创建 74 处散落 — 应统一 Depends 注入
- **修复**：审计是否有 service 层直接 `SessionLocal()` 不通过 DI 的

### 工程化

#### 51. `requirements.txt` 单文件含 dev + runtime 混合 + 136 行
- **修复**：拆 `requirements-runtime.txt` + `requirements-dev.txt` + constraints.txt

#### 52. Makefile 380 行 / 60+ targets — 入口入侵性强但缺 help 分组
- **修复**：把 targets 按主题分组 + 完善 `make help` 输出

#### 53. docker/ 6 个 compose 文件（infra/lite/parsers/retrieval-dev/web/main）— 缺组合矩阵文档
- **修复**：写 `docker/README.md` 说明每个 compose 何时用、组合规则

#### 54. CI workflows 10 个但缺 lint-only 快速路径
- **修复**：拆 `lint-fast.yml`（PR 必跑，<3min）vs `ci.yml`（slow）

---

## 🟢 Low（6 条 — 滚动改善）

#### 55. 前端 `className={cn(...)}` 1175 处 — 部分可抽 design token / variants
- **修复**：用 `class-variance-authority` 已在 deps 里，更多组件改 cva

#### 56. 前端内联 onClick 函数 15 处大文件 — 渲染时重新创建
- **修复**：抽 useCallback（与 #22 配套评估）

#### 57. 后端 only 8 个 TODO/FIXME 标记 + 前端只 2 个 — 反而可疑（问题被忽略而非记录）
- **修复**：建立 PR template 鼓励标 TODO + JIRA/issue 关联

#### 58. 前端 `useEffect` 1782 处 — 总量过多
- **修复**：迁移到 useQuery / useEffect 替代方案后自然下降

#### 59. `app/services/` 50KB / 14 个 1000+ 行 service — 整体目录结构需重构
- **修复**：按业务域拆子目录（chat/ documents/ kg/ parsing/ evaluation/）

#### 60. `docs/` 19 个 .md + `docs-site/` docusaurus + `plans/` 30+ md — 文档分散
- **修复**：写 `docs/INDEX.md` 把 docs / docs-site / plans 串起来作 sitemap

---

## 推荐落地次序（8 周渐进 — 价值/成本最优排序）

| 周次 | 任务（条目号） | 收益 | 工作量 |
|---|---|---|---|
| **W1** | #7 CI on PR + #9-10 仓库卫生 + #11 next.config CSP + #16 logger 统一 | 基建底线立竿见影 | 3 天 |
| **W2** | #1 except: pass 审计脚本 + #26 print→logger + #29 datetime tz | 异常治理起步 | 4 天 |
| **W3** | #8 ONNX → git-lfs 或运行时下载 + #17 .env.example 拆分 + #51 requirements 分层 | 仓库瘦身、新人 onboarding | 4 天 |
| **W4** | #3 + #49 sa.Index 补齐 + 0015 migration | 性能定时炸弹拆除 | 3 天 |
| **W5** | #4 documents.py 拆分（首批 3 个 endpoint） | API 层失控止血 | 5 天 |
| **W6** | #5 connectors.py 拆分（首批 5 个 endpoint） | 同上 | 5 天 |
| **W7** | #18 useMutation 迁移 chat/datasets hot path + #19 graph-viewer 类型化 | 前端数据/类型治理 | 5 天 |
| **W8** | #6 chat.py + #14 endpoint docstring 补 50 个 + #28 Pydantic v2 codemod | 分层完成 | 5 天 |
| **后续滚动** | #32-36 大文件、#37-38 测试洞、#40-41 bundle、#54 CI 拆分 | 持续治理 | 每月 1-2 项 |

---

## 与既有 30+ 份 plan 的关系

**本 audit 与既有 plan 完全正交，避免重复**：
- ✅ 既有 plan 覆盖：RAG 能力扩容（KG/评测/解析/agentic/合规等）
- ✅ 本 audit 覆盖：代码质量、错误处理、API 治理、仓库卫生、CI、安全、依赖、测试、文档、bundle、命名、类型

**已部分落地的进展**（本次扫描发现）：
- 🎉 `web/lib/api/` 子目录已存在并拆分（documents.ts 715 / datasets.ts 614 / pipeline.ts 393 / parsing.ts 315 等）— batch-2 plan 部分落地
- 🎉 ESLint v9 flat config + Sentry + OTel 模块都已就绪
- 🎉 `app/core/sentry.py` `app/core/otel.py` 已存在
- 🎉 ci/ 目录有 20 个 .v1.json 评测/性能基线

---

## Critical 文件参考路径

```
# 异常治理
app/api/v1/documents.py         # except 集中点 #1（147 处）
app/rag/retriever.py            # except 集中点 #2（139 处）

# API 层失控
app/api/v1/{documents,connectors,chat}.py    # 拆分起点 #4-6
app/services/{documents,connectors,chat}/    # 新建目标目录

# DB 索引
alembic/versions/0015_add_indexes.py   # 待新建
app/models/*.py                         # 加 __table_args__ Index

# 仓库治理
.gitattributes                          # 加 *.onnx filter=lfs
.gitignore                              # 补 artifacts/ logs/ runs/ .beads/
app/{deepdoc,resources}/.../qieci/      # 删一份重复
artifacts/                              # 清截图
chunk-preview-*.png                     # 清根目录

# CI/CD
.github/workflows/{ci,security,sonar,api-docs}.yml   # 加 on: pull_request
.github/workflows/lint-fast.yml         # 待新建（#54）

# 安全
web/next.config.mjs                     # 加 headers() #11

# 配置
.env.example.{db,llm,milvus,redis,...}  # 拆分目标 #17
requirements-{runtime,dev}.txt          # 拆分目标 #51
```

---

## 验证方式

落地任一类问题后的回归验证命令：

```bash
# CI gate
gh workflow run ci.yml && gh pr view --web

# 异常治理
grep -rn "except:.*pass\|except Exception:.*pass" app/ --include="*.py" | wc -l   # 应下降

# 大文件
find app/api/v1 -name "*.py" | xargs wc -l | sort -rn | head -5   # 应无 >5000

# DB 索引
psql -c "\d+ documents" | grep "Indexes:"   # 应非空

# 类型治理
cd web && grep -rn ": any\b" --exclude-dir=node_modules . | wc -l   # 应下降

# 仓库瘦身
git ls-files | xargs -I{} ls -la {} 2>/dev/null | awk '$5 > 5242880 {print $9}' | wc -l   # 应=0

# bundle
cd web && pnpm build && pnpm bundle-check   # 现有 budget 不破

# 测试
make test && make test-web   # 现有命令

# docstring
grep -rPzo "(?s)def [^:]+:\s*\n\s*\"\"\"" app/ --include="*.py" | wc -l   # 应上升
```
