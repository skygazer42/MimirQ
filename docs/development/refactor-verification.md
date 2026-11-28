# 重构验证入口

总计划：`docs/superpowers/plans/2026-10-27-repository-maintainability.md`。逐项结果及裁定记录在对应 ledger。

## 本地工具

Windows 使用已安装的 `.venv/Scripts/python.exe` 和 `web/node_modules`，避免包管理器因版本不匹配自动下载安装。以下命令只读检查，不启动模型、解析器或完整容器栈。

仓库根目录：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_source_guard_contracts.py tests/test_route_auth_contracts.py
.venv/Scripts/python.exe scripts/check_module_boundaries.py
.venv/Scripts/python.exe -m pytest -q tests/test_module_boundaries.py
.venv/Scripts/python.exe -m ruff check app tests scripts main.py
```

`web` 目录：

```powershell
node node_modules/vitest/vitest.mjs run source.test entry.test lib/source-test-utils.test.ts app/usage/usage-model.test.ts app/usage/usage-pagination.test.ts --maxWorkers=2
node node_modules/typescript/bin/tsc --noEmit --incremental false
node node_modules/eslint/bin/eslint.js .
node --test scripts/check-feature-boundaries.test.mjs
node scripts/check-feature-boundaries.mjs
```

源码检查约束实际所有者与结构；不能代替浏览器交互验证。JSX、配置和 CSS 源码约束通过 TypeScript/PostCSS 解析，避免依赖引号、空格或已退休的同文件常量。

## B01 基线

- 全仓覆盖表：`artifacts/refactor/repository-plan-v1/B01/coverage.csv` 和 `coverage.json`，4,845 个文件全部映射到计划；映射不代表逐文件重构完成。
- 后端 source/route：126 passed。
- 前端 source/entry、源码解析工具及用量模型/分页：104 passed，37 个文件；原始结果见 `B01/frontend-final.json`。
- TypeScript 与本批测试文件 ESLint 通过。仅检查测试契约，产品界面没有改动，未重新执行浏览器流程。
- 原始失败基线、修改前源码和各项判断见 `B01/frontend-baseline.json`、`B01/before/`、`B01/frontend-triage.md`。

过期约束包括已经移出的知识库 TabKey、Settings 验证器职责、身份工具弹窗、共享健康/画像工作区、预检 CSS、评测样本矩阵及用量 A 概览。保留现有权限、分页、失败状态、滚动和扁平表面契约；没有恢复已退休的 Ocean 页面来迎合测试。

真实服务与浏览器验证按后续业务任务执行并留证；以上基线不代表完整业务流程已通过。

## 依赖检查

Python检查静态、延迟及字面动态的路由反向引用和不透明模块/服务参数；前端检查纯model的实际运行时依赖，包含中转导出和动态import。视图迁移后登记在 `web/scripts/feature-boundaries.json`，约束请求与持久化归属。

迁移清单在 `ci/module-boundary-baseline.json` 和 `web/scripts/feature-boundary-baseline.json`，每条记录带精确目标、数量及任务。新依赖报错，删除依赖后必须同步删除记录；不能用追加整文件豁免使检查通过。`--inventory`只输出发现，不修改清单。

本地 `make verify`、`scripts/verify.ps1`、web verify已经包含检查；现有CI通过 `make verify`执行。Python正反例、CI/Makefile契约合计57 passed，前端6个Node fixtures通过。B02初始发现清单保存在对应阶段目录。

## A02 单文件、URL 与 HTML 入库

- `app/services/document_ingestion.py` 是具名 `ingest_file`、`ingest_url`、`ingest_html` 操作owner；pipeline/rule解析、源下载与写入、数据库/对象源持久化各由对应服务负责。HTTP表单 schema字段和 OpenAPI保持原契约。
- A02完整回归39文件：404 passed、5 integration skipped；`artifacts/refactor/repository-plan-v1/A02/document-regression.log` 和 XML是原始输出。
- A02 OpenAPI：51 paths / 57 operations，与阶段前JSON逐字段相等；同一阶段的模块边界151项中无新增边，已完成A02边已从migration baseline移除。
- Ruff和相关模块compileall通过；真实数据库集成未启用，故5项依赖其环境的用例保留skip。

## A03 批量入库与预检

- `app/services/document_batch_ingestion.py`拥有批量操作、并发处理、来源暂存、预检、去重、独立item持久化和run收尾；HTTP路由只解析请求并调用服务。
- 完整文档/上传组39文件：404 passed、5 integration skipped；原始日志为`artifacts/refactor/repository-plan-v1/A03/document-regression.log`，JUnit为同目录XML。
- 批量/并发/会话聚焦回归11 passed，覆盖取消清理、两条intake路径、duplicate pipeline identity、item session隔离及线程内创建和关闭。
- 模块边界141条已登记迁移依赖、无新增；批量服务不接收整块API模块。OpenAPI 51 paths / 57 operations，Ruff与compileall通过。

## A04 用户元数据、pipeline 与 QA

- `document_user_metadata.apply_user_metadata_patch` 是上传、批量和单条修改共用的规则owner；`document_metadata_operations` 持有pipeline与user metadata操作，`document_qa_service.generate_document_qa` 持有授权后的QA完整操作。
- `document_mutations.py` 的三个handler只转发请求；pending可重处理策略来自A01，hash计算直接使用 `document_identity`，ACL直接使用 `document_access_service`。
- 9个相关测试文件99 passed；日志与JUnit在 `artifacts/refactor/repository-plan-v1/A04/document-regression.log` 和 `.xml`。覆盖显式pipeline字段、replace/null/tag/notes语义、pending/processing冲突、QA service委托和未分配文档ACL。
- Documents OpenAPI仍为51 paths / 57 operations / 92 schemas，与A03快照逐字段相同；A04前记录的 `_documents_module` 依赖删除后，Python模块边界从141条变为140条，无新增依赖。Ruff与相关模块compileall通过。

## A05 手工文档与预览图片

- `app/services/document_manual_ingestion.py` 拥有manual文档写入、后台worker/session、Indexer、KG加工和失败状态；`app/services/document_preview_utils.py` 拥有preview图片归属认领及MinIO改写。
- `document_manual.py` 的handler只调用manual操作；业务不再从 `documents.py` 聚合器找Dataset、pipeline、KG或图片函数。图片归属失败仍fail closed，MinIO关闭时保留本地preview引用并先完成归属升级。
- Manual服务、路由、图片复用聚焦12 passed；日志/JUnit在 `artifacts/refactor/repository-plan-v1/A05/manual-focused.log` 与 `.xml`。扩展组合90 passed、1 skipped，完整解析器前向测试因本地缺少 `trio` 与 `torch` 被排除；日志/JUnit在A05 `document-regression-final.log` 和 `.xml`。
- Documents OpenAPI 51 paths / 57 operations与A04逐字段相同；迁移baseline移除manual路由5条旧边后为135条、无新增依赖。Ruff和相关模块compileall通过。

## A06 资产身份、授权与传输

- `app/api/dependencies/document_assets.py` 解析资产请求actor，verified JWT tenant优先，并拒绝header/query或image-url embedded tenant冲突；`app/services/document_asset_access.py` 授权文档、preview sidecar和legacy精确引用。
- `document_assets.py` 的下载/图片handler调用身份与授权owner；Range/416、ETag、FileResponse/StreamingResponse、content disposition和no-store保持HTTP层职责。
- 资产身份、ACL、legacy sidecar、下载/图片Range与route auth回归63 passed；日志/JUnit在 `artifacts/refactor/repository-plan-v1/A06/document-regression.log` 和 `.xml`。documents OpenAPI保持51 paths / 57 operations / 92 schemas，与A05逐字段相同。
- Python模块边界移除资产API到documents aggregator的12条旧边，登记总数从135降为123，无新增依赖；Ruff与相关模块compileall通过。

## A07 批量操作与生命周期

- `app/services/document_batch_operations.py` 拥有批量user metadata、retry、reingest、ACL更新和move；retry/reingest调用A01状态操作，reingest调用A04 pipeline操作，ACL批量/单条复用 `document_access_service.update_access`。
- `app/services/document_lifecycle_service.py` 拥有四种批量状态变化和批量删除；删除仍逐项经过共享删除操作。HTTP路由保留原request/response模型与逐项结果分类。
- 8个相关测试文件67 passed；日志/JUnit在 `artifacts/refactor/repository-plan-v1/A07/document-regression.log` 和 `.xml`。documents OpenAPI仍为51 paths / 57 operations / 92 schemas，与A06快照逐字段相同。
- Python模块边界删除 `document_batches.py` 与 `document_batches_lifecycle.py` 到documents aggregator的2条旧边，baseline为121条且无新增；Ruff与相关模块compileall通过。

## A08 Connector 执行与 ACL

- 八种 source runner 由 `app/services/connector_execution/` 直接持有，统一暴露 `execute(*, run_id, tenant_id, requested_by)`；`app/services/connector_run_executor.py` 对 connector ID 显式映射，未知 ID 仍返回 `False`。
- `app/services/connector_document_access.py` 拥有 ACL 应用、source identity delta sync 和缺失 source reconciliation；显式 source ACL group mappings 复用 `connector_source_acl_mapping`，未配置 mappings 时沿用既有 tenant-group `external_id` 路径。
- Connector runner/config/ACL/web crawl 组合68 passed；原始输出/JUnit在 `artifacts/refactor/repository-plan-v1/A08/connector-regression-final.log` 和 `.xml`。包含阻断 `app.api.v1.connectors*` 后导入服务执行模块的子进程契约。
- 原 14 个 connectors API 执行/helper 模块已移除，`connectors.py` 保留 route assembly 与旧导出兼容。模块边界删除19条A08执行反向依赖，baseline为102条、无新增；Ruff与compileall通过。`defusedxml==0.7.1` 已声明，因为现有 `web_crawler` 在服务运行时直接导入该包。

## A09 Connector run/config/schedule

- `app/services/connector_run_operations.py` 拥有 run 创建、查询、retry、resume、cancel、pending 持久化和队列 handoff；执行器直接使用 A08 的 service dispatcher。队列 handoff 丢失或抛错时仍将 run 标记 failed、清除 task id 并返回 503；DB connector 的 egress、admin 与 group 校验留在业务操作内。
- `app/services/connector_config_operations.py` 拥有 saved config CRUD、run 和 reconcile；registry、reconcile 与 state snapshot 使用各自 service owner。run 完成后的 saved-state sync 继续由 runner 已用的 `connector_execution.shared.runtime` 提供，避免复制第二套更新逻辑。`app/services/connector_schedule_operations.py` 拥有 tick、due 判断、claim、run 创建和失败释放；同窗口 claim 只允许一个 run，queue 失败恢复 `last_run_at` 并保留错误标记。
- `connectors_runs.py`、`connectors_configs.py`、`connectors_schedules.py` 只负责 HTTP 依赖与响应；`connectors_state.py` 仅重导出对应 service 符号，不再依赖 `_leader_module`。run/config 响应在没有 API facade 初始化时也会对 DB 连接字段脱敏。
- Connector 执行、队列、schedule、配置隔离、DB egress/auth、run/config ACL 分页组合 45 passed；原始输出/JUnit 在 `artifacts/refactor/repository-plan-v1/A09/connector-regression-final.log` 和 `.xml`。`tests/test_module_boundaries.py` 19 passed；`scripts/check_module_boundaries.py` 报告 92 条既有迁移边、无新增或过期项。Ruff 与相关模块 compileall 通过。
- Router-only OpenAPI assembly 当前生成 12 个 connector paths / 15 operations；已有 A07 snapshot 不包含 connector paths，`app.main` 完整 schema 的导入在 30 秒内未返回，因此不记录与历史 OpenAPI 相等结论。
- 更广的 source guard 与 route auth 组合中 125 passed、1 failed：`test_fastapi_sync_db_routes_do_not_run_on_event_loop` 指向未由 A09 修改的 `app/api/v1/document_batches.py:110`。

## A10 Dify 契约、鉴权与 conversation turns

- `app/types/dify_integration.py` 持有 `DifyActor` 和 KG flags，并显式发布 integrations 领域的 request/response；请求与响应由 `app/api/schemas/integrations` 定义。`external_api.py` 与 `integrations_dify.py` 引用同一对象。实际 HTTP 鉴权依赖由 `external_api.py::_require_dify_actor` 持有，服务 auth 模块提供四个真实共享的 token／UUID 函数；未接入的重复 authenticate_actor 服务入口退出。生产 tenant 必需、非生产 header/default tenant、token digest 和缺账号503规则保持，不将旧服务的空账号兜底带入 HTTP。
- `app/services/dify_integration/conversation_turns.py` 拥有 source-scope advisory lock、conversation owner/source 校验、trace seed 创建、turn/seed 幂等复用和 result trace。API adapter 和 `external_api.py` 不再回查 `integrations_dify.py`；`external_conversation_ingest` 将 schema import 延迟到 HTTP response 构造处，因此共享 citation cleaner 可在服务包独立导入。
- Dify owner/import-boundary 与 module-boundary 用例 26 passed；鉴权、conversation lock/owner/source、幂等 turn、route adapter 聚焦回归 15 passed；`tests/test_external_conversation_ingest.py` 11 passed。完整 adapter suite 246 passed、3 failed，原始日志/JUnit 在 `artifacts/refactor/repository-plan-v1/A10/dify-regression-final.log` 和 `.xml`。Ruff、compileall 通过；模块边界检查 91 条、无新增或过期项。
- 完整 adapter suite 的失败为 `test_dify_apply_policy_fallback_candidate_multiplier_uses_default_when_setting_is_invalid`（由 A11 policy helper 承接）以及两个 singleflight 测试连接本地 `localhost:6379` 超时；Redis 未在当前最小本地服务中运行。

## A11 Dify 知识范围与插件策略

- `knowledge_scope.py` 拥有知识映射、继承 routes、strict scope、生产 direct UUID 限制、warmup IDs 和 sibling policy scope；`policy_helpers.py` 直接使用 plugin/planner，API 不再为策略 helper 注入 resolver。剩余 API record 算法也直接调用实际 policy owner，测试统一替换该 owner。
- Common/scoring/query terms 纯规则归到 service；specific-service sibling gate 保留原 min length、candidate 数及 noise/cutoff/admin/segment 规则。当前 pipeline 模型与校验器由 `app/api/schemas/documents/models.py` 持有，领域包发布该对象；没有生产调用的旧 types 副本退出，见[未使用的检索与管线副本](../../.agents/notes/implemented/simplification/2026-11-13-retire-unused-retrieval-copies.md)。下列 A11 验证记录保留当时的源码版本与结果，不代表当前重新执行。ACL helpers 仍由原 schema 持有。
- Dify adapter 247 passed、2 failed，原始日志/JUnit 在 `A11/dify-regression-owner.log` 和 `.xml`；两项失败仍是本地 Redis 等待，A15 承接。共享 pipeline、plugin、ACL、独立 service import 和 module boundary 组合 80 passed，见 `A11/shared-contract-regression.log` / `.xml`。
- Dify OpenAPI 与 A11 前逐字段相等（2 paths / 2 operations）；pipeline schema、3 个样例 dump/字段集相等。证据为 `A11/dify-openapi-parity.json` 和 `pipeline-type-parity.json`。Ruff、format、compileall 与模块边界通过，baseline 仍为 91 条。

## A14 共享 evidence 操作与 RAG 契约

- 当前 API 与 Dify 从 `app/services/retrieval_requests.py` 调用共享 evidence 操作，范围与 ACL 交给 `app/services/retrieval_scope.py`。没有生产入口的旧 monolith 退出；Preview 与 explain 继续使用实际共享 helper。
- ChatRAGConfig 和 HistoryMessage 由 conversations/chat.py 持有，DatasetRAGDefaults 由 datasets/models.py 持有，evidence 请求／响应由 conversations/retrieval.py 持有，并通过所属领域包发布。三份未被生产调用的 types 副本退出。token bucket 与文档 ACL 仍分别归 `app/core/rate_limit.py` 和 `document_access.py`。下列 A14 测试／AST／边界检查均是历史版本的验证记录，当前逐文件整理未修改或运行 Python 测试，不能把历史结果视为副本仍在使用或当前测试通过的证据。
- 清理了已验证模型的 seed 重复转换和字段集兜底。数据库读取默认配置失败时原先被吞掉，现在抛出原异常；缺失配置和显式请求值的合法语义由聚焦测试验证。
- Dify adapter 249 passed；原始日志/JUnit 在 `A14/dify-regression-final.log` 和 `.xml`。此前两项 Redis 超时来自单元测试缺少现成 FakeRedis 接线，补上后，缓存发布/取消接管的原断言全部通过；没有启动 Redis。
- 共享检索/config/quota/session/ACL/profile/module-boundary 组合 146 passed，见 `A14/shared-regression-final.log` / `.xml`；补充默认值优先级后的 service 聚焦 14 passed，见 `service-regression-final.log` / `.xml`。隔离子进程阻断并记录 API import，在该约束下执行检索与真实内存 quota。
- API + Dify 的 9 paths / 9 operations OpenAPI 与迁移前相等；24 个迁移定义 AST 相等。证据为 `A14/contract-parity.json` 和 `owner-migration-parity.json`。Ruff、format、compileall 通过；模块边界清单由 91 降为 88，无新增或过期项。

## A07 后续验证

- 将直接调用同步 ACL 数据库操作的 `batch_update_document_access` 改为同步 FastAPI handler，避免在事件循环执行阻塞 SQL。
- Source guard、route auth、batch 操作和 reingest 组合 130 passed；源码快照、日志和 JUnit 在 `artifacts/refactor/repository-plan-v1/A07-followup/`。关闭了 A09 记录的同一 source guard 遗留失败。

## A12 Dify 记录加工

- `record_processing.finalize_records` 拥有去重、排序、protected final rerank、诊断、压缩和 fast context budget 的完整顺序；API 接收小型 typed result 的 validated records、ranked records 和 policy diagnostics。候选 top_k 与请求开始时确定的 response_top_k 分开传入，保持原有两个限制。
- 104 个 API 函数按实际依赖关系归到 query_policy、answer_hints、record_ranking、record_processing、citation_records 和 chunk_hydration；三个纯规则模块也归服务。删除 callback-driven record_helpers，42 种回调参数改为直接规则调用；测试替换实际所有者，保留原行为断言。
- 94 个函数恢复原实现和注释，144 个迁移/静态绑定后的定义与生成契约 AST 一致，17 个常量归 common 单一维护点。证据为 `A12/algorithm-parity.json`、`refinement-proof.json` 与生成输入快照。
- Dify adapter、record helper/operation、scope/owner/import/module boundary 组合 288 passed，日志/JUnit 为 `A12/dify-regression-final.log` 和 `.xml`；source guard/route auth 126 passed，见 `source-route-regression.log` / `.xml`。含禁止任何 API import 后实际执行 finalize 的子进程回归。
- API + Dify OpenAPI 与阶段前保持相等（9 paths / 9 operations），见 `A12/openapi-parity.json`。Ruff、format、compileall 和边界检查通过，baseline 仍为 88 条；没有启动外部服务。

## A13 Metadata-anchor 数据库回退

- `metadata_anchor.find_anchor_records` 持有原 tenant/dataset/document 资格条件、slot/question/service 候选顺序和 statement timeout/rollback。`run_with_deadline` 与私有 worker 持有排队计时、总 deadline 和 session 创建/关闭；请求共享 spent-time 聚合留在检索编排，随 A16 迁移。服务不接收 API context 或模块。
- 49 个 DB/预算/会话定义与迁移契约 AST 一致；scope、metadata 和检索共用 common 的 UUID 顺序去重，6 个 list/tuple/重复值样例与原两个实现等价。证据为 `A13/contract-parity.json`。
- Dify adapter、record/metadata operation、owner/scope/import/module-boundary 组合 292 passed，日志/JUnit 为 `A13/dify-regression-final.log` 和 `.xml`；source guard/route auth 126 passed，见 `source-route-regression.log` / `.xml`。覆盖 statement timeout 回滚、remaining statement budget、排队等待计入总预算、文档资格、空 scope、过期 deadline 和独立 worker session。
- API + Dify 的 9 paths / 9 operations OpenAPI 不变；隔离子进程禁止并记录 API import 后仍可执行服务。Ruff、format、compileall 与模块边界检查通过，baseline 仍为 88 条。

## A15 Dify 缓存与 singleflight

- `response_cache.get_or_compute_response` 拥有 memory/Redis cache、local/distributed flight、lease heartbeat、结果发布、异常/取消和清理。输入为 key、compute 与不可变 cache policy，返回 records/source/timings；服务不接收 API context，检索在发布后写原有结果和 trace。
- 收回 8 个 cache/lease context 字段。Corpus token 复用现有 `corpus_cache_tokens` 服务，覆盖 embedding binding 与 indexer 更新的 dataset revision；删除重复 timestamp serializer。Actor/scope/metadata 校验仍先于缓存。
- 修复损坏 Redis records 被过滤成空或不完整成功结果的问题：整个损坏 snapshot 作为 cache miss，日志不输出缓存内容；合法空结果仍命中。分布式等待在 compute 前失败也会释放本地 flight，避免后续请求遗留等待。
- 保留 local result → memory/Redis 的发布顺序、跨实例复用、TTL=0 transient result、取消接管、等待超时不取消 leader future、lease release。Leader recheck 命中统一记录为 cache_hit；lease 清理在外层 trace 前完成，因此 elapsed 会包含该清理时间；裁定详见 API ledger。
- Dify/record/metadata/cache/owner/scope/import/module-boundary 组合 301 passed，日志/JUnit 为 `A15/dify-regression-final.log` 和 `.xml`；source guard/route auth 126 passed，见 `source-route-regression.log` / `.xml`。Cache 聚焦与 import boundary 11 passed，包含禁止 API import 的实际执行。
- API + Dify OpenAPI 9 paths / 9 operations 不变，16 个 cache 定义 AST 不变；其余明确变化记录在 `A15/contract-parity.json`。Ruff、format、compileall 和边界检查通过，baseline 仍为 88 条。Redis 验证使用协议替身，没有启动服务。

## A16 Dify 检索、warmup 与 HTTP 收束

- `retrieval.retrieve_knowledge` 持有私有执行 context 和原 preflight → primary → mixed intent → KG → expansion → fallback 顺序；`warmup` 持有状态、调度与 startup loop；KG、evidence 参数映射、request preferences 和 tracing 各自归实际服务。接口只接收 typed body/actor、headers、request id、client ip 与 Session，HTTP Request 留在 adapter。
- `integrations_dify.py` 只保留 6 个 HTTP 定义及旧类型的同对象别名；startup/health 直接使用 warmup。规范化 string/UUID/header/hash 和引用字段白名单由 common 单点维护，纯 scoring 不再持有 HTTP client 解析。
- Dify/record/metadata/cache/retrieval/owner/scope/import/module-boundary 组合 307 passed，日志/JUnit 为 `A16/dify-regression-final.log` 和 `.xml`；startup/health/source/route 组合 152 passed，见 `startup-health-source.log` / `.xml`；worker/admission/权限/启动关闭顺序相关 43 passed，见 `related-regression-final.log` / `.xml`。
- 实际检索与 disabled warmup 在禁止 API import 的子进程中执行；Dify evidence 仍保持 membership/quota/scope 拒绝结果。API + Dify OpenAPI 9/9 不变，73 个业务定义匹配迁移契约，见 `A16/contract-parity.json`。
- Ruff、format、compileall 与边界检查通过；移除 startup/health 的 3 条旧反向依赖，baseline 88 → 85。API 分计划完成，RAG/解析/索引/配置、其余后端、前端与最终覆盖检查继续按总计划执行。

## R01 Engine helper 与公开检索契约

- Engine 的四个 KG helper 直接导入 `kg_merge_boost` 实现所有者，保留现有函数别名和对象身份；engine/orchestrator 两种导入顺序均验证，真实 TYPE_CHECKING 分支不计入运行时依赖。
- 固定无需检索、普通命中、部分通道失败、must-recall 失败、strict parse-quality abstention 五类公开结果。新增实际低质量文档用例，改前/改后 keys、数据形状、状态、失败原因与 trace schema 相等，见 `R01/public-contracts-before.json`、`public-contracts-after.json`、`contract-parity.json`。
- Dependency、engine stream、orchestrator、contract 与 trace 组合 30 passed，日志/JUnit 为 `R01/rag-regression-final.log` 和 `.xml`；五类 characterization 改前/改后各 5 passed。流式单元测试在实际工厂入口使用本地 fake model，原事件顺序、超时与取消断言保持不变；没有使用外部凭据或启动模型服务。
- Ruff、compileall 与模块边界检查通过，baseline 仍为 85 条。

## R02 共享 corpus 与派生索引

- `CorpusIndex` 是写入、BM25、sparse、ColBERT 共用的 corpus 所有者；Indexer 不再导入 Retriever，读端不再持有第二套索引缓存。显式不可变 scope 和每次调用返回的 status 保留租户、dataset、document 隔离及请求诊断隔离。
- 已验证真实内存 upsert/search/delete、tenant/multi-dataset 视图更新、eager/deferred 限制、原事务 session、重建上限和派生索引同步。修复内容替换时 fingerprint 漏失、sparse provider 配置混用、完整删除/文档失效/reset 的残留缓存，以及 sparse 写入修改进行中查询快照的问题；各缺陷均先复现失败。
- 最终组合 587 passed，原始日志/JUnit 为 `artifacts/refactor/repository-plan-v1/R02/combined-regression-final.log` 和 `.xml`。五种公开检索结果与 R01 改前快照相等，见 `R02/contract-parity.json`。Ruff、format、compileall、scoped diff 和模块边界通过，仍为 85 条已登记迁移边。
- 保留真实输入/权限/事务及既有可选通道降级；数据库 streaming 错误直接抛出，不再以无界读取兜底。测试没有启动模型、解析器、Redis 或完整容器栈；真实部署验证仍由 S03 承接。下一项为 R03 chunk/event/vector 写入与清理操作。

## R03 索引写入与失败清理

- `app/services/indexing/` 的 ChunkIndexer、EventIndexer、ChunkVectorWriter 各自持有完整操作；准备规则、quota 与 channel tracking 分别归实际共享位置。Indexer 保留 20 个既有公开方法签名；QA、chunk、audit 通过公开 corpus 同步入口调用，embedding migration 与手工 KG 不再读取其私有实现。
- 小型 typed context/flags 替代内部字典；清理已确定类型上的 getattr/hasattr 和无调用者兼容 helper。查文档/数据集失败明确报错，不再选择默认向量空间。数据库写入失败、默认向量批次中途失败均精确清理本次 chunk，保留旧 pipeline 并抛出原异常；调用方的 commit=False、Session 与原 channel 顺序保持。
- 最终组合 792 passed、3 integration skipped，日志/JUnit 为 `artifacts/refactor/repository-plan-v1/R03/combined-regression-final.log` 和 `.xml`；手工 KG 调用方另有 2 passed。类型/接口与算法证据为 `operation-parity.json`：20 个签名相等，42 个函数和 42 个方法 body 经静态绑定后相等，其余 32 项明确列出变更原因。
- 五类公开检索结果与原快照相等，见 `R03/contract-parity.json`。Ruff、format、compileall、scoped diff 与模块边界通过，登记依赖仍为 85 条。未启用的 3 项真实数据库集成测试保留 skip；全局独立审查仍由 S03 承接。下一项 R04 的 5 组基线 48 passed。

## R04 检索范围阶段（R04 整项仍在执行）

- `hybrid/runtime_scope.py` 持有不可变的请求身份、解析后的运行时范围和 shard；统一文档归属、embedding 分组与过滤条件。检索器调用真实操作，删除原重复 loader 和无调用者的单 dataset 回退链；请求提供的 Session 由调用方持有。
- 保留原运行时覆盖准入检查，并用混合 legacy/unscoped 文档用例复现迁移遗漏后修复。另修复写 Session 的未提交版本进入共享 token 缓存的问题：该结果只返回写入调用方，独立读取的版本才进入跨请求缓存；测试确认原 Session 不被关闭。
- 最终 44 文件组合 853 passed、3 integration skipped，日志/JUnit 为 `artifacts/refactor/repository-plan-v1/R04/scope-transaction-combined-final.log` 和 `.xml`。离线 evidence 门禁保留原 hit/recall=1.0 断言，测试替换点已迁到 CorpusIndex；五类公开检索结果与原快照相等、8 个公开 reader 签名保持，见 `R04/scope-contract-parity.json`。
- Ruff、format、compileall、scoped diff 与模块边界通过，仍为 85 条登记依赖。R04 的 candidate 操作、cache/lease 发布顺序和请求诊断状态归属继续执行；全仓计划未完成。

## R04 缓存与 lease 阶段（通道操作仍待迁移）

- CandidateRequest 和 CandidateCacheSession 持有单次请求的准入、版本、exact/semantic 命中、等待、发布和资源清理；读取器删除 13 个缓存辅助函数及重复控制字段。缓存层不再依赖隐式 current-request ContextVar，也不接收整个检索器或 Any context。
- 8 个独立用例验证发布顺序、错误与取消、follower 超时、账号隔离、命中限制、不完整 leader 的明确失败及禁止导入检索器后实际执行。实际全部 shard 超时仍返回原可重试错误；lease/future 清理归缓存对象。
- 45 文件组合 861 passed、3 integration skipped，原始日志/JUnit 为 `artifacts/refactor/repository-plan-v1/R04/cache-combined-final.log` 和 `.xml`；五类公开结果与原快照相等，见 `cache-contract-parity.json`。Ruff、format、compileall、scoped diff、85 条模块边界通过。
- R04 继续迁移通道、排序协调和每次调用的诊断结果，并消除重复 runtime 读取；总任务与全仓计划均未标完成。

## R04 向量执行阶段（其他通道仍待迁移）

- `hybrid/vector_search.py` 统一 default/dataset/shard 检索，返回各自结果、原始错误和 native hybrid 诊断。worker 不再写共享 `_last_channel_metrics`，普通检索与 keyword 回退共用实现。标记 expected-space 时复制 provider 记录，保留原数据。
- 原有并发、预算、稳定排序、部分/全部超时与 native fallback 测试迁到真实所有者；4 个新增用例覆盖并行诊断、原异常、无效 sparse 输出的可观察错误和禁止导入读取器后的实际执行。legacy native 诊断按请求 shard 顺序投影，完整诊断留在 typed batch。
- 最终 46 文件组合 865 passed、3 integration skipped，日志/JUnit 为 `artifacts/refactor/repository-plan-v1/R04/vector-combined-final.log` 和 `.xml`。五类公开结果与原快照相等，见 `vector-contract-parity.json`；Ruff、format、compileall、diff、85 条模块边界通过。
- R04 下一步处理其余通道、收集/排序及 CandidateBatch；全仓重构继续执行。

## R04 Sparse / ColBERT 查询阶段（lexical 与协调仍待迁移）

- `hybrid/corpus_channels.py` 直接使用共用 corpus/artifact owner，返回候选、当前调用诊断和原始异常。删除两个查询 mixin；sparse 状态只在完成后写入兼容诊断字段，ColBERT 诊断由当前调用投影。
- 先复现 sparse 构建异常被压成 True、ColBERT 异常被压成 None 的缺陷，再保留原异常交给通道处理层；失败不再记为成功空结果。真实读取器用例确认 sparse 不进入 successful_channels，正常向量空结果仍按原策略处理。
- 6 个查询 owner 用例和 14 个 artifact 用例通过，包含两租户状态隔离及禁止导入读取器后的实际执行。扩大 47 文件组合 872 passed、3 integration skipped，证据为 `artifacts/refactor/repository-plan-v1/R04/corpus-channels-combined-final.log` 和 `.xml`。五类公开结果相等，见 `corpus-channel-contract-parity.json`；Ruff/format/compileall/diff 和 85 条模块边界通过。
- R04 继续 lexical、通道收集/排序、CandidateBatch 及消除重复 runtime 读取；总计划仍未完成。

## R04 Lexical SQL 阶段（协调与排序仍待迁移）

- `metadata_scope.py` 统一外部 JSON 过滤器的 dataset/AND/OR 解析；`lexical_search.py` 接收显式 query/scope 与调用方 Session，返回候选、当前 pg_trgm fact 和原始异常。删除 LexicalDBMixin，Root 只持有会话适配与结果投影。
- SQL 故障不再伪装成空命中，也不再在失败事务内继续查询；真正零命中仍走原 plainto fallback。后续策略失败会保留已有命中并标记降级，扩展探测失败不再缓存为“不支持”。SQL 统一投影真实 dataset_id，错误行格式明确失败；会话不被操作提交、回滚或关闭。
- 7 个 owner 用例通过，覆盖 scope、fallback、原异常、部分结果、错误投影与禁止导入读取器后的实际执行；扩大 49 文件组合 890 passed、3 integration skipped，证据为 `artifacts/refactor/repository-plan-v1/R04/lexical-combined-final.log` 和 `.xml`。五类公开结果相等，见 `lexical-contract-parity.json`；Ruff/format/compileall/diff 与 85 条模块边界通过。
- R04 剩余通道收集/策略、排序、CandidateBatch 与重复 runtime 读取；完整目标继续执行。

## R04 通道收集阶段（排序与完整 candidate 操作仍待迁移）

- `hybrid/channel_collection.py` 持有完整的模式策略、召回顺序和既有降级路径，包括 ColPali 的 corpus scaffold。小型 vector/keyword/auxiliary 结果组合成 ChannelCollection，复用 HybridSearchOptions、HybridChannelResults 和 RetrievalChannelHealth；不传入整个 reader、模块或 Any callback context。
- 所有通道状态、原始异常、pg_trgm fact 和耗时归当前调用。BM25 诊断读取实际结果，ColPali 投影复制 provider 数据。仅在真正执行向量召回时解析其 backend；正常 keyword 命中不初始化无用依赖。SQL 会话由操作创建和关闭，事务提交边界保持。
- 原 reader 的通道调度 helper 和 ColPali scaffold 已删除，测试替换点迁到实际所有者。两个实际向量工厂消费者也改为直接依赖 storage 工厂。缺少 tenant 的 corpus 请求明确失败，不借用默认 tenant；可选通道失败和部分命中保留健康状态与原异常。
- 8 个 owner 用例通过，覆盖降级顺序、部分/全部超时、并发诊断、部分 lexical 命中、provider 数据不变、原异常及禁止 reader import 后的真实 corpus 执行。重点接入回归 91 passed；扩大 50 文件组合 **898 passed、3 integration skipped**，见 `artifacts/refactor/repository-plan-v1/R04/collection-combined-first.log` 和 `.xml`。
- 五类公开检索结果与原快照相等，见 `collection-contract-parity.json`；Ruff/format/compileall/diff 和 85 条模块边界通过。R04 仍需完成排序、CandidateBatch 与重复 runtime 读取清理，完整仓库计划未完成。

## R04 候选操作完成

- `retrieve_candidates → CandidateBatch` 统一准入、缓存、通道收集、排序与发布/清理。返回实际 runtime、候选、通道/cache outcome、原异常和耗时；检索器在完成边界投影旧诊断字段，主流程直接消费当前批次。缓存命中跳过召回和排序，普通异常仍由 adapter 原样抛出，取消仍触发原有 lease/future 清理。
- `rank_candidates` 组合明确的 fusion/dedup/diversity/rerank 参数，使用每次调用独立的算法实例并返回诊断。共享 metadata-anchor 排序归到 `metadata_ordering.py`；删除 reader 动态 state 协调、重排栈、重复调试兜底和无业务用途的 fusion 继承。原纯算法测试改为直接使用实际所有者。
- 已先复现并修复实际 runtime 双读：dataset 查询从 2 次减为 1 次，向量与 enrichment 使用同一 runtime 对象。并发 barrier 用例强制同一个 reader 的两个 candidate 批次先全部完成，再分别投影 debug；候选数量和文档仍各属本次调用。可选 reranker 故障保留候选、错误诊断及原异常。
- 最终 owner/runtime 组合 23 passed；扩大 **51 文件、909 passed、3 integration skipped**，见 `artifacts/refactor/repository-plan-v1/R04/candidate-combined-final.log` 和 `.xml`。五类公开结果、8 个公开 reader 签名及 3 个入口签名相等，见 `candidate-contract-parity.json`。Ruff/format/compileall/diff 和 85 条模块边界通过；逐项完成审计与源哈希见 `candidate-completion-audit.json`。
- R04 已勾选完成，下一项 R05 处理 query plan。未启用的真实数据库集成环境和全仓运行验证仍由 S03 承接；RAG 后续任务及其他目录重构继续执行，完整目标未完成。

## R05 查询准备阶段（完整 query plan 尚未完成）

- `query_contracts.py` 定义分组输入、策略配置和实际阶段结果；`query_planning.prepare_query` 持有 sparse 选择、改写、行业词扩展和时间意图分析。模型端口只暴露所需调用，业务操作不导入或接收整个 engine/orchestrator/reader；bootstrap 直接使用 typed result。
- 已先复现再修复非法改写数字被默认为 0、缺少必需模型被当成原查询成功返回的问题。必需配置失败明确抛出；可选模型超时、行业词和时间意图 sidecar 失败保留原异常及原有降级。无历史或禁用改写时不解析模型。适应性路由单元测试在实际模型工厂处使用本地 fake，避免初始化访问真实凭据，原业务断言保留。
- 9 个 owner/adapter 用例包含禁止导入 orchestrator、engine、reader 后的实际执行；接入组合 22 passed。扩大 **53 文件、920 passed、3 integration skipped**，见 `artifacts/refactor/repository-plan-v1/R05/preparation-combined-first.log` 和 `.xml`。五类公开结果相等，见 `preparation-contract-parity.json`；Ruff/format/compileall/diff 与 85 条模块边界通过。
- R05 仍需迁移 alias/dictionary/KG、多查询、HyDE、step-back 和 decomposition，并组合完整 QueryPlan/QueryVariant 与现有契约和预算。源哈希及未完成项见 `preparation-verification.json`；完整仓库目标继续执行。

## R05 别名、词典与 KG 扩展阶段（完整 query plan 仍在执行）

- `expand_deterministic_queries` 持有别名与词典扩展顺序、已有规则和数量限制，返回独立结果、耗时及原异常；词典故障仍保留别名结果。`kg_query_expansion.py` 持有明确的 tenant/account/document/dataset scope、KG 能力准入、排序、去重和查询限制。移除 orchestrator 的 6 个旧 KG facade/helper，扩展与证据注入使用同一个 typed KG read。
- 错误 KG 对象/实体格式不再伪装成健康空命中或被默认为权重 0；故障可观察，合法的其他响应字段仍可复用。另先复现并修复证据注入重复读取已拒绝响应的问题：现在只读取一次，并向后传递同一个异常对象。作用域、排除类型、稳定排序、上限、取消和现有循环调用语义保留。
- 18 个新增用例覆盖正向结果、故障、scope 准入、并发循环、取消及禁止上层模块导入后的实际执行。重点组合 32 passed；最终 **57 文件、946 passed、3 integration skipped**，见 `artifacts/refactor/repository-plan-v1/R05/expansion-combined-final.log` 和 `.xml`。五类公开结果相等，见 `expansion-contract-parity.json`；Ruff/format/compileall/diff 和 85 条模块边界通过。
- 独立 owner 测试仍可见原有 asyncio.get_event_loop 弃用提示，未隐瞒或改动其循环复用语义。R05 继续处理模型扩展策略和完整 QueryPlan；未完成项与源哈希见 `expansion-verification.json`，完整仓库目标保持执行。

## R05 同步模型扩展阶段（异步路径与完整 query plan 仍待完成）

- `model_query_expansion.py` 统一多查询、HyDE、step-back 和问题分解，接收明确配置与模型端口，返回独立结果、解析状态、耗时和原异常。删除调度器 11 个旧 helper/phase 及列表/元组补丁兼容分支；输入门槛、上限、实验开关、关键词模式与启发式降级保持明确。
- 非字符串模型数组项成为可观察的输出契约故障；有效空数组保持原意，不强行用启发式替换。已先复现并修复共享启发式工具在截断后产生重复问题的缺陷。并发结果、实际模型适配器、查询调用顺序及禁止导入上层模块后的执行均有验证；固定私有 phase 名称的测试改为实际早退行为。
- owner/分解组合 25 passed；最终 **58 文件、968 passed、3 integration skipped**，见 `artifacts/refactor/repository-plan-v1/R05/model-combined-final.log` 和 `.xml`。五类公开结果相等，见 `model-contract-parity.json`；Ruff/format/compileall/diff 和 85 条模块边界通过。
- 标准流式路径仍有实际使用的异步实现和重复 parser，R05 下一步会复用这些规则并保留原生异步取消与模型选择，再组合完整 QueryPlan。源哈希、剩余消费者与未完成项见 `model-verification.json` 和 `remaining-query-plan-consumers.json`；完整目标继续执行。

## R05 原生异步复用阶段（最终 QueryPlan 仍在执行）

- JSON 解析合并到轻量的 `core/json_text.py`，原有两个入口为同一函数别名，6 个实现与原 core AST 相等。同步/异步策略共享门槛、解析、裁剪、排序、结果与降级规则；异步直接 await SDK 调用，取消和必需模型故障继续传播。
- 标准流式查询、纠错查询和 KG 后续消费者已接到实际所有者，查询阶段不再通过整个 engine 模块查函数。SDK 绑定与默认参数各保留一个维护点，并验证 fast/已选 LLM/default 选择顺序。合法空 KG 响应及已拒绝响应均不会被重复读取，原异常保持可观察。
- parser/策略/准备组合 52 passed，异步 KG/查询组合 34 passed，标准 owner/纠错文件 4 passed，重点接入组合 45 passed。最终 **62 文件、1000 passed、3 integration skipped**，见 `artifacts/refactor/repository-plan-v1/R05/async-combined-first.log` 和 `.xml`。五类公开结果保持一致，见 `async-contract-parity.json`；23 文件 Ruff/format、compileall/diff 和 85 条模块边界通过。
- `async-verification.json` 留存源哈希和未完成项。R05 接下来组合完整 QueryPlan/QueryVariant、契约与预算，并继续统一剩余 preparation/setup/routing 装配；全仓任务尚未完成。

## R05 完整 QueryPlan（已完成；全仓仍在执行）

- 同步与原生异步入口消费同一个 QueryPlan 结构，组合实际准备、路由、别名/词典、KG、模型策略与既有预算结果。标准流式路径保留 rewrite 事件交接、召回分类、profile/复杂度顺序和 MQ 优先级，删除重复查询列表装配与旧 contract support 模块。
- 已复现并修复通道预算未落到 retriever、非法预算被默认为无限制、分解链绕过已筛选预算，以及标准流式稀疏字段名与实际 retriever 不一致的问题。必需配置/模型故障及取消继续传播；现有可选降级保持可观察。
- 最终 **67 文件、1037 passed、3 integration skipped**，见 `artifacts/refactor/repository-plan-v1/R05/query-plan-combined-final.log` 和 `.xml`；33 文件 Ruff/format、compileall/diff 和 85 条模块边界通过。5 类公开结果与原快照相等；10 类标准流式路由结果除稀疏字段修复外一致。真实 HybridRetriever 的开关/provider 应用和查询计划消费均有验证。
- 完成审计与源哈希见 `query-plan-completion-audit.json`。R05 已完成，接下来 R06 处理融合/排序、证据完成、trace 与剩余运行时上下文；真实数据库集成和全仓最终运行验证仍待 S03。

## R06 查询结果融合（阶段已验证；R06 仍在执行）

- `candidate_ranking.py` 使用明确的 query/doc 分组和配置，返回融合文档、refill 池、家族排序与多查询配额结果；两个入口都已接入。删除重复的上下文分区、选择和填充函数，必需融合故障继续抛出，可选家族阶段保留候选与原异常。
- 新 owner 文件 13 项通过，覆盖真实排序、重复命中、配额、故障、并发隔离和禁止导入上层 runtime 后执行。与重构前真实函数比较，240 组主检索、120 组标准流式结果完全一致。
- 最终 **70 文件、1054 passed、3 integration skipped**，见 `artifacts/refactor/repository-plan-v1/R06/fusion-combined-final.log` 和 `.xml`；35 文件静态检查、compileall/diff 和 85 条模块边界通过，5 类公开结果相等。详情及哈希见 `fusion-verification.json`。
- 下一步继续迁移时间/层级/KG/post-rerank 排序、证据补全与 trace；R06 和全仓任务均未完成。

## R06 可读性纠偏（查询调用链已验证）

- 删除 189 行的 plan 回填函数，主入口改为直接的业务调用顺序，运行状态创建时就必须持有有效计划。流式入口也直接消费计划；重试仅更新当前有效的多查询结果，原计划保持不变。
- 清除 50 项流式结果映射、91 项重复 trace 参数、阶段注册表/通用调度器，以及只包装现有列表的 QueryCandidateBatch、QueryVariant。现有策略结果和模型调用接口继续按实际职责使用。
- 新用例覆盖禁止回填旧字段、原计划与重试结果隔离、有效空重试，以及实际流式入口从无证据到重试成功后的完成事件。最终 **71 文件、1060 passed、3 integration skipped**；38 文件静态检查、compileall/diff 和 85 条模块边界通过。5 类公开结果、10 类路由和 360 类融合结果一致。
- 证据见 `artifacts/refactor/repository-plan-v1/R06/readability-verification.json`。仍需处理实际执行/证据状态与 84 项 trace 输入；通过测试不等于全仓可维护性已经验收，R06 和整体任务保持未完成。

## R06 时间排序失败边界（本批已收尾，按用户要求暂停）

- 在原函数内修复非法 dataset ID 去掉查询限制、数据库/时间字段异常被当成空结果、无效分数或时间被默认为零分或最新数据的问题。真实范围校验和缺少可选时间戳时的正常行为保留。
- 两个入口共用已有的有界文档 ID 收集规则。可选排序失败时保留原候选、记录原异常；流式入口保留已经成功识别的时间意图。未新增请求/结果类型或模块。
- 专项 **29 passed**；最终 **73 文件、1089 passed、3 integration skipped**。41 文件静态检查、compileall/diff 与 85 条模块边界通过，5 类公开结果不变。日志、XML 和源哈希见 `artifacts/refactor/repository-plan-v1/R06/temporal-verification.json`。
- 依用户“这波改完就停下来”要求，在此检查点暂停。R06 和全仓任务仍未完成，剩余工作等待用户恢复。
