# 前后端全量审视（2026-07-14）——冗余 / 健壮性 / 稳定性（速度另见性能报告）

> 日期：2026-07-14 ｜ 方法：四路并行子代理审计（后端健壮性稳定性 / 后端冗余死代码 / 前端质量 / 前后端契约与测试有效性）+ 主会话对全部 P0/P1 与代表性 P2 逐行复核代码属实。
> 边界：本轮**不含安全维度**（用户指定）；**执行速度**已由 `backend-performance-audit-2026-07.md` 系统覆盖，此处只补前端性能与冗余/健壮性顺带发现。
> 总基调：这是一个**成熟度很高**的代码库——防御性强（DB session 全 try/finally、HTTP 全 timeout、缓存有 LRU+maxsize+TTL、arq 任务 Redis 锁防死锁、前端 chat-stream 防竞态工程化到位、markdown 消毒顺序正确、虚拟化已用）。真实缺陷不多但**性质集中且危险**：静默降级把故障当成功、单例共享可变状态、测试给假保护。

---

## 一、稳定性 / 健壮性（最高优先——"绿灯但坏了"类）

### S-P1-1 入库向量写失败静默标 completed，chunk 永久不可召回（已逐行验证）
- `app/services/indexer.py:1911-1914`：默认集合路径 `except Exception: logger.warning(...); return [None]*len(docs)`——parse/chunk/PG 全成功、仅 Milvus 写失败时，chunk 以 `vector_id=None` 提交且文档标 **completed**。
- **行为不一致铁证**：dataset-scoped 路径同样失败是 `raise`（`:1827`，会被 `process_document` 顶层 except 正确标 failed 并重试）。只有默认路径吞掉。
- 结合 `LEXICAL_DB_HYBRID_FALLBACK_ONLY` 默认 True（BM25 仅兜底），这些 chunk 对密集检索永久不可见，用户看到"处理成功"无任何错误。安全网 `index_audit_service`（vector_id_missing 漂移检测）存在但**未自动调度**（app/tasks/、main.py 无入队）。
- 修复：默认路径与 dataset-scoped 对齐——写失败应 raise（走 failed+重试），或至少同步 `record_index_drift_item` 登记并标 partial/degraded，绝不静默 completed。

### S-P1-2 查询向量检索失败降级为空结果，与"无匹配"无法区分（已逐行验证）
- `app/rag/retriever.py:4799-4800`（主）与 `:5104-5105`（fallback）：`except Exception: vector_results = []` 不上抛。
- engine `_run_one`（`engine.py:1959`）只在 `.invoke()` 真 raise 时才 yield error；这里不 raise → `ok=True, docs=[]`、`retrieval_errors` 空 → Milvus 整体故障下每个查询静默丢密集腿，以 **HTTP 200 + 空/幻觉答案**返回，运维无 503 信号。
- 修复：区分"检索异常"与"零命中"——向量腿异常置 `retrieval_degraded` 标志上抛 trace/响应元数据；所有已启用腿都异常时返回错误或明确降级提示，而非静默空答案。

### S-P2-1 单例 retriever 经 model_copy 浅拷贝共享可变缓存 dict + 双锁不互斥（已验证 + 子代理实证 Pydantic 行为）
- `app/rag/retriever.py:540-552`：`_bm25_retrievers/_bm25_docs/_bm25_build_locks/_bm25_cache_order/_last_debug_metrics` 均 `PrivateAttr(default_factory=dict)`；`engine.py:1891/2604` 对模块级单例 `hybrid_retriever` 做 `model_copy(update=...)`。
- Pydantic v2 `model_copy` 对 PrivateAttr 可变 dict 是**按引用浅拷贝**（子代理实测 `a._cache is b._cache`），所有请求副本共享同一批 dict，且检索腿经 `asyncio.to_thread` 在线程池并发写。数据写在**构建锁**下、LRU 驱逐 pop 在**另一把 cache 锁**下，两锁互不排斥 → LRU order 与数据 dict 可失步 → 逃过 `max_tenants` 驱逐**无界增长**，或过早驱逐；`_last_debug_metrics` 共享致 trace 串请求。
- 修复：数据 dict 与 LRU order 的增删统一到 `_bm25_cache_lock` 一把锁；或改为不经 model_copy 共享的显式缓存对象。

### S-P2-2 构建锁的 get-or-create 本身无锁（check-then-act 竞态）
- `retriever.py:1119-1124` `_get_bm25_build_lock`（及 `:1126/:1133` sparse/colbert 同构）：`get→None→new Lock→set` 之间无锁，锁字典又跨请求共享（S-P2-1），冷缓存多线程同 key 首建时各造一把锁 → 同 scope BM25 索引**并发重复构建**（thundering herd，上千 chunk 语料可观 CPU/内存）。
- 修复：`dict.setdefault(key, threading.Lock())` 原子化，或 meta 锁保护。

### S-P2-3 Worker 心跳循环遇首个 Redis 错误即静默死亡
- `app/tasks/worker.py:85-87`：`while True: await observe_task_worker_heartbeat(...)` 循环体无 try/except；Redis 抖动抛异常即终止，任务 fire-and-forget 无 done callback 吞掉异常 → worker 仍工作但可观测性显示"已死"，误告警。
- 对照 `task_queue_observability_service.py:402` poller 循环体包 try/except 能续跑。修复：心跳循环体加 try/except fail-open。

### S-P2-4 流式背压丢正文 chunk / 关闭时丢 sentinel 致消费者永挂
- `app/rag/core/stream_writer.py:157-169`：慢客户端使有界队列满 5s → `except TimeoutError: 丢 chunk`，用户拿到截断答案无提示；`:279-281` close() 丢 sentinel 后消费者 `__aiter__` 可能等永不到来的 sentinel 永久阻塞。
- 修复：背压不丢正文（阻塞等待带整体 deadline，或发 error 事件终止）；close() 保证 sentinel 投递。

### 前端健壮性/稳定性
- **F-P1 登出不清 Query 缓存**（`web/hooks/use-auth.ts:43-48`，已验证）：`logout` 只清 profile 一条，无 `queryClient.clear()`；登入是客户端跳转无整页刷新。共享机换账号时新用户先读到前用户的 documents/datasets/会话缓存（staleTime>0 的 query 甚至不 refetch 直接给旧数据）。修复：`logout` 加 `queryClient.clear()`。
- **F-P2 轮询 timer 卸载后复活**（`web/hooks/use-document-polling.ts:78-80`）：`await` 后无条件 `setTimeout+set`，cleanup 若在 await 期间执行则注册出孤儿轮询；有 30s 自停上限故 P2。修复：await 后检 `cancelledRef`。
- **F-P2 useLocalSearch 每次按键全量重建索引**（`web/hooks/use-local-search.ts:18-34`）：唯一调用方 `sidebar.tsx:44` 内联传数组致 useMemo 依赖每渲染失效，搜索框每敲一字对全量文档 `removeAll+addAll`。修复：fields/storeFields 提常量或 memo。

---

## 二、代码冗余 / 死代码

### 关键：两处"死代码"实为**未接线的功能/修复**（不是删，是接线）
- **R-★1 语言路由 resolver 写好但从未调用**（`app/rag/embedding/factory.py:79` `resolve_language_aware_model_id`，已验证全仓零引用）：这正是 `EMBEDDING_LANGUAGE_ROUTING_ENABLED` 特性 + 召回计划 P0-2"配起 `EMBEDDING_MODEL_ZH/EN`"的核心 resolver。**特性没建，是没接线**。→ 归入 `rag-recall-enterprise-latency-neutral-2026-q3.md` P0-2，勿删。
- **R-★2 图片 URL 重写修复写好但未挂载**（`app/middleware/image_url_rewriter.py:5` `rewrite_markdown_image_urls`，已验证零引用）：对应记忆里"markdown JWT 走 URL query param 需修复"的安全项——修复函数已存在但没接进请求链。本轮不评安全，仅标注"躺着的未完成修复"，去留由用户定。

### Tier 1 死代码（安全删，收益明确）
- **整条 async DB 栈全应用零调用**（`app/core/database_singleton.py:59-124`：`_async_engine/AsyncSessionLocal/to_async_database_url/get_async_engine/get_async_session_factory/get_async_db` 6 符号 + `database.py` re-export）。~55 行，安全删。（注：健壮性子代理提到 `get_async_db` 有 try/finally，但既然零调用，删除优先。）
- **embedding/factory.py 5 个死公开函数**（`:156/:197/:202/:212` + 上述 `:79` 待接线）。
- **4 个死 embedding 空子类**（`providers/{bedrock,cohere,jina,voyage}.py` 各 9 行；factory else 分支直接返回 `OpenAICompatibleEmbedding`，已验证子类永不实例化）。
- **死 reranker shim** `reranker/bge_v2.py::BGEV2Reranker`（整文件，factory 只派发 `LocalBGEV2M3Reranker`）。
- **5 个死委托包装函数**（`chat.py:125/129`、`dataset_tables.py:89/94`、`documents.py:950`，真调用点是 `_impl`/`_role` 变体）。
- **6 个死异常子类**（`core/exceptions.py:165/178/187/210/233/253` 从未 raise/except/import；保留活跃的 ValidationError/RateLimitError/LLMError）。

### Tier 2 复制粘贴样板（提取消除 200+ 行高风险重复，安全）
- **`_run_coroutine_sync` 复制 9-10 份**（parsing/preprocess/enrich 多处 + dashscope + mineru_service）：sync-over-async 桥微妙易错却无共享实现，任一份漂移引入难查 event-loop bug。→ 提取 `app/core/async_bridge.py`。
- **openai/ollama embedding provider ~90 行信号量+重试+退避逐字重复**（`openai.py:26-92` vs `ollama.py:20-92`）→ 提取 `providers/_embedding_http.py`。
- **`_get_redis_client`×8 / `_invalidate_redis_client`×7**（health/candidate_cache/rerank_cache/adapter/chat_response_cache/semantic_cache/saml/embedding_migration 各自造 lazy global + from_url）→ 统一 `app/core/redis_client.py`。

### Tier 3 广泛小工具复制（低风险面积清理，部分需核实语义）
- ⚠ 数值 coercion helper 语义漂移（`_coerce_int`×22/`_coerce_float`×20/`_safe_int`×16 等，各变体失败返回 0/None/int|None 不一）——**不能机械合并**，需明确 default/None 两语义变体。
- `_now_utc`×18、`_update_heading_stack`×12（chunking，注意 `_iter_headings`/`_build_sections` 各格式真不同勿并）、前端 `prettyJson`×10+/`formatBytes`×6/`clipboard.writeText`×28 无公共 hook。

### 疑似死代码需人工确认（勿直接删）
- `rag/middleware/` 备用工厂 API（`create_*_middleware`/`MiddlewareConfig` 等 0 引用但子系统活着）；`rag/core/{interrupt,stream_writer}` / `checkpointer/factory` 若干 occ==1 可能是预留公共 API；`deepdoc/vision/operators.py` vendored 算子经字符串派发需对照注册表（`StandardizeImag` 疑 typo 很可能真死）；`_resolve_connectors_helper`×6 变体不一致且动态解析 test 模块，**勿删**需理解装配。

---

## 三、测试有效性（"稳定性"的元问题——测试在给假保护）

### T-A1 字段级契约漂移 CI 完全不设防（结构性，已验证）
- `web/scripts/check-api-types-drift.mjs:80` 注释 "always exit 0 so CI is not blocked yet"；`package.json:32` `api-check` 不带 `--strict`。实测报 **15 模块 87 个手写类型**（settings.ts 27 含 SystemSettings/RAGConfig/SafetyConfig，rag.ts 11，evaluation.ts 10）是调用点真用的。后端任一次改字段/可空性/删字段 → 这 87 类型不报错、typecheck 绿、test 绿、api-check 绿 → 前端运行时才崩。
- 修复：`api-check` 对 types-drift 加 `--strict` 并 ratchet baseline 下调；高频响应体改生成类型/zod。

### T-A2 路由存在性检查只认 3 种调用写法（结构性）
- `web/scripts/api-contract-lib.mjs:200-247` 只正则匹配 `apiClient.x('literal')`/`openapiRequest({path})`/`fetch(\`${API_V1_BASE_URL}\`)`；变量拼 URL、非 apiClient 实例、动态 method 全部逃逸 contract+coverage → 端点被后端改名/删无告警。

### T-B1 前端约 16/24 测试是"源码文本 grep"不执行代码（系统性，已验证）
- 机制：`fs.readFileSync(x.tsx)` + `expect(src).toContain('精确源码片段')`。既给**假覆盖**（组件渲染即崩只要字符串在就绿）又**极脆**（改格式/引号/缩进就红）。
- 铁证：`page.delete-action.test.ts` 名为删除动作实际只 `toContain('variant="ghost"')`（已逐行验证）；`navbar.source.test.ts:95` 把精确换行+12 空格缩进写进断言；`knowledge-page.entry.test.ts:9` 只断言一个 import 字符串存在。
- 修复：源码 grep 类改判 lint/规范检查（不算 test 覆盖），对页面/组件补真实 render+交互断言。

### T-B2/B3 后端过度 mock（已验证 B2）
- `test_query_decomposition_chain.py:59`：`_decompose_query` 被 stub 成常量 `["subquestion one","subquestion two"]`，`:63-65` 两处断言都只查 "subquestion one" 从不验证第二子问题——分解链丢/重复第二子问题、拆错都测不到（名承诺"sequentially"）。
- `test_run_list_acl_pagination.py:39-46`：`_FakeQuery.filter` 靠 SQL **子串嗅探**（含 "datasets"/"dataset_permissions" 就置 `_acl_applied`）模拟 ACL、过滤由 fake 重实现——生产 ACL 条件写错（漏 dataset 级权限、AND 写成 OR）只要 SQL 含关键词测试照过，越权不会暴露。

### T-B4 "运行时契约"测试是自证循环
- `web/lib/api-runtime-contracts.test.ts:48-68`：校验手写 zod schema 对手写样本对象能否 safeParse，两头同一作者两头同错则同过，**不校验 zod 是否与后端真 schema 一致**（与 T-A1 同根）。

### 测试健康区（子代理已判可靠，供参考）
- `test_document_asset_auth.py`（覆盖 JWT 走 URL 拒绝路径）、`test_rbac_current_access_endpoint.py`（真 TestClient 按角色校验权限集）、`test_connector_db_egress_and_auth.py`（真 SSRF/出网阻断）、`test_feedback_service.py`（fake 真解析 SQLAlchemy 算子 + 未分页 raise）、`test_eval_retrieval_metrics.py`（纯函数真值校验）；前端 `openapi-request.test.ts`/`api-client-chat-stream.test.ts`/`navbar.behavior.test.ts` 真执行逻辑。

---

## 四、已检查、确认健康的区域（后续审计可跳过）

- **后端防御性**：DB session 全 try/finally close + rollback；外部 HTTP 全 timeout + 退避 + Retry-After，无裸 requests；缓存驱逐 LRU+maxsize+TTL+锁；arq 任务 Redis 锁带 TTL 防死锁；顶层 `process_document` except 标 failed + 清理 + re-raise 走重试；关键 gather 均 return_exceptions=True 或每协程自带 try；预处理/切块除零全有守卫；MilvusVectorStore/RAGEngine/jwt_verify 双检锁正确；fire-and-forget 大多保留强引用 + done callback（`chat.py:154` 是模范）。
- **前端**：数据 hooks 大面积 TanStack Query（race 库处理、错误/空态齐全）——**记忆里"hooks 仍 useEffect 手动 fetch/useMutation≈0"已过时作废**；chat-stream AbortController+超时+RAF+断流恢复+降级；chunk-preview 双重防 race；markdown rehypeRaw→rehypeSanitize 顺序正确无 dangerouslySetInnerHTML；虚拟化 react-virtual 已用于 sidebar/knowledge/chunk-list；无 array-index key、无无守卫 .map、JSON.parse 基本包 try/catch；error.tsx 边界齐全。
- **契约健康**：openapi.json 新鲜（07-13）；backend.ts 别名生成类型不漂移；ChatResponse/Citation/PromptTemplateOut/RagasRun 高频响应体逐字段一致；check-api-contract/coverage 现均 PASS。

---

## 五、建议修复批次（全部与性能报告正交，可并行）

1. **批次 1（静默降级止血，最高优先，小 diff）**：S-P1-1 indexer 默认路径改 raise/登记漂移 + 自动调度 index_audit；S-P1-2 检索腿异常置 `retrieval_degraded` 上抛；S-P2-3 心跳 try/except。这三条是"把故障暴露出来"，不改正常路径语义。
2. **批次 2（单例并发正确性）**：S-P2-1 BM25 缓存统一单锁 + S-P2-2 锁创建 setdefault 原子化（同一片代码，一起改）；F-P1 登出 `queryClient.clear()`。
3. **批次 3（测试补真实性，防未来回归）**：T-A1 加 `--strict` ratchet；T-B1 前端 grep 测试改真实 render；T-B2/B3 后端去 mock 补真实断言（尤其 ACL 分页那条，关系越权正确性）。
4. **批次 4（冗余清理，低风险面积）**：Tier 1 死代码删除（先处理 R-★1/★2 的"接线 or 删"决策）；Tier 2 三处样板提取。

## 与既有 plan 的关系
- R-★1 语言路由 resolver → 并入 `rag-recall-enterprise-latency-neutral-2026-q3.md` P0-2。
- S-P1-1/S-P1-2 静默降级 → 与 `rag-four-subsystem-audit-2026-07.md` 的 OTel 阶段 span 缺失相关：可观测性补齐后这类静默故障才可告警。
- 性能维度全部在 `backend-performance-audit-2026-07.md`，本报告不重复。
- 方法论：四路子代理并行 + 主会话逐行复核；子代理结论必须验证后采信（性能轮曾出现"检索已 offload"误判被代码裁决修正）。
