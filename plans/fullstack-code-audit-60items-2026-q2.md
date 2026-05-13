# MimirQ 全栈代码审计 — 60 条问题清单(2026-05 更新版)

> **本次更新**:对照原 plan 60 条逐项实测代码,多条问题已完成或降级移出主清单,**2 条确认倒退**,另有多处旧判断已被 `2026-05-12` 二次复核修正,其余按进度更新或保留,并按严重度重新排序。
>
> **审查时间**:2026-05-12 — 与 plan 原始撰写时(2026-Q2 初)间隔 ~1 个月；2026-05-13 追加闭环 H11 / M3 / H4 / M11 / C10,并复核降级 monaco public。
> **审查方法**:`grep`/`wc -l`/`git ls-files`/`find` 实测。

---

## Context

**问题与触发**
用户要求"审核已经做了的删掉,plan 更新一下"。原 plan 列 60 条详尽 audit,需要逐项验证当前代码状态,清理已完成项,把仍存在的问题刷新进度数据。

**本轮发现**
- ✅ 多条已 100% 完成(异常治理、CI gate、i18n 拆分、openapi 收敛、print 清理等)
- 🟡 多条部分完成,**更新进度数据**(documents/connectors/chat 拆分继续推进、useMutation 从 7→50、`.env.example` 从 53KB→3.3KB 并拆出模块模板等)
- 🔴 **1 条仍需重点治理的倒退 / 残留主线**:
  - **#32**:`similarity-workbench.tsx` 从 2744 → **3425 行**;`quarantine/page.tsx` 从 2115 → **2720 行**(都变更大)
  - **#30**:`stream_chat` 路由壳已从先前的 **1533+ 行**降到当前约 **81 行**；流式 orchestration 又从单一 `chat_stream_orchestrator.py` 继续拆成 `chat_stream_common.py` / `chat_stream_graph.py` / `chat_stream_langchain.py` / `chat_stream_orchestrator.py`，但整条流式 service 链路合计仍然偏大
- 🔁 **2026-05-12 二次复核修正**:
  - **#22**:旧文档写成 React.memo 从 4 处降到 **0 处**,但当前实测 `memo()/React.memo` 仍有 **4 处**
  - **#38**:旧文档写成 e2e tests **0 个**,但当前 `web/e2e/*.spec.ts` 实测 **6 个**
  - **#9**:仓库根 PNG 已清零,且 `web/.playwright-mcp/*.png` 当前已通过 `git rm --cached` 收敛到 **0 张** 被 git 追踪

---

## 关键量化指标对比(2026-Q2 初 → 2026-05)

| 指标 | 初 | 现 | Δ |
|---|---|---|---|
| 后端 except: pass | 418 | **0** | ✅ 全清 |
| 后端 except + logger.warning 无 raise | 205 | **6** | ✅ 97% 清 |
| 后端 sa.Index | 0 | **16** | 🟠 增 |
| alembic `op.create_index` | 0 | **0** | ℹ️ 迁移仍以 `CREATE INDEX` SQL 为主 |
| 后端 print() | 28 | **0** | ✅ |
| 后端 endpoints | 367 | **369** | 🟠 |
| 后端 v1/ documents.py | 11770 | **2235**(拆出 23 子文件 + preview utils, 主文件 `0` route) | 🟢 大幅下降 |
| 后端 v1/ connectors.py | 10697 | **523**(拆出 20 子文件/模块) | 🟢 继续下降 |
| 后端 v1/ chat.py | 3653 | **494** | 🟢 继续下降 |
| 后端 requests vs httpx | 20 / 22 | **29 app files / settings.py 已迁 httpx** | ❌ 分批迁移 |
| 后端 f-string SQL | 31 | **20** | 🟠 |
| 后端 Pydantic v1 残留 | 35 | **11** | 🟠 |
| 后端 datetime.now() 无 tz | 5 | **0** | ✅ 已加 source guard |
| 后端 endpoint docstring 缺失 | 未实测 | **160 / 369** | 🟠 批次推进 |
| 后端 logger 两套(`logging.getLogger(__name__)` / `get_logger(...)`)| 不详 | **0 / 121** | ✅ 已统一入口 |
| 前端 useMutation | 7 | **50** | 🟢 |
| 前端 useQuery | 不详 | **244** | 🟢 |
| 前端 useMemo/useCallback | 1149 | **1565** | 🔴 继续膨胀 |
| 前端 memoized 组件(`memo`/`React.memo`) | 4 | **4** | ~ |
| 前端 `: any`(graph-viewer / force-graph-3d / scim.ts) | 28/27/13 | **27/26/5** | 🟠 部分降 |
| 前端 `.then()` 无 `.catch()` | 42 | **34** | 🟠 |
| 前端 `key={index}` | 14 | **0** | ✅ 已加 source guard |
| 前端 Playwright e2e/spec | 7 | **6** | 🟠 基本恢复,但覆盖面仍偏薄 |
| `stream_chat` 函数行数 | 1305 | **81** | 🟢 路由壳已显著收口 |
| 前端 similarity-workbench.tsx | 2744 | **3425** | 🔴 倒退 |
| 前端 quarantine/page.tsx | 2115 | **2720** | 🔴 倒退 |
| 前端 i18n zh-CN.ts | 3667 | **31** | ✅ 已拆 namespace |
| 前端 types/index.ts | 3008 | **30** | ✅ 已收敛 openapi |
| 前端 monaco public | 16M | **0 tracked / 16M ignored generated** | ✅ 降级为本地生成物 |
| 前端 ts target | ES2017 | **ES2022** | ✅ 已加 source guard |
| 前端 alert() | 1 | **0** | ✅ |
| .env.example | 53KB | **3.3KB / 104 行** | 🟠 大幅瘦身,并已拆出模块模板 |
| 仓库根 PNG | 10+ | **0** | ✅ 已清零 |
| ONNX git 追踪 | >600MB | **18 个仍在；未引用 qieci 重复目录已删** | 🟠 |
| CI workflows | 10 | **11**(已补 lint-fast.yml) | ✅ |
| CI `on: pull_request` gate | 仅 dispatch | **已加 pull_request + push:main** | ✅ |

---

## ✅ 已 100% 完成/降级清单(本轮显式记录)

| 原 # | 内容 | 实测结果 |
|---|---|---|
| 1 | 418 处 `except: pass` 吞异常 | **0 处** ✅ |
| 7 | CI 主流水线仅 `workflow_dispatch` | 已加 `pull_request` + `push: branches: main` ✅ |
| 10 | .gitignore 缺 `.beads/` `logs/` `runs/` `.playwright-mcp/` | 全部补齐 ✅ |
| 15 | `documents.py:11690` example code 写死 localhost | grep 无命中 ✅ |
| 16 | `logging.getLogger(__name__)` vs `get_logger` | `logging.getLogger(__name__)` 已清零,新增 `tests/test_logging_get_logger_source.py` ✅ |
| 26 | 28 处 `print()` 残留 | **0 处** ✅ |
| 35 | `zh-CN.ts` 3667 行单文件 i18n | 已拆为 31 行 entry + namespace 子文件 ✅ |
| 36 | `web/types/index.ts` 3008 行手写类型 | 已收敛到 30 行 re-export + openapi.ts 单源 ✅ |
| 39(部分) | tsparticles + lottie 重复依赖 | tsparticles 已不在 package.json ✅ |
| 44 | 前端 `alert()` 浏览器原生 | **0 处** ✅ |
| 29 | `datetime.now()` 裸调用无 tzinfo | `app/**/*.py` 已清零,新增 `tests/test_datetime_now_utc_source.py` ✅ |
| 42 | 前端 TS target 仍为 `ES2017` | 已升 `ES2022`,新增 `web/tsconfig.source.test.ts` ✅ |
| 21 | 前端 `key={index}` | 实测 8 处已清零,新增 `web/react-keys.source.test.ts` ✅ |
| 54 | CI workflows 无 `lint-fast.yml` | 已新增 PR/push/main 必跑的轻量 lint/typecheck workflow ✅ |
| 40/41(降级) | `web/public/monaco` 16M | 0 个 git-tracked 文件,`.gitignore` 已忽略,由 `predev/prebuild` 生成 ✅ |
| 2(降级) | 205 处 `except + logger.warning` 无 raise | **6 处** — 降级到 Medium |

---

## 🔴 Critical(11 条,本轮新顺序)

### A. 错误处理 / 数据库

#### C1(原 #3 + #49)— Alembic 索引问题经二次复核后收敛为“风格/落库验证”而非“缺失迁移”
- **进展**:`app/models/*.py` 里 **16** 个 `Index(...)` 名称与当前 `alembic/versions/*.py` 中的索引 SQL 名称比对后,**差集为 0**
- **现状**:当前问题不是“16 个 model index 没写进 migration”,而是 Alembic 仍主要通过 `CREATE INDEX` SQL 字符串维护,且缺少对既有部署实例是否真实落库的验证
- **修复**:优先用 `pg_indexes` / `psql \d+` 校验生产/测试库真实索引是否齐全;只有出现实例级 drift 时才补新 migration

### B. API 层超失控(进度更新)

#### C2(原 #4)— `app/api/v1/documents.py` 已压到 **2235 行**(从 11770 持续下降)
- **已完成**:拆出 **23 个 `document_*.py` 子文件**(新增 `document_preview.py` / `document_upload.py` / `document_chunk_preview.py`)；并把 preview/chunk-preview 共用 helper 抽到 `app/services/document_preview_utils.py`
- **现状**:`upload` / `upload-url` / `upload-batch` 与 `chunk-preview` 主干均已落到分拆模块，主文件当前 `@router.* = 0`，已收口为兼容导出 + shared helper surface；后续价值更偏向继续下沉 shared helper/service，而不是再把大段 endpoint 塞回 router

#### C3(原 #5)— `app/api/v1/connectors.py` 仍 **523 行**(从 10697 继续下降)
- **已完成**:拆出 20 个已接线子文件/模块(新增 `connectors_common.py` / `connectors_external.py` / `connectors_state.py` / `connectors_acl.py` / `connectors_artifacts.py` / `connectors_db_catalog.py` / `connectors_url_batch.py` / `connectors_github_plan.py` / `connectors_github_repo.py` / `connectors_drive_files.py` / `connectors_minio_bucket.py` / `connectors_confluence.py` / `connectors_jira.py` / `connectors_web_crawl.py`; catalog/configs/runs/schedules/validation/common/external/state/acl/artifacts/db_catalog/url_batch/github_plan/github_repo/drive_files/minio_bucket/confluence/jira/web_crawl/web_crawl_plan)
- **补充**:`connectors_common.py` 当前已承接 connector 通用错误分类 / stats 聚合 helper cluster; `connectors_external.py` 当前已承接 Drive / GitHub 外部源 URL / auth / ACL helper cluster,并继续接住 `http/https` 与 link href 校验；`connectors_state.py` 当前已承接 connector ACL summary / run-config out / schedule / config-sync helper cluster; `connectors_acl.py` 当前已承接通用文档 ACL 应用 / source_url-source_ref soft-disable / Jira issue-attachment-linked-artifact ACL reconcile helper cluster; `connectors_artifacts.py` 当前已承接 connector identity metadata / db row sidecar helper cluster; `connectors_github_repo.py` 当前已承接 github repo runtime cluster; `connectors_drive_files.py` 当前已承接 drive files runtime cluster; `connectors_minio_bucket.py` 当前已承接 minio bucket runtime cluster; `connectors_confluence.py` 当前已承接 confluence 专属 helper/runtime cluster; `connectors_jira.py` 当前已承接 jira pure helper/render/settings、orchestration shell、resolve/progress/finalize、issue-processing，以及 attachments / linked-artifacts / run-stats 子簇; `connectors_web_crawl.py` 当前已承接 web crawl runtime cluster,并复用 `connectors_web_crawl_plan.py` 中的 plan/manifest helper
- **剩余**:进度仍明显慢于 documents,需要继续拆 schema_infer / sample / oauth_flows / web_crawl / jira,重点已经进一步转向 web crawl residual helper 和更深的 service 化

#### C4(原 #6 + #30)— `app/api/v1/chat.py` 已压到 **494 行**(从 3653),流式 router 主链路已显著收口
- **进展**:已把 ask/stream 共用的会话/文档作用域解析抽到 `app/services/chat_scope.py`,并把 cache/metadata/summary/stream-persist helper 抽到 `app/services/chat_runtime.py`; 前几轮已下沉 long-term / structured memory retrieval、turn-touch helper、ask/stream 共用的 request-runtime preparation 链、non-streaming 的 LangGraph 单次执行分支、streaming 的 LangGraph 事件分支、LangChain streaming producer 子链、stream direct-persist 收尾同步、通用的 runtime metrics context / cache-store helper、stream persistence dispatch helper、stream done-payload / completion logging helper、cached stream fast-path helper、graph stream session wrapper、LangChain stream session wrapper、ask/stream 共用的 chat-turn session bootstrap helper、non-streaming LangChain 单次执行 helper、non-streaming cache/singleflight bootstrap helper，以及 stream runtime bootstrap helper；先前把 `stream_chat` 的 keepalive/start-event、cached hit、graph/langchain 分支与 stream error orchestration 统一下沉到 `app/services/chat_runtime.py::stream_chat_sse_events()`，随后把 stream-only helper cluster 继续拆成 `app/services/chat_stream_common.py`（done/log/cached 收尾）、`app/services/chat_stream_graph.py`（graph 流式链路）、`app/services/chat_stream_langchain.py`（langchain 流式链路）和瘦身后的 `app/services/chat_stream_orchestrator.py`（顶层分发）；先前再把 non-streaming / streaming persistence 与 finalize cluster 拆到 `app/services/chat_persistence.py`（`build_chat_message_metadata` / `auto_update_summary_background` / `dispatch_chat_stream_persistence` / `persist_chat_turn_sync` / `finalize_chat_response_sync` / `persist_chat_stream_turn_sync` / `persist_chat_stream_turn_background`），之后新增 `app/services/chat_memory_runtime.py` 承接 `_retrieve_long_term_messages` / `_retrieve_structured_memory_records` / `_touch_conversation_after_turn`，新增 `app/services/chat_cache_runtime.py` 承接 `ChatCacheLookupInput` / `PreparedNonStreamingChatCacheState` / `prepare_chat_cache_lookup` / `prepare_non_streaming_chat_cache_state` / cache-singleflight metrics helper，新增 `app/services/chat_execution_runtime.py` 承接 `execute_graph_chat_once` / `execute_langchain_chat_once` / `ExecutedGraphChatOnceResult`，新增 `app/services/chat_bootstrap_runtime.py` 承接 `PreparedChatRequestRuntime` / `PreparedChatTurnSession` / `PreparedStreamChatRuntime` 与 `prepare_chat_turn_session` / `prepare_chat_request_runtime` / `prepare_stream_chat_runtime`，并把 `app/services/chat_runtime.py` 收成仅 `140` 行的薄兼容层；本轮再新增 `app/services/chat_turn_persistence.py` 承接 `build_chat_message_metadata` / `auto_update_summary_background` / `persist_chat_turn_sync`，同时把 `stream` 专属 persistence 保持在 `app/services/chat_stream_persistence.py`，并把 `app/services/chat_persistence.py` 进一步压到 `125` 行，仅保留 non-streaming finalize/cache resolve 逻辑；`app/api/v1/chat.py` 兼容导出 wrapper 已同步保留 helper 接口以维持旧测试和调用面。主路由文件从 **2834 → 2588 → 2402 → 2234 → 2107 → 1851 → 1707 → 1577 → 1524 → 1431 → 1325 → 1240 → 1212 → 1179 → 1124 → 1025 → 960 → 908 → 874 → 821 → 788 → 761 → 494**；`stream_chat` 路由壳当前约 **81 行**
- **剩余**:`app/api/v1/chat.py` 已不再是主要瓶颈；当前瓶颈转为 `app/services/chat_runtime.py` **140 行** + `app/services/chat_bootstrap_runtime.py` **436 行** + `app/services/chat_persistence.py` **125 行** + `app/services/chat_turn_persistence.py` **146 行** + `app/services/chat_stream_persistence.py` **286 行** + `app/services/chat_memory_runtime.py` **142 行** + `app/services/chat_cache_runtime.py` **286 行** + `app/services/chat_execution_runtime.py` **300 行** + `app/services/chat_stream_orchestrator.py` **292 行** + `app/services/chat_stream_common.py` **176 行** + `app/services/chat_stream_graph.py` **330 行** + `app/services/chat_stream_langchain.py` **293 行**，流式 orchestration / citation / trace / persistence 仍需要继续模块化
- **修复**:**优先级 P0**,继续抽 `services/chat/{stream_orchestrator,citation_builder,trace_emitter}`

### C. 仓库治理

#### C5(原 #8)— ONNX 仍在 git 追踪,但重复目录已在当前工作区收敛
- **现状**:`git ls-files '*.onnx'` 当前为 **18** 个;`.gitattributes` 已补 `*.onnx filter=lfs diff=lfs merge=lfs -text`
- **进展**:未被任何代码/测试引用的 `app/resources/data_parser/qieci/` 已移除,保留实际被 `deepdoc` 路径使用的 `app/deepdoc/resources/**`
- **剩余**:现有已跟踪 ONNX 还没有真正迁入 LFS,仓库体积压力仍在
- **修复**:① 把剩余 18 个 ONNX 迁入 Git LFS 或改为运行时下载 ② 继续核对 `app/deepdoc/resources/models/**` 是否还能再瘦身

#### C6(原 #9)— 仓库根 PNG 与 `.playwright-mcp` 追踪图已在当前工作区清理
- **现状**:仓库根 `*.png` 仍为 **0**;`.gitignore` 已覆盖 `chunk-preview-*.png` / `graph-snapshots-*.png` / `.playwright-mcp/`
- **进展**:`git rm --cached web/.playwright-mcp/*.png` 已执行,当前 `git ls-files 'web/.playwright-mcp/*.png'` 为 **0**
- **后续**:保持视觉产物只进 `artifacts/` 或 PR 附件,避免再入仓

### D. 安全

#### C7(原 #11)— `web/next.config.mjs` 已补基础安全头
- **现状**:`headers()` 已添加 `Referrer-Policy` / `X-Content-Type-Options` / `X-Frame-Options` / `Permissions-Policy`;生产环境额外补 `Strict-Transport-Security`
- **说明**:由于当前 CSP 仍依赖 `web/proxy.ts` 的 nonce 注入,`next.config` 未额外重复写 CSP,以免和代理层冲突

#### C8(原 #13)— `app/api/v1/settings.py` 的 2 处 OpenAI base 默认值已收口到全局配置
- **现状**:`LLMConfig.api_base` 与 `TestLLMRequest.api_base` 已改为通过 `settings.LLM_API_BASE` 取默认值,不再内联 `https://api.openai.com/v1`
- **验证**:`tests/test_settings_endpoints.py` 已补默认值回归断言

### E. 代码质量

#### C9(原 #14)— endpoint docstring 缺失已从 **181 → 160 / 369**
- **进展**:2026-05-13 用 AST 精确改为只统计 FastAPI endpoint,不再沿用旧的“257/4838 def lines”粗口径。
- **本批完成**:`auth.py`、`dataset_analysis.py`、`dataset_categories.py` 共 21 个 endpoint 已补 docstring。
- **守卫**:新增 `tests/test_endpoint_docstrings_source.py`,先锁住上述 3 个模块的 endpoint docstring 不回退。
- **剩余**:还有 160 个 endpoint 缺 docstring,应继续按模块批次推进,下一批优先 `dataset_precheck.py` / `evidence.py` / `observability.py`。

#### C10(原 #16)— logger 两套已统一:`logging.getLogger(__name__)` **0 处** + `get_logger("...")` **121 处**
- **进展**:`rag/agents`、`rag/tools`、`rag/workflows`、`rag/tracing`、`rag/output`、`rag/chunking`、`rag/evaluation` 和 `deepdoc/vision/t_ocr.py` 的剩余 19 处已统一到 `app.rag.core.logging.get_logger`。
- **验证**:`pytest tests/test_logging_get_logger_source.py -q`;`rg -n "logging\.getLogger\(__name__\)" app --glob '*.py'` 无命中。

### F. 配置

#### C11(原 #17)— `.env.example` 已从 53KB 瘦到 **3.3KB / 104 行**,并已拆出模块模板
- **进展**:`config/env/*.env.example` 已存在,主 example 大幅瘦身 ✅
- **剩余**:继续约束根 `.env.example` 只保留最小启动必填项,防止再次回膨
- **修复**:把新模块配置继续落到 `config/env/`;根模板只列真正必填项

---

## 🟠 High(15 条,本轮)

### 前端代码

#### H1(原 #18)— useMutation 从 7 → **50 处**,useQuery **244 处** 🟢 大幅改善但未完成
- **剩余**:chat / datasets / ingestion / knowledge 4 hot path 仍有 **83 个**源码文件同时出现 `useEffect` 与 `fetch/api` 迹象,统一数据流还没做完
- **新增进展（2026-05-13）**:`RegressionTestTab` 已用 `queryKeys.evaluations.regressionRuns` / `regressionRunDetail` + `useQuery` 承接 regression run 列表与 run detail 轮询,不再依赖 `loadRuns()` / `fetchDetail()` 手写链；`components/evaluation/regression-tab.query.source.test.ts` 已补回退约束
- **新增进展（2026-05-13）**:`DatasetPrecheckPage` 的“代表性样本 / 近重复 / Diff”按钮已用 `queryKeys.datasets.precheckSamples` / `precheckNearDups` / `precheckDiff` + on-demand `useQuery` 承接,不再依赖 `loadSamples()` / `loadNearDups()` / `loadDiff()` 手写读侧
- **新增进展（2026-05-13）**:`DatasetPrecheckPage` 的“生成入库策略”建议弹窗已用 `queryKeys.datasets.precheckIngestionPolicySuggestion` + on-demand `useQuery` 承接,不再依赖 `policyLoading/policyRes` 本地状态和手写请求链
- **新增进展（2026-05-13）**:`DatasetPrecheckPage` 的 finding 文件清单弹窗与“加载更多”已用 `queryKeys.datasets.precheckFindingFiles` + `useInfiniteQuery` 承接,不再依赖 `findingLoading/findingRes` 本地追加状态
- **新增进展（2026-05-13）**:`DatasetProfilePage` 的 finding 文档清单和分桶 drilldown 清单已用 `queryKeys.datasets.profileFindingDocuments` / `profileBucketDocuments` + `useInfiniteQuery` 承接,不再依赖 `findingRes/bucketRes` 本地追加状态
- **新增进展（2026-05-13）**:`DatasetDbCatalogPage` 的最近同步面板、选中表详情与 profile snapshot 已用 `queryKeys.connectors.runs` / `queryKeys.datasets.dbCatalogTableDetail` / `queryKeys.datasets.dbCatalogProfiles` + `useQuery` 承接,不再依赖 `loadLatestRun()` / `loadDetail()` 手写读侧
- **新增进展（2026-05-13）**:`DatasetIngestionPolicyPage` 的版本历史弹窗/刷新/回滚后同步已用 `queryKeys.datasets.ingestionPolicyVersions` + on-demand `useQuery` 承接,不再依赖 `loadVersions()` 手写读侧
- **修复**:继续推进,目标 useMutation > 100

#### H2(原 #19)— `: any` 集中文件仅部分清理
- 现状:`graph-viewer.tsx` 27 / `force-graph-3d.tsx` 26 / `scim.ts` **5**(原 13,部分清)/ `document-detail-dialog.tsx` 不详
- **修复**:scim.ts 继续清;graph 层抽通用 `Node`/`Edge` 类型

#### H3(原 #20)— `.then()` 无 `.catch()` 从 42 → **34 处**
- **修复**:加 ESLint `@typescript-eslint/no-floating-promises`

#### H4(原 #21)— `key={index}` 已清零
- **现状**:2026-05-13 实测精确命中为 8 处,已全部替换为语义稳定 key。
- **范围**:`knowledge/feedback`、`knowledge/ingestion`、`graph-canvas`、`similarity-workbench` 的固定装饰/占位数组。
- **验证**:`pnpm -C web exec vitest run react-keys.source.test.ts`；`rg -n "key=\{\s*index\s*\}" web --glob '*.tsx' --glob '*.ts'` 无命中。

#### H5(原 #22)— memoized 组件仍只有 **4 处**,而 useMemo/useCallback 已到 **1565 处**
- **影响**:缓存型 hooks 继续增长,但真正切断子树重渲染的 memoized 组件数量没有同步提升,优化结构失衡
- **修复**:① React Profiler 找渲染瓶颈 ② 大列表 item / markdown / chat message 子项优先补 `memo` ③ 移除明显过度的 useMemo/useCallback

#### H6(原 #23)— ESLint 仍关 `react-hooks/set-state-in-effect` + `preserve-manual-memoization`
- **现状已确认**:`web/eslint.config.js` 仍有 `'react-hooks/set-state-in-effect': 'off'`
- **修复**:hot path 修了再开规则

#### H7(原 #24)— `page.tsx` vs `page-client.tsx` 命名不一致,仍 **8 个 page-client.tsx**
- **修复**:统一命名(推荐 page.tsx + 内部 `_components/`);写 ADR

### 后端代码

#### H8(原 #25)— f-string SQL 从 31 → **20 处**
- **剩余位置**:`app/connectors/db/catalog_runner.py`、`core/migrations.py`、`rag/checkpointer/sqlite.py`、`services/table_tag_service.py`
- **修复**:bandit B608 规则 + SQLAlchemy `text()` + `bindparam`

#### H9(原 #27)— `requests` 仍分布在 **29 个 app 文件**,已开始按风险分批迁移
- **进展**:`app/api/v1/settings.py::_probe_http_json` 已从局部 `requests.get()` 改为同步 `httpx.Client`,并新增 `tests/test_settings_httpx_source.py` 防回归。
- **现状**:剩余 requests 主要集中在 MinerU 服务、OCR/parser 上传链路、parsing enrich/preprocess 以及第三方 integrated pipeline;这些路径包含文件上传、长超时下载和兼容第三方 Response 类型,不宜一轮硬迁。
- **验证**:`pytest tests/test_settings_httpx_source.py tests/test_settings_endpoints.py -q`;`rg -n "import requests|requests\.get\(" app/api/v1/settings.py` 无命中。
- **修复**:继续按模块拆批迁移到 `httpx.Client` / `httpx.AsyncClient`,并为每个解析器补兼容测试后再启用 ruff `S113`。

#### H10(原 #28)— Pydantic v1 残留从 35 → **11 处**
- **修复**:codemod 替换 `.model_dump()` / `.model_dump_json()`

#### H11(原 #29)— `datetime.now()` 无 tzinfo 已清零
- **现状**:`app/**/*.py` 裸 `datetime.now()` 已由 source guard 约束为 0；运行时代码改用兼容 Python 3.10 的 `datetime.now(timezone.utc)`。
- **验证**:`pytest tests/test_datetime_now_utc_source.py -q`；`rg -n "datetime\.now\(\)" app --glob '*.py'` 无命中。

#### H12(原 #31)— 5 个 utils.py 散落
- **修复**:按职能命名(`text_utils.py` / `geom_utils.py`)或并入 `core/`

### 大文件与测试覆盖

#### H13(原 #32)🔴 **倒退** — 前端多个 >2000 行单文件继续膨胀
- `similarity-workbench.tsx` 2744 → **3425**(+25%)
- `quarantine/page.tsx` 2115 → **2720**(+29%)
- `rag-trace-panel.tsx` 2458 → 不详
- `kg-snapshots-page.tsx` 2482 → 不详(可能已拆)
- **修复**:**P0 priority**,按子能力拆

#### H14(原 #34)— 后端 service 层超大文件仍存
- `parsing/processors/processor.py` **5539** / `services/dataset_precheck_scan_runner.py` 1924 / `services/report_html.py` 1822 / `services/indexer.py` 1627 / `services/dataset_profile_service.py` 1579
- **修复**:拆模块化

#### H15(原 #38)— Playwright 端到端用例已恢复到 **6 个 spec**,但核心业务面覆盖仍偏薄
- **现状**:`web/e2e/*.spec.ts` 当前有 `backend-business-surfaces.live`、`command-menu-document-view`、`document-chat.smoke`、`live-stack.smoke`、`management-surfaces.smoke`、`visual-regression`
- **判断**:旧文档里“e2e = 0”的结论已失效,但 datasets / knowledge / ingestion 的核心业务流仍没有形成稳定的领域化回归矩阵
- **修复**:把现有 smoke/live/visual 用例之外,继续补 `datasets` / `knowledge` / `ingestion` 领域型 e2e,目标至少 4 条稳定主流程

#### H18(新增补充)— 普通知识页已不再接受 `?demo=1` 触发本地演示分支
- **现状**:`knowledge/feedback`、`knowledge/quarantine`、`knowledge/ingestion` 当前只有在路径显式匹配 `/demo` 时才允许 demo 分支;普通正式页面会忽略 `?demo=1`
- **新增证据**:`knowledge/ingestion` 的 execution-monitor 样本卡片/抽屉处置按钮已改成真实 `documentApi.patchUserMetadata` round-trip,把 `precheck_disposition` / `precheck_reviewed_at` 写入 `documents/{id}.metadata.user`,不再只改前端本地 `sampleDispositions`
- **新增证据**:`knowledge/ingestion` 的 sales-audit 样本卡片处置按钮已改成真实 `PATCH /api/v1/datasets/{dataset_id}/precheck/scan-runs/{scan_run_id}/samples/review` round-trip,后端会把 `review_disposition` / `reviewed_at` / `reviewed_by` 写入 precheck review metadata,并在 samples 读接口返回时合并回前端样本列表
- **验证**:前端 source tests 已覆盖 `non-demo-real-backend` 与对应页面 real-data gating 断言

### 测试 / 其他

#### H16(原 #33)— `chunk-preview/context.tsx` 仍 **1449 行** 巨型 Context
- **修复**:拆细粒度 Context 或迁 zustand

#### H17(原 #37)— 3 个 1500+ 行核心 service 仍零测试
- `dataset_precheck_scan_runner` 1924 / `dataset_profile_service` 1579 / `rag_metrics_dashboard` 1500
- **修复**:每个至少 5 个 happy path test

---

## 🟡 Medium(11 条,本轮)

### 前端

#### M1(原 #2 降级)— `except + logger.warning` 无 raise 从 205 → **6 处** 🟡
- **修复**:剩余 6 处补 `error_code` 写到响应

#### M2(原 #40 + #41)— 重型库懒加载 + monaco 16MB 已重新定级
- **现状**:`web/public/monaco` 本地仍约 16M,但 `git ls-files 'web/public/**' | rg "monaco|vs/"` 无命中,且 `.gitignore` 已覆盖 `web/public/monaco/`。
- **说明**:Monaco runtime 仍由 `predev/prebuild` 的 `scripts/sync-monaco-assets.mjs` 生成到 public path,以匹配 `loader.config({ paths: { vs: '/monaco/vs' } })`;当前仓库治理风险已关闭,剩余只是本地生成物体积。
- **验证**:`git check-ignore -v web/public/monaco/vs/loader.js`;`git ls-files 'web/public/**' | rg "monaco|vs/"` 无命中。

#### M3(原 #42)— TS target 已升 `ES2022`
- **现状**:`web/tsconfig.json` 的 `compilerOptions.target` 已从 `ES2017` 升到 `ES2022`。
- **验证**:`pnpm -C web exec vitest run tsconfig.source.test.ts`；`pnpm -C web exec tsc --noEmit`。

#### M4(原 #43)— zustand store 3 个仍散在 `web/store/`
- **修复**:写 ADR 明确 zustand vs Context vs TanStack Query 分工

#### M5(原 #45)— `suppressHydrationWarning` 仍 1 处
- **修复**:找出真实 SSR/CSR 不一致并修

### 后端

#### M6(原 #12)— 前端 hardcode `localhost`/`127.0.0.1` 从 16 → **10 处**
- **修复**:统一走 `web/lib/env.ts` `NEXT_PUBLIC_API_URL`;ESLint 规则禁字面量

#### M7(原 #46)— magic numbers(0.5/0.7/0.85 等阈值)
- **修复**:抽 `app/rag/constants.py` 或 `settings`

#### M8(原 #48)— 后端 cache 装饰器仅 17 处
- **修复**:热点纯函数加 `functools.cache`

#### M9(原 #50)— SQLAlchemy session 74 处散落
- **修复**:审计是否有 service 层直接 `SessionLocal()` 不通过 DI

### 工程化

#### M10(原 #51)— `requirements.txt` 部分拆(已有 `requirements-dev.txt`)
- **进展**:`requirements-dev.txt` 已存在
- **剩余**:未拆 `requirements-runtime.txt` + `constraints.txt`

#### M11(原 #54)— CI fast lane 已补 `lint-fast.yml`
- **现状**:新增 `.github/workflows/lint-fast.yml`,覆盖 `pull_request` / `push: main` / `workflow_dispatch`,与慢速 `ci.yml` 分离。
- **范围**:只安装 `ruff` 和 web 依赖,运行 Python lint、web lint、web typecheck,不跑后端全量依赖和 Playwright。
- **验证**:`pytest tests/test_lint_fast_workflow.py -q`。

---

## 🟢 Low(6 条,保留)

| # | 内容 | 现状 |
|---|---|---|
| L1(原 #52)| Makefile 380 行 + 60+ targets | 380 行不变 |
| L2(原 #53)| docker/ 6 个 compose 缺组合矩阵文档 | 不变 |
| L3(原 #55)| `cn(...)` 1175 处可抽 design token | 渐进 |
| L4(原 #56)| 大文件内联 onClick 函数 | 与 H5 配套 |
| L5(原 #57)| 后端 8 个 TODO / 前端 2 个 — 反而可疑 | 不变 |
| L6(原 #60)| 文档分散 docs/19 + docs-site/ + plans/ | 写 `docs/INDEX.md` sitemap |

---

## 推荐落地次序(8 周渐进,基于本轮实测重排)

| 周次 | 任务 | 收益 | 工作量 |
|---|---|---|---|
| **W1** | **C5 剩余 ONNX 迁 LFS + C4 chat.py 继续拆流式主链路** | 仓库瘦身 + 主链路止血 | 4 天 |
| **W2** | **C2 documents.py 继续拆 + C3 connectors.py 继续拆 + C1 用真实 DB 验证索引落库** | API 层失控继续止血 | 5 天 |
| **W3** | **H15 e2e 重建 4 flow(倒退最严重)+ H13 similarity-workbench / quarantine page 拆分(倒退)** | 倒退止血 | 5 天 |
| **W4** | **C4 chat.py + stream_chat 大函数拆分** | 倒退 + 长函数同步治理 | 5 天 |
| **W5** | **C2 documents.py 继续拆(chunk preview / upload pipeline / version mgmt)+ C3 connectors.py 继续拆** | API 层失控完成 | 5 天 |
| **W6** | **H1 hot path useMutation 迁移(目标 28→80)+ H5 React.memo 重建(0→20)+ H2 graph-viewer/force-graph-3d 类型** | 前端治理 | 5 天 |
| **W7** | **C9 endpoint docstring 补 100 个(ruff D102)+ H10 Pydantic v2 codemod(11→0)+ H8 f-string SQL bandit(20→0)** | 代码质量 | 5 天 |
| **W8** | **H17 三个零测试 service 补 happy path + M10 requirements 完成拆分** | 测试 + CI | 5 天 |
| 后续 | H7/H14 等持续治理 | 每月 1-2 项 |

---

## 验证方式

```bash
# 异常治理(应 = 0)
grep -rn "except:.*pass\|except Exception:.*pass" app/ --include="*.py" | wc -l

# 大文件(应 < 5000 / < 3000)
find app/api/v1 -name "*.py" | xargs wc -l | sort -rn | head -5
find web/components web/app -name "*.tsx" | xargs wc -l | sort -rn | head -10

# DB 索引(应非空)
psql -c "\d+ documents" | grep "Indexes:"
python - <<'PY'
import pathlib, re
model_names = []
for path in pathlib.Path("app/models").glob("*.py"):
    model_names.extend(re.findall(r'Index\\("([^"]+)"', path.read_text()))
all_text = "\\n".join(path.read_text() for path in pathlib.Path("alembic/versions").glob("*.py"))
print([name for name in sorted(set(model_names)) if name not in all_text])
PY  # 应输出 []

# 类型治理(应下降)
cd web && grep -rn ": any\b" --exclude-dir=node_modules . | wc -l

# React 治理
cd web && grep -rn "React.memo\|memo(" --include="*.tsx" | wc -l  # 应 > 0
cd web && grep -rn "useMutation" --include="*.ts" --include="*.tsx" | wc -l  # 目标 > 100

# 仓库瘦身
git ls-files | xargs -I{} ls -la {} 2>/dev/null | awk '$5 > 5242880 {print $9}' | wc -l  # 应 = 0
git ls-files | grep "\.onnx$" | wc -l  # 应 = 0(走 lfs 或运行时)
ls *.png 2>/dev/null | wc -l  # 应 = 0(仓库根)

# e2e tests
find web -name "*.e2e.*" -not -path "*/node_modules/*" | wc -l  # 应 ≥ 4

# CI gate
gh workflow list && grep "on:" .github/workflows/lint-fast.yml  # 应存在

# docstring(应上升)
grep -rPzo "(?s)def [^:]+:\s*\n\s*\"\"\"" app/ --include="*.py" | wc -l
```

---

## 与既有 30+ 份 plan 的关系(更新)

**已完成的工作**(本次扫描发现并验证):
- 🎉 `web/lib/api/` 拆分(documents.ts 715 / datasets.ts 614 等)— batch-2 已落地
- 🎉 `app/api/v1/documents.py` 拆出 23 个 `document_*.py` 子文件,并抽出 `document_preview_utils.py`,主文件压到 2235 行且 `@router.* = 0`
- 🎉 `app/api/v1/connectors.py` 已拆出 20 个 `connectors_*.py` 子文件/模块
- 🎉 ESLint v9 flat config + Sentry + OTel 已就绪
- 🎉 `app/core/sentry.py` `app/core/otel.py` 已存在
- 🎉 ci/ 20 个 .v1.json 评测/性能基线
- 🎉 **本轮新增确认**:`except: pass` 全清(418→0)/ print() 全清(28→0)/ logger 入口统一 / CI gate 已加 / i18n 拆分完成 / openapi 单源收敛 / `.env.example` 大幅瘦身 / `datetime.now()` 裸调用清零 / `key={index}` 清零 / TS target 升 `ES2022` / `lint-fast.yml` 已补 / monaco public 入仓风险关闭

**仍需注意的倒退**(本轮新增):
- 🔴 `similarity-workbench.tsx` 2744 → 3425(+25%)
- 🔴 `quarantine/page.tsx` 2115 → 2720(+29%)
- 🔴 `chat_runtime.py` + `chat_bootstrap_runtime.py` + `chat_persistence.py` + `chat_turn_persistence.py` + `chat_stream_persistence.py` + `chat_memory_runtime.py` + `chat_cache_runtime.py` + `chat_execution_runtime.py` + `chat_stream_{orchestrator,common,graph,langchain}.py` 合计仍很大,chat service 还没继续细拆

---

## Critical 文件参考路径(更新)

```
# 异常治理(已完成)
✅ except: pass = 0

# API 层失控
app/api/v1/documents.py             # 2235 行,router 主块已收敛为 compat/helper surface
app/api/v1/connectors.py            # 523 行,继续拆 residual helper/service 化
app/api/v1/chat.py                  # 494 行,router 已显著收口
app/services/chat_runtime.py        # 140 行,thin compatibility layer
app/services/chat_bootstrap_runtime.py # 436 行,request/session/runtime bootstrap
app/services/chat_persistence.py    # 125 行,non-stream finalize/cache resolve
app/services/chat_turn_persistence.py # 146 行,non-stream turn persistence + summary update
app/services/chat_stream_persistence.py # 286 行,stream persistence
app/services/chat_memory_runtime.py # 142 行,long-term/structured memory + conversation touch helper
app/services/chat_cache_runtime.py  # 286 行,cache/singleflight bootstrap
app/services/chat_execution_runtime.py # 300 行,non-stream graph/langchain execution
app/services/chat_stream_orchestrator.py  # 292 行,stream 顶层分发
app/services/chat_stream_common.py        # 176 行,stream 收尾/缓存共用
app/services/chat_stream_graph.py         # 330 行,graph 流式链路
app/services/chat_stream_langchain.py     # 293 行,langchain 流式链路
app/services/{documents,connectors,chat}/  # 目标目录

# DB 索引(部分完成)
✅ app/models/*.py 已 16 处 sa.Index
🟡 先做实例级索引落库校验;当前 model-index 名称与 Alembic 文件差集为 0

# 仓库治理(未完成)
🟡 .gitattributes                   # 已加 *.onnx filter=lfs,待实际迁移现存二进制
✅ app/resources/data_parser/qieci/ # 未引用重复目录已删
✅ web/.playwright-mcp/*.png        # 已取消 git 跟踪
✅ 根目录 chunk-preview-*.png / graph-snapshots-*.png  # 已清理

# CI/CD
✅ ci.yml 已加 pull_request + push:main
✅ .github/workflows/lint-fast.yml  # PR/push/main fast lane 已补

# 安全
✅ web/next.config.mjs              # 已补 headers() 基础安全头
✅ app/api/v1/settings.py           # api_base 默认值已统一走 settings.LLM_API_BASE

# 配置
✅ web/tsconfig.json                # target 已从 ES2017 升 ES2022
🟡 .env.example                     # 53KB → 3.3KB,未拆 .{db,llm,milvus,...}
🟡 requirements-dev.txt             # 已有,缺 requirements-runtime.txt

# 大文件倒退治理
🔴 web/components/ragviz/similarity-workbench.tsx  # 3425 行(↑)
🔴 web/app/knowledge/quarantine/page.tsx           # 2720 行(↑)
🔴 app/services/chat_runtime.py + chat_bootstrap_runtime.py + chat_persistence.py + chat_turn_persistence.py + chat_stream_persistence.py + chat_memory_runtime.py + chat_cache_runtime.py + chat_execution_runtime.py + chat_stream_{orchestrator,common,graph,langchain}.py  # chat service 仍过长

# e2e 重建
🟡 web/e2e/*.spec.ts                 # 已恢复 6 个 spec,但业务覆盖仍偏薄
```
