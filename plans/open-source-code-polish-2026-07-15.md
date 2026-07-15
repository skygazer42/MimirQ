# 开源前代码打磨清单（2026-07-15）——冗余 / 写错 / 更好设计

> 目的：为开源公开做**代码级可读性打磨**（非上线 gate，非安全/合规——那些见 `open-source-release-gate-2026-07-14.md`）。
> 方法：四路并行 review（后端 Python 质量 / 前端 TS+React 质量 / API+数据模型设计 / 文档与新人友好度）+ 主会话对头部发现逐行验证。
> 覆盖状态：前端质量、API 设计两路已完成并验证；后端 Python 深读、文档友好度两路报告未送达（见 §6 待补）；另有主会话独立扫描的确定项（§1）。
> 总基调：**代码机械纪律很好，低级 bug 几乎为零**——前端 0 处 index-key / 0 松散 == / 0 @ts-ignore / 仅 3 处 as any；后端 0 生产 print / 0 TODO-FIXME / 0 裸 except。真正可挑的集中在**设计/一致性层**与**开源门面**，不在 bug 层。这对开源是好信号。

> 执行裁决（2026-07-15）：本轮仅处理 M-1/M-2/M-3、A-1 中仓库实际使用的 400/409/416，以及 F-1。其余 API/DB 兼容性改造与未经测量的结构性重构暂缓。
> 执行结果：上述范围已完成，相关回归测试及全量前端门禁通过。
> 第二批裁决：D-2 保留应用侧默认值，只改为 UTC-aware，避免引入数据库迁移；D-5 仅收紧四个已明确值域的关键配置。A-2 中入库任务状态与文档状态属于不同领域，不合并，DB 约束继续暂缓。

---

## 1. 开源门面（必修，别人第一眼就看到）——主会话已逐行验证

### M-1 一个文件通篇 GBK 乱码注释（已完成）
- 当前复核确认 `web/components/data-governance-panel.tsx` 共 **48 行**乱码注释，现已全部重写为正常中文。仅此一文件。
- 为什么必修：开源后任何人打开此文件第一屏就是乱码，直接拉低专业观感。
- 处置：按原意用正常中文（或英文）重写这些注释。

### M-2 内部研发代号注释散落 16 文件 21 处（已完成）
- 代表：`app/api/v1/chat.py:175` `# Tenant QPS quotas (Wave22-T094): ...`、`app/api/v1/rbac.py:4` `Wave22-T092: RBAC roles ...`、`app/api/v1/usage.py:346`（`Wave22-T095: cost attribution`）。前端另有 1 处。
- 为什么必修：`Wave22-T094` 是内部迭代任务编号，对外部读者零信息量、还暴露内部流程节奏。
- 处置：批量删除代号前缀或改写为正常功能描述（如 `# Per-tenant aggregate QPS limiter (best-effort)`）。

### M-3 注释掉的 print 调试残留（已完成）
- 当前复核确认 `app/deepdoc/parser/excel_parser.py` 与 `app/deepdoc/vision/recognizer.py` 共 5 处 `# print(...)`，现已删除。均为非活代码。
- 处置：顺手清理即可，非阻塞。生产活 `print()` = 0（已确认干净）。

---

## 2. 接入体验（高性价比，改动小，"别人接你 API 立刻踩"）——已逐行验证

### A-1 错误码信封在最高频的 400/409 上退化为通用码（已完成：400/409/416）
- `app/core/exceptions.py:248` `error_code_map` 只含 `{401,403,404,422,413,429,500,503}` 八个；但全仓 `status_code=400` 用了 **357 次**、`409` 用了 **48 次**，二者不在 map 里 → `ErrorResponse.error` 全部落回通用 `"HTTP_ERROR"`。
- 为什么：那个设计得很好的机器可判别错误字段，在占比最大的两类错误（校验失败/冲突）上失效，接入方只能回退去 string-match `message`。
- 处置：map 补 `400:"BAD_REQUEST"`、`409:"CONFLICT"`、`416`、`402` 等；或让端点改抛携带稳定 `error_code` 的 `MimirQError` 子类（该体系已存在但 HTTP 层几乎没消费）。

### A-2 文档状态枚举三处定义、值集发散、DB 不约束（复核后暂缓）
- `app/models/document.py:74` `status = Column(String(20))` 注释 4 值（pending/processing/completed/failed）；`app/api/schemas/document.py:16` `DocumentStatusEnum` 6 值（多 quarantined/cancelled）；`app/models/ingestion_run.py:70` 注释 7 值（多 created）。DB 列裸 String 无 CHECK。
- 为什么：接入方无法从单一来源知道会收到哪些状态；脏值可直接落库。权限词表同类问题（`DocumentAccessMode` Literal vs `DatasetPermissionEnum` Enum，两套重叠不等同）。
- 处置：每个受控词表建单一 source of truth（`str, Enum`），DB 加 `CheckConstraint`（项目已有先例 `models/feedback.py:25`），API `*Out` 复用同一枚举。
- 复核裁决：`Document.status` 与 `IngestionRunDocument.status` 分属文档生命周期和单次入库映射状态，不能合并成同一枚举；本轮仅修正文档模型的六值注释，DB 约束留待兼容性迁移时处理。

### A-3 请求体默认静默吞未知字段
- 绝大多数 Create/Update/Request schema 无 `model_config`（Pydantic 默认 `extra="ignore"`）；全仓仅 19 处 `extra="forbid"`。
- 为什么：写操作里 `nam`（拼错 `name`）被静默丢弃、返回 200，调用方以为生效了。
- 处置：建 `StrictRequest` 基类统一 `extra="forbid"`，所有请求体继承；响应可保持 ignore 向前兼容。

### A-4 约 27% 端点无 response_model
- 387 路由中 282 带 `response_model`（73%），166 处返回裸 `dict/Any`。
- 为什么：这些端点 OpenAPI 响应体为空，生成的客户端拿到 `any`，对一个"以别人接你 API 为卖点"的开源项目是直接体验损耗。
- 处置：对外端点补 `*Out` schema（尤其 observability/pipeline/kg）；内部/调试端点标 `include_in_schema=False` 明确区分。

### A-5 PUT/PATCH 语义不一致
- `app/api/v1/prompt_templates.py:373` `PUT` 却是部分更新语义（全 Optional）；孪生资源 `rag_config_templates.py:177` 用 `PATCH`。`chunk_presets.py:232`、`connectors_configs.py:112` 也 PUT 做部分更新。
- 处置：统一"部分更新=PATCH、整体替换=PUT"。

---

## 3. 前端设计/抽象（结构性，建议示范式推进，非全量重写）——已验证头部

### F-1 真 bug：formatFileSize 对负数/NaN/≥TB 输出 "undefined"（已完成）
- `web/lib/utils.ts:33`：`i = Math.floor(Math.log(bytes)/Math.log(k))`，`bytes` 为负/NaN → `i=NaN` → `sizes[NaN]=undefined`；`bytes≥1TB` → `i=4` 越界。输出 `"NaN undefined"`。
- 处置：入口守卫 `Number.isFinite(bytes) && bytes>0`，`i` 用 `Math.min(i, sizes.length-1)`，`sizes` 补 TB。

### F-2 格式化函数散落且分叉（高频）
- `formatRelativeTime` 三套各不同（`app/history/page-client.tsx:1300` Intl 范本级 / `datasets-page.tsx:135` 硬编码中文 / `lib/utils.ts:46` 硬编码 zh-CN 无守卫）；`formatBytes/formatFileSize` **6 份定义**。
- 为什么：同概念多实现、阈值/i18n/容错各异 → 显示不一致；canonical `formatDate` 硬编码 zh-CN 反而逼各处重造。
- 处置：统一到 `lib/format.ts`，以 history 的 Intl 版为准接受 locale 参数，删本地重复。**改动小、收益直接，建议先做。**

### F-3 组件/表单状态碎片化（系统性，25 个组件 useState≥15）
- 代表 `components/knowledge/import/knowledge-web-crawl-dialog.tsx:132-153`（21 个字段各一 useState + `authType` 判别哪些有效）；`document-detail-dialog.tsx`（30 useState/1208 行）。
- 处置：`useReducer` 单一 state 或 react-hook-form；auth 部分用 discriminated union。**挑最痛的 web-crawl 表单做一个示范再推广。**

### F-4 chunk-preview 巨型 context → 重渲染风暴
- `components/chunk-preview/context.tsx:1666` 单 useMemo 聚合 ~40 state（含 `hoveredChunkIndex`），任一变化（连鼠标悬停）→ 全 consumer 重渲染。
- 处置：拆 context（稳定 actions vs 易变 state；hover/selection 单独 context），或用项目已有 Zustand + selector。

### F-5 手写 resize 逻辑重复 4 份、行为不一致
- `data-governance-panel.tsx:633` / `ragviz/similarity-workbench.tsx:1349`（还含 2 份）/ `document-viewer-panel-shell.tsx` / `ui/fluid-cursor.tsx`；持久化与 clamp 边界各写各的。
- 处置：抽 `useResizablePanel({min,max,storageKey?})`。

### F-6 该用 discriminated union 却 as 断言 narrow（类型安全）
- `app/graph/_components/graph-node-detail-panel.tsx:191-212`：`KGEntityDetailResponse | KGEventDetailResponse` 靠外部 `selectedNode?.meta?.kind` 判别再 `as`；`types/knowledge-graph.ts:79/91` 无共享判别字段。
- 处置：两 interface 加 `kind:'entity'|'event'` 直接 narrow，去掉所有 `as`。

### F-7 server 状态镜像进 client store（双数据源）
- `components/data-governance-panel.tsx:505-578`：useQuery 数据经 useEffect 命令式灌进 Zustand，全组件从 store 读。
- 处置：直接消费 query.data + 衍生，别 query→store 镜像。

### F-8 其他（次要）
- `hooks/use-document-list.ts:79` 声明式 useQuery 与命令式 fetchQuery 混用（同 key 双取）→ 用 refetch/ensureQueryData。
- `components/test-case-manager.tsx:524` `as unknown as Citation[]` + `as any`（全库仅 3 处 as any 之一）→ 补全 `retrieveEvidence` 响应类型。

---

## 4. 数据模型/后端设计（维护者改一处要改多处）——已验证头部

### D-1 七张近乎相同的 Run 表无共享基类
- `ConnectorRun`/`IngestionRun`/`RagasEvaluationRun`/`RagasRegressionRun`/`KGSearchDiagnosticsRun`/`DatasetPrecheckScanRun`/`DatasetProfileScanRun` 全直接 `(Base)`，各自重抄 tenant_id/status/config/stats/error/时间戳；`status` 宽度 20/32 混用。ConnectorRun 与 IngestionRun 功能高度重叠（两套 API 并存）。
- 处置：抽 `RunMixin`；评估 ConnectorRun 是否可收敛为 IngestionRun 的一个 `kind`。

### D-2 时间戳默认值两套机制并存（已完成：应用侧 UTC-aware）
- `datetime.utcnow`（naive，3.12 起弃用）：`dataset.py:42`/`tenant.py:23`/`dataset_category.py:43`/`tenant_group.py:40`/`group_permissions.py` 5 文件；其余用 `server_default=func.now()`（tz-aware）。列都声明 `DateTime(timezone=True)`。
- 为什么：前 5 张表写入 naive UTC，读出 tzinfo 缺失，跨组时间比较会 aware/naive 混用异常。
- 处置：保留现有应用侧默认值语义，统一为 `datetime.now(UTC)`；不引入数据库迁移。

### D-3 Schema 字段四处重复 + 共享基类被绕过
- `schemas/dataset.py` 的 `DatasetBase/DatasetUpdate/DatasetOut/DatasetConfigBundle` 各自重抄同一组 ~15 字段；`base.py` 的 `OrmTimestampModel/TimestampMixin` 各仅用 3 次，而 `created_at: datetime` 在 schema 里手抄 43 次。
- 处置：抽 `DatasetConfigMixin` 共享；`*Out` 一律继承 `OrmTimestampModel`。

### D-4 约束/FK 严格度不一致
- `models/feedback.py:49` `rating` 注释"1-5"无 CheckConstraint（同表 category 有）；`RagasRegressionItem.case_id`（evaluation.py:132）裸 UUID 无 FK（同类 run_id 有）；`IndexDriftItem.document_id/chunk_id`、`EvidenceItem.regression_case_id` 均无 FK。
- 处置：能加 FK 的补 FK（多租户用组合 FK，项目已有优秀先例）；rating 加 `CheckConstraint('rating BETWEEN 1 AND 5')`。

### D-5 受控配置项用裸 str + 注释而非 Literal（已完成：四个关键配置）
- config.py 1257 项里仅 2 个 Literal；`INPUT_GUARD_MODE`(252)/`RETRIEVAL_FUSION_STRATEGY`(943)/`VECTOR_BACKEND`(1354)/`GOVERNANCE_PII_MODE`(1684) 等几十个是"注释即枚举"的裸 str。
- 为什么：env 拼错（`GOVERNANCE_PII_MODE=msak`）加载期不报错，运行时才 fallback 走错分支。
- 处置：本轮仅将上述四项改为 `Literal[...]`，加载即校验；同时删除 VECTOR_BACKEND 与 RETRIEVAL_FUSION_STRATEGY 的重复手写校验。

### D-6 列表分页元数据不统一（nit）
- 仅 `schemas/chat.py:236 ConversationList` 有 `total/returned/has_more/next_skip`；其余列表是 `{total, items}`（信封一致是优点，但多数不告诉"还有没有下一页"）。
- 处置：把 `has_more/next_skip` 提升为所有列表标准字段（SCIM 例外，它正确遵循 startIndex/count）。

---

## 5. 各路确认"写得好、值得保留"（重构时勿破坏）

**前端**：`lib/query-keys.ts` 分层 queryKey 工厂杜绝 key 漂移；`query-provider.tsx:12` 按状态码分流 retry+退避；`use-documents.ts` 组合 4 个聚焦子 hook；`formatApiError` 全站 396 处统一；`getDatasetStatusBadgeConfig` 是 discriminated union 正例。
**API/模型**：组合外键强制租户一致性（`(tenant_id,dataset_id)→datasets`）从 schema 层杜绝跨租户挂接；统一 `ErrorResponse{error,message,detail,request_id,hint}` 四 handler + hint 推导，远超 FastAPI 默认；282 response 全走 DTO 无 ORM 泄漏；分页 skip/limit 全站一致；201/204/409/416/202 用得准；`IngestDeadLetter` 带 schema_version+producer_service 可回放可追责。
**机械纪律**：前端 0 index-key/0 松散==/0 @ts-ignore/0 exhaustive-deps 禁用；后端 0 生产 print/0 TODO-FIXME/0 裸 except。

---

## 6. 待补（两路 review 报告未送达，需补跑或人工过一遍）

- **后端 Python 代码质量深读**（rev-py-quality 未回）：类型标注质量（397 处 type:ignore 抽样，集中在 orchestrator.py:21/connectors_acl.py:18/milvus.py:14）、异常设计一致性、函数职责过载/参数过多/可变默认参数、Pythonic 程度（range(len)/os.path 拼接/魔法数）。**建议补跑一路或本地用 ruff/mypy 严格模式扫一遍。**
- **文档与新人友好度**（rev-docs-onboard 未回）：关键模块注释质量（engine/retriever/orchestrator/kg 有没有解释"为什么"）、命名可读性、项目结构可导航性、缺 ARCHITECTURE.md、README 宣称特性（SPLADE/ColBERT/KG）vs 代码真假一致性。**建议补跑或结合已知（记忆中"账面能力≠默认行为"）人工确认。**

---

## 7. 建议处理顺序（按 改动成本 × 别人会不会挑）

1. **开源前必清（0.5 天，纯门面）**：M-1 乱码注释、M-2 Wave 代号 28 处、M-3 print 残留。
2. **接入体验（1 天，小改大收益）**：A-1 错误码补 400/409、A-3 请求体 extra=forbid、F-1 formatFileSize 修 bug、F-2 格式化统一；A-2 等兼容性迁移时处理。
3. **一致性欠账（2-3 天，维护性）**：D-2 时间戳统一、D-5 关键配置收紧、D-4 补 FK/CheckConstraint、D-1 Run 表 RunMixin、A-4 补 response_model。
4. **结构性重构（示范式，不阻塞开源）**：F-3 表单状态、F-4 chunk-preview context、F-5 useResizablePanel、D-3 schema mixin——各挑一个最痛的做示范，其余渐进。
5. **补审两路**（§6）后合并本清单。

## 关系
- 与 `robustness-redundancy-fix-2026-07.md`（RD 死代码/样板）、KG 图分裂待办（task #19 之外另记）互补，均属代码质量维度。
- 与 `open-source-release-gate-2026-07-14.md`（泄密/license/默认值）正交——那份是"能不能开源"，本份是"开源后代码好不好看"。
