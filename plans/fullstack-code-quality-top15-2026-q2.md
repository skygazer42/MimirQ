# MimirQ 全栈健康度审查 — Top 15 必修问题清单

> **For agentic workers:** 本文档为 triage 报告，每条问题给定位 + 严重度 + 修复方向 + 工作量。需要落地时按下方"推荐落地次序"展开成独立 implementation plan（参考既有 batch-1/2/3/4 plan 风格）。

## Context

**问题与触发**
用户要求"全面看一下前后端有哪些值得修改的地方或者问题"。仓库已有 30+ 份 plan 深度调研 RAG/KG/评测/解析等**能力扩容**方向，但**代码质量、架构治理、工程化基础设施层面的问题**未系统盘点。最近 5 个 commit 全是 "调整 ui 样式"，主线开发节奏快，技术债未集中清理。

**预期产出**
Top 15 必修问题清单，每条带定位 + 严重度 + 修复方向。**不重复 30+ 份既有 plan 已覆盖的能力扩容内容**（如 KG agentic、评测扩容、Output Guard 扩容、行业规则库等）；专注本次扫描发现的代码层 / CI 层 / 仓库治理层短板。

## 当前落地状态（2026-05-11）

| 编号 | 状态 | 当前证据 |
|---|---|---|
| #1 CI PR gate | 已落地 | `ci.yml` / `security.yml` / `sonar.yml` / `api-docs.yml` 已补 `pull_request` + `push main` 触发；`make verify` 覆盖 api contract/coverage。 |
| #2 `documents.py` 拆分 | 部分落地 | MinerU batch-upload 两个 endpoint 已拆到 `app/api/v1/document_batch_upload.py`，folder tree endpoint 已拆到 `app/api/v1/document_folders.py`，document stats endpoint 已拆到 `app/api/v1/document_stats.py`；`documents.router` 通过 `router.include_router(document_batch_upload.router)`、`router.include_router(document_folders.router)` 与 `router.include_router(document_stats.router)` 保持原 `/documents/batch-upload/...`、`/documents/folders` 与 `/documents/stats` 路径不变；`tests/test_documents_router_split_source.py` 锁定源代码拆分和运行时路由暴露。剩余 list/upload/detail/chunk/lifecycle 等主路由仍需继续拆。 |
| #3 `connectors.py` 拆分 | 部分落地 | 根路径 connector catalog endpoint 已拆到 `app/api/v1/connectors_catalog.py`；connector config validation endpoint 已拆到 `app/api/v1/connectors_validation.py`，`connectors.router` 通过 `router.routes.extend(...)` 保持原 `GET /connectors` 与 `POST /connectors/validate` 路径不变；`tests/test_connectors_router_split_source.py` 锁定源代码拆分和运行时路由暴露；`web/scripts/api-contract-lib.mjs` 已支持该根路径拆分扫描。剩余 runs/configs/scheduled 等主路由仍需继续 service 化和拆分。 |
| #4 仓库卫生 | 已落地 | `.gitignore` 已纳入 `.beads/`、`.playwright-mcp/`、`runs/.deepseek_ocr/`、根部截图等生成物；相关已跟踪生成物已从索引移除。 |
| #5 `.env.example` 拆分 | 已落地 | 根 `.env.example` 已压缩为 104 行最小启动模板；高级配置拆到 `config/env/*.env.example`；`tests/test_env_example_split.py` 锁定模板大小、必需键和模块存在性。 |
| #6 TanStack Query 迁移 | 部分落地 | 共享 `useDatasets` 已从手写 `useEffect + setState` 迁移到 `useQuery` + `queryKeys.datasets.list`，`DatasetSelectField` 已复用该共享 hook，避免每个选择控件重复手写后端加载；`GroupChipsInput`、`/settings/groups` 与 `/settings/groups/[id]` 已用 `queryKeys.groups.*` + `useQuery/useMutation` 承接组列表、详情、成员列表、创建、删除、保存、添加成员与移除成员；`/settings/rbac` 已用 `queryKeys.rbac.members` + `useQuery/useMutation` 承接真实成员列表和角色保存；`/access-review` 已用 `queryKeys.accessReview.summary` + `useQuery/useMutation` 承接访问图谱摘要和导出任务；`ConversationSummaryDialog` 已用 `queryKeys.chat.summary` + `useQuery/useMutation` 承接摘要读取/更新/清空；审计日志页已用 `queryKeys.audit.logs/filterOptions` 承接列表与筛选选项加载；用量/配额页已用 `queryKeys.usage.summary/cost/quota` 和 `queryKeys.datasets.list` 承接真实后端数据加载；提示词模板页已用 `queryKeys.prompts.list` 加载并用 query invalidation 刷新；报告页已用 `queryKeys.datasets.list`、`queryKeys.reports.categories/dataset` 承接数据集、分类树与报告预览；诊断中心 `/diagnostics` 已用 `queryKeys.diagnostics.*`、`queryKeys.datasets.list`、`queryKeys.documents.list` 承接 ready/deps/online-quality、数据集和文档范围真实加载；`KgExtractPromptSettings` 已用 `queryKeys.settings.snapshot` + `useQuery/useMutation` 承接 KG 配置读取与保存；`KgPredicateOntologySettings` 已用 `queryKeys.settings.snapshot`、`queryKeys.kg.predicateOntology` + `useQuery/useMutation` 承接 KG 谓词治理读取、增删改与刷新；`DataCleaner` 已用 `queryKeys.prompts.list` + `useQuery` 承接 LLM 清洗 Prompt 模板列表；`GovernanceProfileSelector` 已用 `queryKeys.governance.profiles/profileResolved` + `useQuery` 承接治理预设列表和详情，导入后通过 query invalidation 刷新；`GovernanceProfilesPage` 已用 `queryKeys.governance.profiles` + `useQuery/useMutation` 承接治理配置列表、导入、删除和编辑器保存后的刷新；`GovernanceCommonLinesPage` 已用 `queryKeys.datasets.list`、`queryKeys.governance.profiles` + `useQuery/useQueryClient` 承接样板行发现页数据集与写入目标治理配置元数据加载和刷新；`IndustryRulesSection` 已用 `queryKeys.industryRules.rulesets` + `useQuery` 承接设置页行业规则集列表；`IndustryRulesWorkbench` 已用 `queryKeys.industryRules.rulesets`、`queryKeys.datasets.list` + `useQuery` 承接行业规则库工作台规则集与候选来源数据集元数据加载和刷新；`DatasetIngestionPolicyPage` 已用 `queryKeys.governance.profiles` + `useQuery` 承接入库策略页治理预设下拉真实后端加载；浏览器端 API base 已在 `web/lib/env.ts` 支持 `localhost` / `127.0.0.1` loopback 归一，避免本机用 `127.0.0.1:3000` 打开时真实接口因 CORS 失败；`TestCaseManager` 已用 `queryKeys.evaluations.regressionCases` + `useQuery/useMutation` 承接 Golden 回归用例列表、创建、删除、批量删除与 Golden 标记刷新；`DatasetFolderTree` 已用 `queryKeys.documents.folders` + `useQuery/refetch` 承接文档目录树加载与刷新；`AnswerLineageAction` 与 `ChunkLineageButton` 已用 `queryKeys.lineage.*` + `useQuery` 承接答案/Chunk 血缘弹窗加载；`DatasetCategoryTree` 与 `DatasetCategoryMultiSelect` 已用 `queryKeys.datasetCategories.tree` / `queryKeys.datasets.categories` + `useQuery/useMutation` 承接分类树、数据集分类绑定、创建、删除与保存；`DocumentHealthPage` 已用 `queryKeys.documents.health` + `useQuery` 承接文档健康卡真实后端加载和刷新；`RagvizSimilarityWorkbench` 已用 `queryKeys.ragviz.similarityCollections` + `useQuery` 承接检索消融相似度 collections 真实后端加载和刷新；`DatasetTablesPage` 已用 `queryKeys.datasets.detail/tables` + `useQuery` 承接数据集表格页真实数据集元数据和表格资产列表加载与刷新；`DatasetDbCatalogPage` 已用 `queryKeys.datasets.detail/dbCatalogTables` + `useQuery` 承接数据库目录页真实数据集元数据和 catalog table 列表加载与刷新；`DatasetWorkflowPage` 已用 `queryKeys.datasets.detail/config` + `useQuery` 承接数据集工作流页真实元数据与配置导出加载，导入/保存后通过 refetch 同步；`VectorNebula` 已用 `queryKeys.documents.nebula` + `useQuery` 承接真实文档列表和 chunk 列表星云数据构建并去重重复加载逻辑；`DatasetsPage` 已用 `queryKeys.datasets.list` + `useQuery/useQueryClient` 承接数据集主页真实列表加载、刷新与更新/删除后的 Query cache 同步；`query-convergence.source.test.ts`、`kg-predicate-ontology-settings.behavior.test.ts`、industry rules section 源测试、industry-rules-workbench 源测试、governance-profiles 源测试、governance-common-lines 源测试、dataset-ingestion 源测试、env 单测、test-case-manager 源测试、dataset-folder-tree 测试、lineage 源测试、dataset-category 测试、document-health 源测试、ragviz similarity 源测试、dataset tables 源测试、dataset db catalog 源测试、dataset workflow 源测试、vector nebula 源测试、datasets page 源测试与 governance 文案源测试已补回归断言。剩余 useEffect/api 热点仍需分批迁移。 |
| #7 类型逃逸预算 | 已落地（预算门禁） | `web/lib/type-safety-budget.source.test.ts` 要求 `@ts-ignore/@ts-nocheck = 0`，显式 `any <= 500`；当前 `npm --prefix web run test` 通过。 |
| #8 `chat.py` 拆分 | 部分落地 | `ConversationSummary*` schema 已下沉到 `app/api/schemas/chat.py`；conversation summary / rag-traces / checkpoint endpoints 已拆到 `app/api/v1/chat_conversation_memory.py`；conversation create/update/list/messages/export/delete endpoints 已拆到 `app/api/v1/chat_conversations.py`，标题 helper 下沉到 `app/services/chat_conversation_titles.py`，非空检索范围校验下沉到 `app/services/chat_scope.py`，`chat.py` 降至 2831 行且主路由只保留 ask/stream；共享访问校验抽到 `app/services/chat_conversation_access.py`；`tests/test_chat_router_split_source.py` 锁定路由拆分且运行时仍暴露原路径；`web/scripts/api-contract-lib.mjs` 已支持嵌套 router，`api-contract-lib.source.test.ts` 覆盖 contract 扫描。剩余流式 SSE/context/citation 主逻辑仍需继续 service 化。 |
| #9 SQL f-string 审计 | 已落地（安全约束 + 回归测试） | `app/core/migrations.py` 使用 bind 参数；`tenant_rls.py`、table-store、dataset table API 已统一 identifier/literal quoting；connector/checkpointer/table TAG 的动态 SQL 由 quote helper、整数 clamp 或 table-prefix regex 约束；`tests/test_dynamic_sql_safety_guards.py`、`tests/test_table_store_service.py` 覆盖回退风险。 |
| #10 i18n 单文件拆分 | 已落地 | `web/i18n/messages/zh-CN.ts` 已由 3667 行单文件改为 31 行聚合器；中文消息按域拆到 `web/i18n/messages/zh-CN/*.ts`；`zh-CN.split.source.test.ts` 和全量前端测试覆盖导出兼容。 |
| #11 print → logger | 已落地 | `app/` 与 `main.py` 无 `print()`；`ruff.toml` 已启用 `T201`，仅 `scripts/**` 允许 CLI 输出。 |
| #12 装饰性依赖 | 已落地 | 未使用的 `ParticleBackground` 已删除；`react-tsparticles` / `tsparticles-engine` / `tsparticles-slim` 已从 `web/package.json` 与 lockfile 移除；`lottie-react`、本地 `/lottie/*.json` 与 Lottie SW 缓存已移除，侧栏空状态改为轻量 CSS/SVG 组合。`heavy-imports.source.test.ts` 锁定回归。 |
| #15 requirements 分层 | 已落地（最小分层） | 新增 `requirements-dev.txt`，CI 改装 dev 依赖；runtime `requirements.txt` 移除 pytest/ruff/pip-audit 等开发依赖。 |

**#6 补充证据（2026-05-11）**
- `DatasetIngestionPolicyPage` 已用 `queryKeys.governance.profiles`、`queryKeys.datasets.detail`、`queryKeys.datasets.ingestionPolicy`、`queryKeys.datasets.ingestionStats` + `useQuery` 承接入库策略页治理预设、数据集元数据、入库策略与入库统计真实后端加载，保存/导入/回滚后通过 refetch 同步。
- `app/datasets/[id]/ingestion/page.source.test.ts` 已锁定该页不再用手写 `load()` 管理初始 dataset / policy / stats 加载。
- `DatasetPrecheckPage` 已用 `queryKeys.datasets.detail`、`queryKeys.datasets.precheckRuns` + `useQuery` 承接预检页数据集元数据与扫描 run 列表真实后端加载，扫描完成/SSE 回调/刷新后通过 refetch 同步。
- `app/datasets/[id]/precheck/page-client.source.test.ts` 已锁定该页不再用手写 `load()` / `loadRuns()` 管理初始 dataset / run list 加载。
- `EvidenceWorkbench` 已用 `queryKeys.datasets.list` + `useQuery` 承接证据检索工作台数据集下拉真实后端加载。
- `components/ragviz/evidence-workbench.source.test.ts` 已锁定该组件不再用手写 `loadDatasets()` 管理数据集下拉加载。
- `GraphScopePickerDialog` 已用 `queryKeys.datasets.list` + `useQuery` 承接图谱范围选择弹窗的数据集下拉真实后端加载，仅在弹窗打开时启用请求。
- `app/graph/_components/graph-scope-picker-dialog.source.test.ts` 已锁定该组件不再用手写 `loadDatasets()` 管理数据集下拉加载。
- `chat/stream` 的 CORS expose headers 已固定包含 `X-Conversation-ID` 与 `X-Assistant-Message-ID`，即使本地 `.env` 覆盖 `CORS_EXPOSE_HEADERS` 也会保留真实会话头；`tests/test_cors_expose_headers.py` 锁定默认配置和环境覆盖场景。
- 真实浏览器从 `http://127.0.0.1:3000` 发起 `fetch('/api/v1/chat/stream')` 时已能读取 `x-conversation-id=35fac0b6-de0e-4adf-8f4c-aab4e180c702` 与 `x-assistant-message-id=3a57cc55-d4fa-4bbb-9f8a-62e027048f77`，避免真实 chat 页面只能等超长 SSE `done` 后才更新会话 URL。
- `PLAYWRIGHT_LIVE_STACK=1 PLAYWRIGHT_PORT=3000 PLAYWRIGHT_LIVE_API_URL=http://127.0.0.1:8000 pnpm --dir web exec playwright test web/e2e/live-stack.smoke.spec.ts --project=chromium` 已通过，覆盖真实上传、解析、viewer、chat stream 与 command-menu handoff；用例超时调整为 420s 以匹配真实解析/回答链路。
- `CommandMenu` typed search 已从 `useEffect + Promise.allSettled + result/loading state` 迁移为 220ms debounce 后的 `useQuery`，分别使用 `queryKeys.documents.list`、`queryKeys.datasets.list` 与 `queryKeys.chat.conversations` 承接文档、数据集、会话真实加载；普通自然语言输入时隐藏基础导航组，确保 Enter 默认触发 AI handoff。
- `components/command-menu.source.test.ts` 已锁定 command menu Query 迁移，不再允许 `requestSeqRef` / `Promise.allSettled` / 手写 result state 回退；`PLAYWRIGHT_PORT=3000 pnpm --dir web exec playwright test web/e2e/command-menu-document-view.spec.ts --project=chromium` 已通过，覆盖自然语言 handoff 与文档 viewer 恢复。
- `ChatArea` 的系统 RAG 默认值、数据集列表/欢迎统计、文档计数与 Prompt 模板列表已从 mount-time `useEffect` 请求迁移到 `useQuery`，分别使用 `queryKeys.settings.snapshot`、`queryKeys.datasets.list`、`queryKeys.documents.list` 与 `queryKeys.prompts.list`；仅保留 `selectedDatasetId` 等真实交互状态在组件内。
- `components/chat-area.autorun.source.test.ts` 已锁定 ChatArea Query 迁移，不再允许 `loadWelcomeStats` / `loadTemplates` / `setDatasets` / `setPromptTemplates` 回退；`PLAYWRIGHT_PORT=3000 pnpm --dir web exec playwright test web/e2e/document-chat.smoke.spec.ts --project=chromium` 已通过，覆盖上传、解析、进入聊天并发送请求。

**审查方法**
3 个维度并行扫描：(A) 代码质量与缺陷 (B) 架构与可维护性 (C) 安全/性能/稳定性 (D) 工程化基础设施。源数据：`wc -l`、`grep` 关键反模式、`git ls-files`、`.github/workflows/` 与 `package.json` / `requirements.txt`。

---

## Tech Stack 概览（实测）

| 维度 | 现状 |
|---|---|
| 前端 | Next.js 16.2 / React 19.2 / TS strict / pnpm 10.26 / TanStack Query 5.96 / Sentry 10.47 |
| 后端 | Python 3.11 / FastAPI / SQLAlchemy 2.0 / Milvus / Postgres / Redis |
| 测试 | 前端 vitest 530 文件 + playwright；后端 pytest 1121 文件（py 文件总数 967，比例不错） |
| CI | 10 个 workflow（ci/security/sonar/perf-nightly/rag-quality-gate/api-docs/handbook-matrix/parsing-proof-{nightly,sample}/docs-site） |

---

## Top 15 必修问题清单

### 🔴 Critical（影响交付质量，必修）

#### 1. CI 主流水线仅手动触发，PR 无自动 gate
- **位置**：`.github/workflows/ci.yml` 第 3-4 行 `on: workflow_dispatch`
- **影响**：所有 PR 合并前**不强制跑** lint/typecheck/test，靠人工 dispatch；security.yml 同样仅 weekly schedule + workflow_dispatch
- **证据**：`grep -A2 "^on:" .github/workflows/ci.yml` → 只有 `workflow_dispatch`
- **修复方向**：补 `on: pull_request` + `on: push: branches: [main]`，并把 ci/security/sonar/api-docs 都补上 PR 触发；perf/parsing-proof/handbook-matrix 这种重的可保留 nightly
- **工作量**：0.5 天（改 yml + 跑通一次验证）
- **与既有 plan 关系**：无，纯本次发现

#### 2. `app/api/v1/documents.py` 11770 行 / 55 endpoints — API 层失控
- **位置**：`app/api/v1/documents.py`（最大后端单文件）
- **影响**：业务逻辑塞 router、PR review 不可能完整、merge 冲突高发、grep 找 endpoint 慢
- **证据**：`wc -l` = 11770；`grep -c "@router\."` = 55，平均 214 行/endpoint（业务逻辑没下沉到 service 层）
- **修复方向**：按资源拆分 `documents/` 子目录（list/upload/parse/chunk/embed/version/acl/...）；将业务逻辑下沉到 `app/services/documents/*`；router 文件控制在 ≤500 行
- **工作量**：3-5 天（拆分 + 测试回归）
- **与既有 plan 关系**：与 `batch-2-architecture.md`（前端 api-client.ts 拆分）思路对偶，可作 batch-2 后端篇

#### 3. `app/api/v1/connectors.py` 10697 行 / 15 endpoints — 业务逻辑全塞 router
- **位置**：`app/api/v1/connectors.py`
- **影响**：平均 713 行/endpoint，单个 endpoint 函数体可达数百行；catalog 同步、表结构推断、采样等核心逻辑应在 service
- **证据**：`wc -l` = 10697；15 endpoints
- **修复方向**：service 层化（`app/services/connectors/{catalog,sample,schema_infer}/...`），router 仅做参数校验 + 调用
- **工作量**：3-4 天
- **与既有 plan 关系**：无，纯本次发现

#### 4. 仓库根目录散落 10+ 张 PNG / log / db 大文件
- **位置**：`/data/temp34/MimirQ/` 根直接列出 `chunk-preview-{1536-v2,after,after-2,aligned,current,final}.png`、`graph-snapshots-{audit,before,after}.png`、`.beads/{daemon.log,beads.db,issues.jsonl}`、`runs/deepseek_ocr_smoke.pdf`、`logs/{web,backend}.local-20260506.log`、`.playwright-mcp/*.png`
- **影响**：仓库膨胀（>2MB 装饰性内容）、`git status` 噪音、日志/db 应在 .gitignore；`graph-snapshots-*.png` 看似 PR 截图未清理
- **证据**：`find -maxdepth 2 -size +100k -type f`
- **修复方向**：① 把 chunk-preview-*.png/graph-snapshots-*.png 移到 `docs/screenshots/` 或删除 ② `.beads/`、`logs/`、`runs/`、`.playwright-mcp/` 加 .gitignore ③ 检查 git 历史是否已混入大文件（若已 push 过则只能 BFG/filter-repo 清理）
- **工作量**：0.5 天
- **与既有 plan 关系**：无

#### 5. `.env.example` 53KB 巨型 + `.env` 25KB（已 gitignored 但本地存在风险）
- **位置**：`/data/temp34/MimirQ/.env.example`（53392 字节）、`/data/temp34/MimirQ/.env`
- **影响**：53KB 的 example 意味着配置项极多，新人 setup 极易漏；同时配置散落风险高
- **证据**：`ls -la .env.example` 53392 字节；`app/core/config.py` 2885 行（800+ 配置项已知）
- **修复方向**：① 把 .env.example 按模块拆 `.env.example.{db,llm,milvus,redis,observability,kg}` 并合 README 章节 ② 核对 config.py 中**真正必填**的项（启动会 fail 的）vs **可选**项，只在 example 列必填
- **工作量**：1 天
- **与既有 plan 关系**：与 batch 系列正交

---

### 🟠 High（影响开发效率/可维护性，应排期）

#### 6. 前端数据获取严重偏移 — 87 useEffect+fetch vs 7 useMutation
- **位置**：全 `web/` 目录（87 个文件用 useEffect 调 fetch/api 手动加载）
- **影响**：缺统一缓存/重试/loading 状态、多页面并发请求重复、刷新无 stale-while-revalidate；与 layout 已注入的 QueryProvider 配套不匹配
- **证据**：`grep -rln "useEffect" web/ | xargs grep -l "fetch\|api"` = 87；`grep "useMutation"` 总计 7 处
- **修复方向**：分批迁移高频页面到 useQuery + useMutation，先做 chat/datasets/ingestion 三个 hot path
- **工作量**：5-8 天（分阶段）
- **与既有 plan 关系**：MEMORY.md 中提到此模式问题，但**无独立落地 plan**；建议作 `frontend-tanstack-query-migration` 独立 plan

#### 7. 前端类型逃逸 — 200 个 @ts-ignore + 772 个 `: any`
- **位置**：分散全 `web/`
- **影响**：strict: true 形同虚设；OpenAPI 生成的 types/openapi.ts 49004 行未充分被使用；refactor 时类型保护失效
- **证据**：`grep -rn "@ts-ignore\|@ts-nocheck"` = 200；`grep -rn ": any\b\|<any>"` = 772
- **修复方向**：① ESLint 加 `@typescript-eslint/no-explicit-any: warn` + `ban-ts-comment: error` ② 设阈值（如 any < 500 / @ts-ignore < 100）作 CI gate ③ 优先把 api-client 周边的 any 替换为 openapi.ts 类型
- **工作量**：3-5 天（清理）+ 1 天（gate 接入）
- **与既有 plan 关系**：与 `batch-3-code-quality.md` 思路一致

#### 8. `app/api/v1/chat.py` 3653 行 / 15 endpoints — 流式逻辑混在 router
- **位置**：`app/api/v1/chat.py`
- **影响**：流式 SSE 处理、context 组装、citation 拼接全混在 endpoint 里
- **证据**：`wc -l` = 3653；15 endpoints
- **当前进展（2026-05-11）**：已先拆出 summary / rag-traces / checkpoint conversation memory router，`chat.py` 降至 3368 行；API contract 已支持嵌套路由扫描并通过。流式主 endpoint 仍未 service 化，不能视为完成。
- **修复方向**：抽 `app/services/chat/{stream_orchestrator, citation_builder, ...}`；router 仅保留 schema/路由层
- **工作量**：2-3 天
- **与既有 plan 关系**：无

#### 9. f-string 拼 SQL 31 处 — 部分有引号防护但需逐一审计
- **位置**：`app/connectors/db/catalog_runner.py:553,617`、`app/core/migrations.py:48`、`app/rag/checkpointer/sqlite.py:225,238,376,382,404,405`、`app/services/table_tag_service.py:736`
- **影响**：`migrations.py:48` 把 `default_tenant` 直接拼进 `WHERE tenant_id IS NULL UPDATE ... = '{default_tenant}'::uuid` 字符串，即使内部源也是不良习惯
- **证据**：`grep -n "f\".*\(SELECT\|INSERT...\)"` 命中 31 处
- **修复方向**：① catalog_runner 的表名/列名通过 `_quote_mysql_ident` 处理可保留但加注释说明 ② migrations / table_tag_service 改 SQLAlchemy text() + bindparam ③ 在 `pyproject.toml` 加 `bandit` 规则 B608 自动扫
- **工作量**：1-2 天
- **与既有 plan 关系**：无

#### 10. `web/i18n/messages/zh-CN.ts` 3667 行单文件 — i18n 维护噩梦
- **位置**：`web/i18n/messages/zh-CN.ts`
- **影响**：所有中文文案集中一文件，按模块查找/合并冲突高发；新增页面要去这里加键
- **证据**：`wc -l` = 3667
- **修复方向**：按模块拆 `messages/zh-CN/{chat,datasets,knowledge,graph,evaluations,...}.ts` + 入口聚合；next-intl 4.9 支持 namespace 加载
- **工作量**：1-2 天
- **与既有 plan 关系**：无

#### 11. 后端 28 处 `print()` — 应统一走 logger
- **位置**：分散 `app/`（28 处）
- **影响**：print 不进结构化日志、production 看不到、无 level 过滤
- **证据**：`grep -rn "^\s*print(" app/` = 28
- **修复方向**：批量替换 `print(...)` → `logger.info/debug(...)`；在 ruff 配置加 `T201` 规则禁 print（除明确 cli 脚本）
- **工作量**：0.5 天
- **与既有 plan 关系**：无

#### 12. 装饰性依赖冗余 — tsparticles 双套 + react-tsparticles + lottie-react
- **位置**：`web/package.json` 同时声明 `tsparticles-engine` `tsparticles-slim` `react-tsparticles` `lottie-react`
- **影响**：bundle 体积；20 处使用，可能可砍/合并到一种动效库
- **证据**：`package.json` 显式列三套 tsparticles + lottie；`grep` 确认实际用量 20 处
- **修复方向**：① 评估 tsparticles 是否必要（若仅几处装饰可改 framer-motion / CSS 实现）② lottie 动画可换 SVG/CSS ③ pnpm 不会自动 dedupe 这种独立包名
- **工作量**：1 天评估 + 0.5-2 天迁移
- **与既有 plan 关系**：无

---

### 🟡 Medium（建议规划但非紧急）

#### 13. 前端多个 >1500 行单文件待拆（除已知 ingestion/page-client）
- **位置**（按行数）：
  - `web/components/ragviz/similarity-workbench.tsx` 2744
  - `web/components/graph/kg-snapshots-page.tsx` 2482
  - `web/components/rag-trace/rag-trace-panel.tsx` 2458
  - `web/app/knowledge/quarantine/page.tsx` 2115（**已在 batch 计划提及**）
  - `web/components/chunk-preview/components/workbench/sidebar-client.tsx` 1903
  - `web/components/data-governance-panel.tsx` 1878
  - `web/app/datasets/[id]/profile/page-client.tsx` 1767
  - `web/components/chunk-preview/components/workbench/preview/chunk-list.tsx` 1692
  - `web/components/datasets/datasets-page.tsx` 1633
  - `web/components/graph/kg-diagnostics-page.tsx` 1581
- **影响**：组件层次混乱、props drilling、render 性能未优化
- **修复方向**：按子能力拆为 `<Workbench>{<Sidebar/><Main/><Detail/>}</Workbench>` 风格；避免一次性大重构，按 PR 单元拆
- **工作量**：每个文件 0.5-2 天
- **与既有 plan 关系**：MEMORY 中前端 6 份 P0 plan 部分已点名（quarantine/ingestion），其余可补做

#### 14. 后端 service 层超大文件
- **位置**：
  - `app/parsing/processors/processor.py` 5539
  - `app/services/dataset_precheck_scan_runner.py` 1924
  - `app/services/report_html.py` 1822
  - `app/rag/evaluation/ragas.py` 1897
  - `app/services/indexer.py` 1627
  - `app/services/dataset_profile_service.py` 1579
- **影响**：单文件多 god class、循环嵌套深、单测困难
- **修复方向**：① `processor.py` 按 stage 拆（pre/parse/post）② `report_html.py` 模板与数据组装分离 ③ ragas.py 与 evaluation/runners/ 重组
- **工作量**：每个文件 1-3 天
- **与既有 plan 关系**：parsing 已有 deep dive，但**未涉及代码拆分**

#### 15. `requirements.txt` 单文件 + python deps 无分层
- **位置**：`/data/temp34/MimirQ/requirements.txt` 单文件（无 `requirements-dev.txt` / `requirements-test.txt`），无 `pyproject.toml` 完整声明（仅顶部少量内容）
- **影响**：dev/prod/test 依赖混在一起；torch CPU wheel 写死在 CI yaml 而非 requirements；安装慢、镜像大
- **证据**：`ls requirements*.txt` 仅 1 个；CI 中 torch URL 硬编码
- **修复方向**：① 拆 `requirements.txt`（runtime） + `requirements-dev.txt`（pytest/ruff/black/mypy）② torch wheel URL 移到 `requirements-runtime.txt` 或 constraints.txt ③ 评估迁移到 `pyproject.toml` + uv/poetry
- **工作量**：1 天
- **与既有 plan 关系**：无

---

## 推荐落地次序（4 周渐进）

| 周次 | 任务 | 收益 |
|---|---|---|
| **Week 1** | #1 CI on PR + #4 仓库卫生 + #5 .env.example 拆分 + #11 print→logger + #15 requirements 分层 | 基建立竿见影、PR review 体验改善 |
| **Week 2** | #7 ts-any/ignore 接入 lint gate + #10 i18n 拆分 + #12 装饰性依赖评估 | 前端代码质量底线、bundle 优化 |
| **Week 3** | #2 documents.py 拆分 + #9 SQL bandit 审计 | 后端 API 层失控止血 |
| **Week 4** | #3 connectors.py 拆分 + #6 useMutation 迁移 chat hot path | 后端业务下沉 + 前端数据获取统一 |
| **后续** | #8 chat.py、#13 前端大组件、#14 后端 god service —— 滚动排期，每月 1-2 个 | 持续治理 |

---

## 不在本清单的（避免与既有 plan 重复）

以下方向 **MEMORY 已有 plan 深度调研**，本审查**不重复**：
- RAG 能力扩容（CRAG streaming / web search / Self-RAG / A-RAG hierarchical tools / Adaptive-RAG router）
- Output Guard 扩容 + Llama Guard 3 + Presidio
- KG agentic search（ToG / PoG / Plan-on-Graph）/ KG snapshot 影响分析
- 评测集 4 阶段 + Citation/Atomic Fact / 内部 GraphRAG-Bench / OmniDocBench
- 行业规则库产品化、合规自动化、DeepDoc API 化、视频 RAG、边缘部署
- 前端 6 份 P0 plan（parsing/chunk-preview/ingestion/precheck/feedback/quarantine 子组件细化）
- batch-1/2/3/4 优化（api-client.ts 拆 lib/api/、types/index.ts 拆分等）

---

## 验证方式

落地任一问题后的回归验证：
- **CI**：`gh workflow run ci.yml` 然后看 PR 触发是否生效
- **lint/type**：`cd web && pnpm lint && pnpm typecheck` 计数 any/ts-ignore 是否下降
- **测试**：`make test && make test-web`（既有命令）
- **bundle**：`cd web && pnpm bundle-check`（已有 budget 检查脚本）
- **后端拆分**：`pytest app/tests/api/test_documents.py -v` 确认行为不变
- **仓库卫生**：`git ls-files | xargs du -sh | sort -h | tail -20` 看大文件是否清理

## Critical 文件参考路径

```
.github/workflows/ci.yml               # #1 改 on:
app/api/v1/documents.py                # #2 拆分起点
app/api/v1/connectors.py               # #3 拆分起点
app/api/v1/chat.py                     # #8 拆分起点
app/core/migrations.py:48              # #9 SQL 修复点 1
app/connectors/db/catalog_runner.py    # #9 SQL 审计点 2
web/lib/api-client.ts                  # #6 + #7 切入起点（已存在 batch plan）
web/i18n/messages/zh-CN.ts             # #10 拆分起点
web/package.json                       # #12 依赖梳理
.gitignore                             # #4 补 .beads/ logs/ runs/ .playwright-mcp/
.env.example                           # #5 拆分起点
requirements.txt                       # #15 拆分起点
```
