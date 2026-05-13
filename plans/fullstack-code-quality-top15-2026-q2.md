# MimirQ 全栈健康度审查 — Top 15 必修问题清单

> **For agentic workers:** 本文档为 triage 报告，每条问题给定位 + 严重度 + 修复方向 + 工作量。需要落地时按下方"推荐落地次序"展开成独立 implementation plan（参考既有 batch-1/2/3/4 plan 风格）。

## Context

**问题与触发**
用户要求"全面看一下前后端有哪些值得修改的地方或者问题"。仓库已有 30+ 份 plan 深度调研 RAG/KG/评测/解析等**能力扩容**方向，但**代码质量、架构治理、工程化基础设施层面的问题**未系统盘点。最近 5 个 commit 全是 "调整 ui 样式"，主线开发节奏快，技术债未集中清理。

**预期产出**
Top 15 必修问题清单，每条带定位 + 严重度 + 修复方向。**不重复 30+ 份既有 plan 已覆盖的能力扩容内容**（如 KG agentic、评测扩容、Output Guard 扩容、行业规则库等）；专注本次扫描发现的代码层 / CI 层 / 仓库治理层短板。

## 当前落地状态（2026-05-12）

| 编号 | 状态 | 当前证据 |
|---|---|---|
| #1 CI PR gate | 已落地 | `ci.yml` / `security.yml` / `sonar.yml` / `api-docs.yml` 已补 `pull_request` + `push main` 触发；`make verify` 覆盖 api contract/coverage。 |
| #2 `documents.py` 拆分 | 部分落地 | MinerU batch-upload 两个 endpoint 已拆到 `app/api/v1/document_batch_upload.py`，folder tree endpoint 已拆到 `app/api/v1/document_folders.py`，document stats endpoint 已拆到 `app/api/v1/document_stats.py`，duplicates endpoint 已拆到 `app/api/v1/document_duplicates.py`，versions/diff/activate/delete 端点已拆到 `app/api/v1/document_versions.py`，document access 端点已拆到 `app/api/v1/document_access.py`，lifecycle metadata 端点已拆到 `app/api/v1/document_lifecycle.py`，timeline 端点已拆到 `app/api/v1/document_timeline.py`，parsed-content / clean-docx 端点已拆到 `app/api/v1/document_content.py`，document detail 端点已拆到 `app/api/v1/document_detail.py`，document health 端点已拆到 `app/api/v1/document_health.py`，chunk read-only 端点已拆到 `app/api/v1/document_chunks_read.py`，chunk write 端点已拆到 `app/api/v1/document_chunks_write.py`，QA generate / pipeline patch / user metadata patch 端点已拆到 `app/api/v1/document_mutations.py`，document status / cancel / retry / delete 端点已拆到 `app/api/v1/document_processing.py`，batch metadata / retry / reingest / access / move 端点已拆到 `app/api/v1/document_batches.py`，batch disable / enable / archive / unarchive / batch-delete 端点已拆到 `app/api/v1/document_batches_lifecycle.py`，文档列表读接口已拆到 `app/api/v1/document_listing.py`，document download / image / image-url 资产端点已拆到 `app/api/v1/document_assets.py`，manual chunk 文档创建端点已拆到 `app/api/v1/document_manual.py`，文档预解析预览端点已拆到 `app/api/v1/document_preview.py`，upload / upload-url / upload-batch route logic 已抽到 `app/api/v1/document_upload.py`，chunk-preview / chunk-preview-by-sha route logic 已抽到 `app/api/v1/document_chunk_preview.py`，preview/chunk-preview 共用 helper 已抽到 `app/services/document_preview_utils.py`；`documents.router` 通过 `router.include_router(...)` 保持原 `/documents/**` 路径不变；`tests/test_documents_router_split_source.py`、`tests/test_documents_upload_url_endpoint.py`、`tests/test_documents_chunk_preview_response_fields.py`、`tests/test_chunk_preview_stats_histogram.py` 与 `tests/test_chunk_preview_positions_contract.py` 锁定源代码拆分、运行时路由暴露和 chunk-preview / upload-url 行为。当前 `documents.py` 已降到约 `2235` 行、`0` 个主路由，本轮 router 级拆分已收口到兼容层。 |
| #3 `connectors.py` 拆分 | 部分落地 | 根路径 connector catalog endpoint 已拆到 `app/api/v1/connectors_catalog.py`；connector config validation endpoint 已拆到 `app/api/v1/connectors_validation.py`；connector run create/list/detail/retry/resume/cancel 端点已拆到 `app/api/v1/connectors_runs.py`；connector config list/create/update/delete/run/reconcile 端点已拆到 `app/api/v1/connectors_configs.py`；scheduled tick 端点已拆到 `app/api/v1/connectors_schedules.py`；connector 通用错误分类 / stats 聚合 helper cluster 已拆到 `app/api/v1/connectors_common.py`；Drive / GitHub 外部源 URL / auth / ACL helper cluster 已拆到 `app/api/v1/connectors_external.py`，并继续承接 `http/https` 与 link href 校验；connector ACL summary / run-config out / schedule / config-sync helper cluster 已拆到 `app/api/v1/connectors_state.py`；通用文档 ACL 应用 / source_url-source_ref soft-disable / Jira issue-attachment-linked-artifact ACL reconcile helper cluster 已拆到 `app/api/v1/connectors_acl.py`；connector identity metadata / db row sidecar helper cluster 已拆到 `app/api/v1/connectors_artifacts.py`；DB catalog 执行簇已拆到 `app/api/v1/connectors_db_catalog.py`；URL batch 执行簇已拆到 `app/api/v1/connectors_url_batch.py`；GitHub planning/helper 已拆到 `app/api/v1/connectors_github_plan.py`，GitHub repo runtime cluster 已拆到 `app/api/v1/connectors_github_repo.py`，Drive files runtime cluster 已拆到 `app/api/v1/connectors_drive_files.py`，MinIO bucket runtime cluster 已拆到 `app/api/v1/connectors_minio_bucket.py`；Confluence 专属 helper/runtime cluster 已整体落到 `app/api/v1/connectors_confluence.py`；Jira 的 pure helper/render/settings、orchestration shell、resolve/progress/finalize、issue-processing，以及 attachments / linked-artifacts / run-stats 子簇已拆到 `app/api/v1/connectors_jira.py`；Web crawl runtime cluster 已拆到 `app/api/v1/connectors_web_crawl.py`，并复用 `app/api/v1/connectors_web_crawl_plan.py` 中的 plan/manifest helper；`connectors.router` 通过 `router.routes.extend(...)` 保持原 `GET /connectors`、`POST /connectors/validate`、`/connectors/runs*`、`/connectors/configs*` 与 `/connectors/scheduled/tick` 路径不变；`tests/test_connectors_router_split_source.py` 锁定源代码拆分和运行时路由暴露；`web/scripts/api-contract-lib.mjs` 已支持该根路径拆分扫描。当前 `connectors.py` 已降到 `523` 行、拆出 `20` 个 `connectors_*.py` 子文件/模块。剩余工作主要是继续把共享执行/helper 逻辑 service 化，而不是继续在 router 里堆 endpoint。 |
| #4 仓库卫生 | 已落地（当前工作区） | `.gitignore` 已纳入 `.beads/`、`.playwright-mcp/`、`runs/.deepseek_ocr/`、根部截图等生成物；仓库根 `*.png` 已清零，且 `git rm --cached web/.playwright-mcp/*.png` 后当前已无被 git 跟踪的 Playwright 生成图。 |
| #5 `.env.example` 拆分 | 已落地 | 根 `.env.example` 已压缩为 104 行最小启动模板；高级配置拆到 `config/env/*.env.example`；`tests/test_env_example_split.py` 锁定模板大小、必需键和模块存在性。 |
| #6 TanStack Query 迁移 | 部分落地 | 截至 `2026-05-12`，前端实测 `useMutation = 50`、`useQuery = 244`，明显高于上一版记录。共享 `useDatasets` 已从手写 `useEffect + setState` 迁移到 `useQuery` + `queryKeys.datasets.list`，`DatasetSelectField` 已复用该共享 hook，避免每个选择控件重复手写后端加载；`GroupChipsInput`、`/settings/groups` 与 `/settings/groups/[id]` 已用 `queryKeys.groups.*` + `useQuery/useMutation` 承接组列表、详情、成员列表、创建、删除、保存、添加成员与移除成员；`/settings/rbac` 已用 `queryKeys.rbac.members` + `useQuery/useMutation` 承接真实成员列表和角色保存；`/access-review` 已用 `queryKeys.accessReview.summary` + `useQuery/useMutation` 承接访问图谱摘要和导出任务；`ConversationSummaryDialog` 已用 `queryKeys.chat.summary` + `useQuery/useMutation` 承接摘要读取/更新/清空；审计日志页已用 `queryKeys.audit.logs/filterOptions` 承接列表与筛选选项加载；用量/配额页已用 `queryKeys.usage.summary/cost/quota` 和 `queryKeys.datasets.list` 承接真实后端数据加载；提示词模板页已用 `queryKeys.prompts.list` 加载并用 query invalidation 刷新；报告页已用 `queryKeys.datasets.list`、`queryKeys.reports.categories/dataset` 承接数据集、分类树与报告预览；诊断中心 `/diagnostics` 已用 `queryKeys.diagnostics.*`、`queryKeys.datasets.list`、`queryKeys.documents.list` 承接 ready/deps/online-quality、数据集和文档范围真实加载；`KgExtractPromptSettings` 已用 `queryKeys.settings.snapshot` + `useQuery/useMutation` 承接 KG 配置读取与保存；`KnowledgeSettingsPanel` 已用 `queryKeys.settings.snapshot` + `useQuery` 承接知识工作台设置面板的系统配置读取；`feedback` 页的归档/取消归档按钮已改成真实 `PATCH /api/v1/feedback/messages/{feedback_id}` round-trip，不再依赖本地 `archivedIds` 假状态；`/evaluations` 已用 `queryKeys.chat.conversations`、`queryKeys.evaluations.ragasRuns` 与 `queryKeys.evaluations.ragasRunDetail` + `useQuery` 承接会话列表、run 列表和 run detail 轮询，不再依赖 `loadConversations()/loadRuns()/Promise.all(...)` 手写 loader；`/history` 已用 `queryKeys.chat.conversations` + `useQuery` 承接会话列表、用 `useInfiniteQuery + queryKeys.chat.messages` 承接消息列表和“加载更多”，且已移除纯前端 `starredConversationIds` / `收藏对话` 假交互，不再在正式页暴露未接后端的收藏按钮；`/datasets/[id]/profile` 已用 `queryKeys.datasets.detail/profileSummary/profileScanRuns` + `useQuery` 承接数据集详情、profile summary 与 scan runs 的首屏 bootstrap，不再依赖初始 `load()` 的 `Promise.all(...)` 手写链；`TestGenerationDialog` 已用 `queryKeys.documents.list`、`queryKeys.datasets.list` 与 `queryKeys.chat.conversations` + `useQuery` 承接文档源、数据集源与对话源列表，不再依赖 `loadData()` 的手写并发拉取；`IndustryRulesWorkbench` 已用 `queryKeys.industryRules.ruleset` 与 `queryKeys.industryRules.glossarySuggestions` + `useQuery` 承接规则详情与规则候选读取，不再依赖 `loadRulesetDetail()` / `loadGlossarySuggestions()` 手写读侧；`DatasetKGWorkbenchPage` 已用 `queryKeys.datasets.detail` 与 `queryKeys.documents.list` + `useQuery` 承接数据集详情与 Scope docs 列表，不再依赖 `loadDocs()` 的手写首屏加载；`QuerysetHealthTabClient` 已用 `queryKeys.evaluations.querysetHealthRuns` 与 `queryKeys.evaluations.querysetHealthDiff` + `useQuery` 承接健康度 runs 历史与 diff 读取，不再依赖 `loadRuns()` / `loadDiff()` 手写读侧；`RetrievalAblationsPage` 已用 `queryKeys.datasets.list` 与 `queryKeys.evaluations.list` + `useQuery` 承接数据集列表和 regression runs 列表，不再依赖 `loadDatasets()` / `refreshRuns()` 的手写首屏加载；`RagTracePanel` 已用 `queryKeys.chat.ragTraces` + `useQuery` 承接 trace 历史列表读取，不再依赖 `load()` 里直接调用 `chatApi.getRagTraces()` 的手写首屏读侧；`KgPredicateOntologySettings` 已用 `queryKeys.settings.snapshot`、`queryKeys.kg.predicateOntology` + `useQuery/useMutation` 承接 KG 谓词治理读取、增删改与刷新；`DataCleaner` 已用 `queryKeys.prompts.list` + `useQuery` 承接 LLM 清洗 Prompt 模板列表；`GovernanceProfileSelector` 已用 `queryKeys.governance.profiles/profileResolved` + `useQuery` 承接治理预设列表和详情，导入后通过 query invalidation 刷新；`GovernanceProfilesPage` 已用 `queryKeys.governance.profiles` + `useQuery/useMutation` 承接治理配置列表、导入、删除和编辑器保存后的刷新；`GovernanceCommonLinesPage` 已用 `queryKeys.datasets.list`、`queryKeys.governance.profiles` + `useQuery/useQueryClient` 承接样板行发现页数据集与写入目标治理配置元数据加载和刷新；`IndustryRulesSection` 已用 `queryKeys.industryRules.rulesets` + `useQuery` 承接设置页行业规则集列表；`DatasetIngestionPolicyPage` 已用 `queryKeys.governance.profiles` + `useQuery` 承接入库策略页治理预设下拉真实后端加载；浏览器端 API base 已在 `web/lib/env.ts` 支持 `localhost` / `127.0.0.1` loopback 归一，避免本机用 `127.0.0.1:3000` 打开时真实接口因 CORS 失败；`TestCaseManager` 已用 `queryKeys.evaluations.regressionCases` + `useQuery/useMutation` 承接 Golden 回归用例列表、创建、删除、批量删除与 Golden 标记刷新；`DatasetFolderTree` 已用 `queryKeys.documents.folders` + `useQuery/refetch` 承接文档目录树加载与刷新；`AnswerLineageAction` 与 `ChunkLineageButton` 已用 `queryKeys.lineage.*` + `useQuery` 承接答案/Chunk 血缘弹窗加载；`DatasetCategoryTree` 与 `DatasetCategoryMultiSelect` 已用 `queryKeys.datasetCategories.tree` / `queryKeys.datasets.categories` + `useQuery/useMutation` 承接分类树、数据集分类绑定、创建、删除与保存；`DocumentHealthPage` 已用 `queryKeys.documents.health` + `useQuery` 承接文档健康卡真实后端加载和刷新；`RagvizSimilarityWorkbench` 已用 `queryKeys.ragviz.similarityCollections` + `useQuery` 承接检索消融相似度 collections 真实后端加载和刷新；`DatasetTablesPage` 已用 `queryKeys.datasets.detail/tables` + `useQuery` 承接数据集表格页真实数据集元数据和表格资产列表加载与刷新；`DatasetDbCatalogPage` 已用 `queryKeys.datasets.detail/dbCatalogTables` + `useQuery` 承接数据库目录页真实数据集元数据和 catalog table 列表加载与刷新；`DatasetWorkflowPage` 已用 `queryKeys.datasets.detail/config` + `useQuery` 承接数据集工作流页真实元数据与配置导出加载，导入/保存后通过 refetch 同步；`VectorNebula` 已用 `queryKeys.documents.nebula` + `useQuery` 承接真实文档列表和 chunk 列表星云数据构建并去重重复加载逻辑；`DatasetsPage` 已用 `queryKeys.datasets.list` + `useQuery/useQueryClient` 承接数据集主页真实列表加载、刷新与更新/删除后的 Query cache 同步；`query-convergence.source.test.ts`、`kg-predicate-ontology-settings.behavior.test.ts`、industry rules section 源测试、industry-rules-workbench 源测试、governance-profiles 源测试、governance-common-lines 源测试、dataset-ingestion 源测试、env 单测、test-case-manager 源测试、dataset-folder-tree 测试、lineage 源测试、dataset-category 测试、document-health 源测试、ragviz similarity 源测试、dataset tables 源测试、dataset db catalog 源测试、dataset workflow 源测试、vector nebula 源测试、datasets page 源测试、`app/evaluations/page.query.source.test.ts`、`app/history/page.real-data.source.test.ts`、`app/datasets/[id]/profile/page.query.source.test.ts`、`components/test-generation-dialog.query.source.test.ts`、`components/industry-rules/industry-rules-workbench.source.test.ts`、`components/datasets/dataset-kg-workbench-page.source.test.ts`、`components/evaluation/queryset-health-tab-client.query.source.test.ts`、`components/evaluation/retrieval-ablations-page.query.source.test.ts`、`components/rag-trace/rag-trace-panel.source.test.ts` 与 governance 文案源测试已补回归断言。剩余 useEffect/api 热点仍需分批迁移。 |
| #7 类型逃逸预算 | 已落地（预算门禁） | `web/lib/type-safety-budget.source.test.ts` 要求 `@ts-ignore/@ts-nocheck = 0`，显式 `any <= 500`；当前 `npm --prefix web run test` 通过。 |
| #8 `chat.py` 拆分 | 部分落地 | `ConversationSummary*` schema 已下沉到 `app/api/schemas/chat.py`；conversation summary / rag-traces / checkpoint endpoints 已拆到 `app/api/v1/chat_conversation_memory.py`；conversation create/update/list/messages/export/delete endpoints 已拆到 `app/api/v1/chat_conversations.py`，标题 helper 下沉到 `app/services/chat_conversation_titles.py`，会话/文档作用域解析已抽到 `app/services/chat_scope.py`，cache/metadata/summary/stream-persist helper 已抽到 `app/services/chat_runtime.py`；先前把 `stream_chat` 的 keepalive/start-event、cached hit、graph/langchain 分支与 stream error orchestration 下沉到 `chat_runtime.py::stream_chat_sse_events()`，随后把 stream-only helper cluster 继续拆成 `app/services/chat_stream_common.py`、`app/services/chat_stream_graph.py`、`app/services/chat_stream_langchain.py` 和瘦身后的 `app/services/chat_stream_orchestrator.py`；先前已把 non-streaming / streaming persistence 与 finalize cluster 拆到 `app/services/chat_persistence.py`，再把 long-term memory / structured memory retrieval 与 conversation touch helper 拆到 `app/services/chat_memory_runtime.py`，把 cache / singleflight bootstrap 拆到 `app/services/chat_cache_runtime.py`，把 non-streaming graph/langchain execution cluster 拆到 `app/services/chat_execution_runtime.py`，把 request/session/runtime bootstrap 整组拆到 `app/services/chat_bootstrap_runtime.py`，并把 `app/services/chat_runtime.py` 收成薄兼容层（只保留 metrics context、`ChatStreamPersistInput`、error formatting 和显式 re-export）。本轮再把 non-stream turn persistence cluster 拆到新的 `app/services/chat_turn_persistence.py`，把 stream-only persistence cluster 继续留在 `app/services/chat_stream_persistence.py`，并把 `app/services/chat_persistence.py` 压缩到只保留 `finalize_chat_response_sync` 这一类 non-stream finalize/cache-resolve 逻辑；`chat.py` 当前为 `494` 行且 `stream_chat` 路由壳约 `81` 行；共享访问校验抽到 `app/services/chat_conversation_access.py`；`tests/test_chat_router_split_source.py` 与 `tests/test_chat_helper_option_inputs.py` 锁定路由拆分且运行时仍暴露原兼容 helper 面；`web/scripts/api-contract-lib.mjs` 已支持嵌套路由扫描，`api-contract-lib.source.test.ts` 覆盖 contract 扫描。剩余流式 SSE/context/citation/persistence orchestration 仍分布在 `chat_runtime.py`（`140` 行）、`chat_bootstrap_runtime.py`（`436` 行）、`chat_persistence.py`（`125` 行）、`chat_turn_persistence.py`（`146` 行）、`chat_stream_persistence.py`（`286` 行）、`chat_memory_runtime.py`（`142` 行）、`chat_cache_runtime.py`（`286` 行）、`chat_execution_runtime.py`（`300` 行）、`chat_stream_orchestrator.py`（`292` 行）、`chat_stream_common.py`（`176` 行）、`chat_stream_graph.py`（`330` 行）和 `chat_stream_langchain.py`（`293` 行），还需继续 service 化。 |
| #9 SQL f-string 审计 | 已落地（安全约束 + 回归测试） | `app/core/migrations.py` 使用 bind 参数；`tenant_rls.py`、table-store、dataset table API 已统一 identifier/literal quoting；connector/checkpointer/table TAG 的动态 SQL 由 quote helper、整数 clamp 或 table-prefix regex 约束；`tests/test_dynamic_sql_safety_guards.py`、`tests/test_table_store_service.py` 覆盖回退风险。 |
| #10 i18n 单文件拆分 | 已落地 | `web/i18n/messages/zh-CN.ts` 已由 3667 行单文件改为 31 行聚合器；中文消息按域拆到 `web/i18n/messages/zh-CN/*.ts`；`zh-CN.split.source.test.ts` 和全量前端测试覆盖导出兼容。 |
| #11 print → logger | 已落地 | `app/` 与 `main.py` 无 `print()`；`ruff.toml` 已启用 `T201`，仅 `scripts/**` 允许 CLI 输出。 |
| #12 装饰性依赖 | 已落地 | 未使用的 `ParticleBackground` 已删除；`react-tsparticles` / `tsparticles-engine` / `tsparticles-slim` 已从 `web/package.json` 与 lockfile 移除；`lottie-react`、本地 `/lottie/*.json` 与 Lottie SW 缓存已移除，侧栏空状态改为轻量 CSS/SVG 组合。`heavy-imports.source.test.ts` 锁定回归。 |
| #15 requirements 分层 | 已落地（最小分层） | 新增 `requirements-dev.txt`，CI 改装 dev 依赖；runtime `requirements.txt` 移除 pytest/ruff/pip-audit 等开发依赖。 |

**2026-05-12 补充复核**
- `web/e2e/*.spec.ts` 当前实测有 `6` 个 Playwright spec，说明端到端用例并未消失，只是上一轮 60 项审计使用了过窄的 `*.e2e.*` 统计口径。
- `git ls-files '*.onnx'` 当前仍有 `18` 个被追踪 ONNX 文件；`.gitattributes` 已补 `*.onnx filter=lfs diff=lfs merge=lfs -text`，且未被代码引用的 `app/resources/data_parser/qieci/` 重复目录已移除。下一步是把剩余二进制真正迁入 LFS 或改为运行时下载。
- `node web/scripts/check-api-contract.mjs` 与 `check-api-coverage.mjs` 当前均已通过；`check-openapi-coverage.mjs` 在刷新 `web/openapi.json` 与 `web/types/openapi.ts` 后也已通过，前端 API wrapper 与 OpenAPI 规范现已重新对齐。
- `knowledge/feedback`、`knowledge/quarantine`、`knowledge/ingestion` 已改为只有显式 `/demo` 路径才允许演示分支，普通正式页面会忽略 `?demo=1`，更符合“非 demo 页只走真实后端数据”的要求。
- `knowledge/ingestion` 的 execution-monitor 样本 disposition 按钮已改成真实 `documentApi.patchUserMetadata` round-trip，把 `precheck_disposition` / `precheck_reviewed_at` 写入 `documents/{id}.metadata.user`；`app/knowledge/ingestion/page-client.real-data.source.test.ts` 已锁定不再回退到纯本地 `sampleDispositions` 假状态。
- `knowledge/ingestion` 的 sales-audit 样本卡片处置按钮也已改成真实 `PATCH /api/v1/datasets/{dataset_id}/precheck/scan-runs/{scan_run_id}/samples/review` round-trip，把 `review_disposition` / `reviewed_at` / `reviewed_by` 写入 precheck review metadata，并在 `getPrecheckSamples()` 返回时合并回样本列表；同一份 `page-client.real-data.source.test.ts` 已锁定前端必须调用 `datasetApi.patchPrecheckSampleReview(...)`。

**#6 补充证据（2026-05-11）**
- `RegressionTestTab` 已用 `queryKeys.evaluations.regressionRuns` 与 `queryKeys.evaluations.regressionRunDetail` + `useQuery` 承接 regression run 列表与 run detail 轮询，不再依赖 `loadRuns()` / `fetchDetail()` 的手写历史加载链；`components/evaluation/regression-tab.query.source.test.ts` 与 `components/evaluation/regression-tab.layout.source.test.ts` 已锁定 Query 收口和嵌入式布局约束。
- `DatasetIngestionPolicyPage` 已用 `queryKeys.governance.profiles`、`queryKeys.datasets.detail`、`queryKeys.datasets.ingestionPolicy`、`queryKeys.datasets.ingestionStats` + `useQuery` 承接入库策略页治理预设、数据集元数据、入库策略与入库统计真实后端加载，保存/导入/回滚后通过 refetch 同步。
- `app/datasets/[id]/ingestion/page.source.test.ts` 已锁定该页不再用手写 `load()` 管理初始 dataset / policy / stats 加载。
- `DatasetPrecheckPage` 已用 `queryKeys.datasets.detail`、`queryKeys.datasets.precheckRuns` + `useQuery` 承接预检页数据集元数据与扫描 run 列表真实后端加载，扫描完成/SSE 回调/刷新后通过 refetch 同步。
- `app/datasets/[id]/precheck/page-client.source.test.ts` 已锁定该页不再用手写 `load()` / `loadRuns()` 管理初始 dataset / run list 加载。
- `DatasetPrecheckPage` 的“代表性样本 / 近重复 / Diff”按钮现在也已用 `queryKeys.datasets.precheckSamples`、`queryKeys.datasets.precheckNearDups`、`queryKeys.datasets.precheckDiff` + on-demand `useQuery` 承接，不再依赖 `loadSamples()` / `loadNearDups()` / `loadDiff()` 手写按钮读侧；同一份 `page-client.source.test.ts` 已补回退断言。
- `DatasetPrecheckPage` 的“生成入库策略”建议弹窗已用 `queryKeys.datasets.precheckIngestionPolicySuggestion` + on-demand `useQuery` 承接，不再依赖 `policyLoading/policyRes` 本地状态和手写请求链；同一份 `page-client.source.test.ts` 已补回退断言。
- `DatasetPrecheckPage` 的 finding 文件清单弹窗与“加载更多”已用 `queryKeys.datasets.precheckFindingFiles` + `useInfiniteQuery` 承接，不再依赖 `findingLoading/findingRes` 本地追加状态；同一份 `page-client.source.test.ts` 已补回退断言。
- `DatasetProfilePage` 的 finding 文档清单和分桶 drilldown 清单已用 `queryKeys.datasets.profileFindingDocuments` / `profileBucketDocuments` + `useInfiniteQuery` 承接，不再依赖 `findingRes/bucketRes` 本地追加状态；`app/datasets/[id]/profile/page.query.source.test.ts` 已补回退断言。
- `DatasetDbCatalogPage` 的最近同步面板、选中表详情与 profile snapshot 现在也已用 `queryKeys.connectors.runs`、`queryKeys.datasets.dbCatalogTableDetail`、`queryKeys.datasets.dbCatalogProfiles` + `useQuery` 承接，不再依赖 `loadLatestRun()` / `loadDetail()` 手写读侧；`app/datasets/[id]/db-catalog/page.source.test.ts` 已补回退断言。
- `DatasetIngestionPolicyPage` 的版本历史弹窗/刷新/回滚后同步已用 `queryKeys.datasets.ingestionPolicyVersions` + on-demand `useQuery` 承接，不再依赖 `loadVersions()` 手写读侧；`app/datasets/[id]/ingestion/page.source.test.ts` 已补回退断言。
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
- `TenantQuotaPanel` 已从手写 `loadQuota()` 迁移到 `useQuery(enabled: false)` + `queryKeys.usage.tenantQuotaSummary`，仍保持“点击刷新再拉取”的真实后端交互；`components/usage/tenant-quota-panel.source.test.ts` 已锁定不再回退到手写 `loading/setState` 加载模式。
- `DocumentDetailDialog` 的 document detail / access / versions / timeline 读接口已迁到 `useQuery` + `useQueryClient`，分别使用 `queryKeys.documents.detail/access/versions/timeline`；读侧不再保留手写 `loadDetail()` / `loadVersions()` / `loadTimeline()`，编辑与版本切换后通过 query refetch / setQueryData 同步真实后端结果；`components/document-detail-dialog.source.test.ts` 与 `lib/query-keys.test.ts` 已补回归断言。
- `IndustryRulesSection` 已补 `queryKeys.industryRules.ruleset`，规则详情读取改为 `useQuery(enabled: false)` + `refetch()`，保存 glossary / patterns / intents 后通过 `useQueryClient().invalidateQueries(...)` 刷新规则详情缓存；`app/settings/_sections/industry-rules-section.source.test.ts` 与 `lib/query-keys.test.ts` 已补回归断言。

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

#### 1. CI PR gate 已落地（原 Critical）
- **位置**：`.github/workflows/{ci,security,sonar,api-docs}.yml`
- **当前状态**：`pull_request` + `push: main` 已补齐，主线 PR 不再依赖人工 `workflow_dispatch`
- **证据**：`ci.yml` / `security.yml` / `sonar.yml` / `api-docs.yml` 均已包含 `pull_request`；`ci.yml` 还覆盖 backend/frontend tests、Playwright smoke 与 `make verify`
- **后续建议**：若 PR 时延仍偏高，再额外拆一条 `< 3 min` 的 `lint-fast.yml`
- **与既有 plan 关系**：已完成，可从治理主线中移除

#### 2. `app/api/v1/documents.py` 已压到 2188 行 / 1 主路由 — router 级失控已基本收敛
- **位置**：`app/api/v1/documents.py`（最大后端单文件）
- **影响**：业务逻辑塞 router、PR review 不可能完整、merge 冲突高发、grep 找 endpoint 慢
- **证据**：`wc -l app/api/v1/documents.py` = `2188`；同目录已拆出 `23` 个 `document_*.py` 子文件，且 `chunk-preview` route logic 已落到 `app/api/v1/document_chunk_preview.py`，preview/chunk-preview 共用 helper 已抽到 `app/services/document_preview_utils.py`
- **修复方向**：按资源拆分 `documents/` 子目录（list/upload/parse/chunk/embed/version/acl/...）；将业务逻辑下沉到 `app/services/documents/*`；router 文件控制在 ≤500 行
- **工作量**：3-5 天（拆分 + 测试回归）
- **与既有 plan 关系**：与 `batch-2-architecture.md`（前端 api-client.ts 拆分）思路对偶，可作 batch-2 后端篇

#### 3. `app/api/v1/connectors.py` 仍 523 行 — 路由拆出一层，DB catalog / url_batch / GitHub repo / Drive files / MinIO / Confluence / Jira / Web crawl 子簇已继续外移，但主体仍过大
- **位置**：`app/api/v1/connectors.py`
- **影响**：主文件仍承载多个数百行级别的 connector 执行链；catalog 同步、表结构推断、采样等核心逻辑应在 service
- **证据**：`wc -l app/api/v1/connectors.py` = `523`；已拆出 `connectors_catalog/configs/runs/schedules/validation/common/external/state/acl/artifacts/db_catalog/url_batch/github_plan/github_repo/drive_files/minio_bucket/confluence/jira/web_crawl`
- **修复方向**：service 层化（`app/services/connectors/{catalog,sample,schema_infer}/...`），router 仅做参数校验 + 调用
- **工作量**：3-4 天
- **与既有 plan 关系**：无，纯本次发现

#### 4. 仓库卫生部分落地，残留点缩到受追踪生成物
- **位置**：`.gitignore`、`web/.playwright-mcp/`
- **当前状态**：仓库根 `*.png` 已清零，`.beads/`、`runs/.deepseek_ocr/`、`.playwright-mcp/` 等忽略规则已补齐
- **剩余问题**：`git ls-files 'web/.playwright-mcp/*.png'` 当前仍有 `10` 张被 git 跟踪，历史生成图未完全出索引
- **修复方向**：`git rm --cached web/.playwright-mcp/*.png`，并固定视觉产物只进 `artifacts/` 或 PR 附件
- **工作量**：0.5 天
- **与既有 plan 关系**：无

#### 5. `.env.example` 拆分已落地（原 High）
- **位置**：`.env.example`、`config/env/*.env.example`
- **当前状态**：根 `.env.example` 已压到 `104` 行 / `3.3K`，高级配置按模块拆到 `config/env/`
- **证据**：`wc -l .env.example` = `104`；`config/env/` 当前已存在 `database/llm/kg/observability/...` 模块模板
- **后续建议**：继续约束“根模板只放最小启动必填项”，避免再次回膨
- **与既有 plan 关系**：已完成，可从优先治理清单移除

---

### 🟠 High（影响开发效率/可维护性，应排期）

#### 6. 前端数据获取仍偏移，但 TanStack Query 迁移已明显推进
- **位置**：全 `web/` 目录
- **影响**：缺统一缓存/重试/loading 状态、多页面并发请求重复、刷新无 stale-while-revalidate；与 layout 已注入的 QueryProvider 配套不匹配
- **证据**：当前实测 `useMutation = 50`、`useQuery = 244`；仍有 `83` 个前端源码文件同时包含 `useEffect` 和 `fetch/api` 迹象
- **修复方向**：分批迁移高频页面到 useQuery + useMutation，先做 chat/datasets/ingestion 三个 hot path
- **工作量**：5-8 天（分阶段）
- **与既有 plan 关系**：MEMORY.md 中提到此模式问题，但**无独立落地 plan**；建议作 `frontend-tanstack-query-migration` 独立 plan

#### 7. 前端类型逃逸预算门禁已落地，但余量仍值得继续压
- **位置**：分散全 `web/`
- **影响**：strict: true 形同虚设；OpenAPI 生成的 types/openapi.ts 49004 行未充分被使用；refactor 时类型保护失效
- **证据**：`web/lib/type-safety-budget.source.test.ts` 已要求 `@ts-ignore/@ts-nocheck = 0`、显式 `any <= 500`；当前源码实测 `@ts-ignore/@ts-nocheck = 0`、显式 `any = 29`
- **修复方向**：继续把 API/graph 周边 `any` 收敛到 openapi/types，后续可把预算从 `500` 继续压低到 `100` 以内
- **工作量**：1-3 天（渐进清理）
- **与既有 plan 关系**：与 `batch-3-code-quality.md` 思路一致

#### 8. `app/api/v1/chat.py` 已压到 494 行，但流式 orchestration 仍需要继续细拆
- **位置**：`app/api/v1/chat.py`
- **影响**：router 已基本收口，但流式 SSE/context/citation/persistence orchestration 仍然是大块 service；后续维护入口从 endpoint 迁到了 `chat_runtime.py`、`chat_persistence.py` 和多份 `chat_stream_*` module
- **证据**：`wc -l app/api/v1/chat.py app/services/chat_runtime.py app/services/chat_persistence.py app/services/chat_stream_orchestrator.py app/services/chat_stream_common.py app/services/chat_stream_graph.py app/services/chat_stream_langchain.py` = `494 / 1202 / 538 / 292 / 176 / 330 / 293`；`chat_conversation_memory.py` 与 `chat_conversations.py` 已拆出，ask/stream 共用的会话作用域解析已抽到 `app/services/chat_scope.py`，cache/metadata/summary/stream-persist helper、long-term/structured memory runtime helper、request-runtime preparation helper，以及 non-streaming / streaming LangGraph 执行 helper、LangChain streaming producer helper、stream direct-persist sync helper、runtime metrics context helper、cache-store helper、stream persistence dispatch helper、stream done-payload / completion logging helper、cached stream fast-path helper、graph stream session wrapper、LangChain stream session wrapper、ask/stream 共用的 chat-turn session bootstrap helper、non-streaming LangChain 单次执行 helper、non-streaming cache/singleflight bootstrap helper、stream runtime bootstrap helper和本轮继续拆出的 persistence / stream-only helper modules 已抽到 service 层
- **当前进展（2026-05-13）**：会话摘要、checkpoint、conversation CRUD、scope 解析与 router-level 流式 orchestration 已拆走，剩余瓶颈集中在 service 内部的 stream orchestrator / citation / trace / persistence 聚合
- **修复方向**：抽 `app/services/chat/{stream_orchestrator, citation_builder, ...}`；router 仅保留 schema/路由层
- **工作量**：2-3 天
- **与既有 plan 关系**：无

#### 9. SQL 动态拼接审计已基本落地，剩余价值在持续门禁
- **位置**：`app/connectors/db/catalog_runner.py:553,617`、`app/core/migrations.py:48`、`app/rag/checkpointer/sqlite.py:225,238,376,382,404,405`、`app/services/table_tag_service.py:736`
- **影响**：`migrations.py:48` 把 `default_tenant` 直接拼进 `WHERE tenant_id IS NULL UPDATE ... = '{default_tenant}'::uuid` 字符串，即使内部源也是不良习惯
- **当前状态**：文档上方状态表与 `tests/test_dynamic_sql_safety_guards.py` 已表明高风险点已补 bind/quote/regex 防护
- **后续建议**：把 `bandit B608` 或等价自定义检查补进 CI，避免同类动态 SQL 回流
- **工作量**：0.5-1 天
- **与既有 plan 关系**：无

#### 10. i18n 单文件拆分已落地（原 High）
- **位置**：`web/i18n/messages/zh-CN.ts`
- **当前状态**：入口文件已缩到 `31` 行，中文消息按域拆到 `web/i18n/messages/zh-CN/*.ts`
- **证据**：状态表已记录 `zh-CN.split.source.test.ts` 与前端全量测试覆盖导出兼容
- **后续建议**：新增页面继续按 namespace 增量落，不要回到单文件聚合
- **与既有 plan 关系**：已完成，可移出主清单

#### 11. print → logger 已落地（原 High）
- **位置**：`app/`、`main.py`、`ruff.toml`
- **当前状态**：后端源码 `print()` 已清零，`ruff T201` 已启用，只保留脚本侧 CLI 输出例外
- **证据**：`rg -n '^\s*print\(' app main.py --glob '*.py' | wc -l` = `0`
- **与既有 plan 关系**：已完成，可移出主清单

#### 12. 装饰性依赖清理已落地（原 High）
- **位置**：`web/package.json`、`web/pnpm-lock.yaml`
- **当前状态**：`react-tsparticles` / `tsparticles-engine` / `tsparticles-slim` / `lottie-react` 已从依赖和代码面移除
- **证据**：状态表已记录 `heavy-imports.source.test.ts` 锁定回归
- **后续建议**：后续动画统一优先 CSS / SVG / 轻量 motion 方案，避免再引入整套装饰库
- **与既有 plan 关系**：已完成，可移出主清单

---

### 🟡 Medium（建议规划但非紧急）

#### 13. 前端多个 >1500 行单文件待拆（除已知 ingestion/page-client）
- **位置**（按行数）：
  - `web/app/knowledge/ingestion/page-client.tsx` 4976
  - `web/components/ragviz/similarity-workbench.tsx` 3425
  - `web/components/graph/kg-snapshots-page.tsx` 3258
  - `web/components/rag-trace/rag-trace-panel.tsx` 2458
  - `web/app/knowledge/quarantine/page.tsx` 2720（**已在 batch 计划提及**）
  - `web/components/data-governance-panel.tsx` 2255
  - `web/components/graph/kg-diagnostics-page.tsx` 2240
  - `web/components/evaluation/retrieval-ablations-page.tsx` 2049
  - `web/components/chunk-preview/components/workbench/sidebar-client.tsx` 1903
  - `web/app/knowledge/feedback/page.tsx` 1873
  - `web/app/datasets/[id]/profile/page-client.tsx` 1767
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

#### 15. requirements 已做最小分层，剩余是进一步规范化
- **位置**：`requirements.txt`、`requirements-dev.txt`
- **当前状态**：`requirements-dev.txt` 已存在，runtime `requirements.txt` 也已剥离 pytest/ruff/pip-audit 等开发依赖
- **证据**：`wc -l requirements.txt requirements-dev.txt` 当前分别为 `136` / `10`
- **后续建议**：如要继续治理，可再拆 `constraints.txt` / `requirements-runtime.txt`，并把 CI 中 torch wheel URL 收口到依赖层
- **工作量**：0.5-1 天
- **与既有 plan 关系**：已完成最小版，剩余是增强项

---

## 推荐落地次序（4 周渐进，基于 2026-05-12 现状）

| 周次 | 任务 | 收益 |
|---|---|---|
| **Week 1** | #4 彻底清掉已跟踪生成图 + #8 `chat.py` 流式主链路 service 化 | 仓库卫生收口 + chat 主链路止血 |
| **Week 2** | #2 `documents.py` 继续拆 + #3 `connectors.py` 继续拆 | 后端 API 层失控继续止血 |
| **Week 3** | #6 TanStack Query 继续迁移 hot path + #13 前端超大组件拆分 | 前端数据流和可维护性同步改善 |
| **Week 4** | #14 后端大服务文件拆分 + #9 SQL/安全门禁补 CI | 持续治理，防止回流 |
| **后续** | #7 继续压缩 `any` 预算，#15 视需要补 constraints/runtime 分层 | 长线质量治理 |

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
