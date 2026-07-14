# 健壮性·冗余·测试有效性修复计划（2026-07-14）

> 范围：只修复 `plans/backend-frontend-audit-2026-07-14.md` 中已逐行验证的静默降级、共享状态竞态、假测试与安全可删冗余。
> 目标：把"故障暴露出来"、把"绿灯变成真绿灯"，不改变正常路径的召回、排序、引用与合规语义。
> 关联：`plans/backend-performance-audit-2026-07.md`（性能修复计划，BP-01~06 执行中，本计划不重复其条目）、`plans/rag-recall-enterprise-latency-neutral-2026-q3.md`。
> 边界：不含安全维度（用户指定）；性能条目已归 BP 计划。

## 1. 硬约束

1. 延迟中性硬约束继续适用：不新增检索调用、模型调用或请求路径 DB 查询；RB-02 只置标志不加工作量。
2. 不改变召回、排序、ACL、引用、claim check、output guard 语义；**不触碰 `engine.py` 缓冲流式**——BP 计划 §6 已裁决其为 fail-closed 合规边界。
3. 不新增依赖、常驻后台服务、测试框架；index_audit 漂移检测维持手动/API 触发。
4. 每项先补确定性回归测试再改生产代码；删除类改动逐文件独立提交便于 revert。
5. TQ-01 是本计划唯一有意新增的 CI 门禁，且采用 ratchet（只挡增量）控制维护负担。

## 2. 审计结论（全部已由主会话逐行验证）

| ID | 结论 | 代码证据 | 优先级 |
| --- | --- | --- | --- |
| RB-01 | 默认集合向量写失败被吞，文档静默标 completed，chunk 永久不可召回；dataset-scoped 同失败却 raise，行为不一致 | `app/services/indexer.py:1911-1914` vs `:1820-1827` | P0 |
| RB-02 | 查询期向量检索异常降级为空结果，与零命中不可区分，Milvus 宕机=200 空答案 | `app/rag/retriever.py:4799-4800`、`:5104-5105`、`app/rag/engine.py:1959` | P0 |
| RB-03 | worker 心跳循环体无 try/except，首个 Redis 抖动即静默死亡，误报"worker 已死" | `app/tasks/worker.py:85-90` | P1 |
| RB-04 | 单例 retriever 可变缓存经 model_copy 按引用共享+线程池并发写+双锁不互斥；构建锁 get-or-create 无锁 | `app/rag/retriever.py:540-552`、`:1119-1138`、`engine.py:1891/2604` | P1 |
| RB-05 | 流式背压丢正文 chunk（截断答案无提示）；close 丢 sentinel 可致消费者永挂 | `app/rag/core/stream_writer.py:157-169`、`:279-281` | P1 |
| RB-06 | 前端：登出不清 Query 缓存（换账号残留数据）；轮询 timer 卸载后复活；useLocalSearch 每键全量重建索引 | `web/hooks/use-auth.ts:43-48`、`use-document-polling.ts:78-80`、`use-local-search.ts:18-34` | P1/P2 |
| TQ-01 | 字段级契约漂移 CI 不拦：drift 脚本恒 exit 0，87 个手写类型裸奔 | `web/scripts/check-api-types-drift.mjs:80`、`web/package.json:32` | P1 |
| TQ-02 | ACL 分页测试靠 SQL 子串嗅探，生产 ACL 写错测试照过 | `tests/test_run_list_acl_pagination.py:39-46,73-76` | P1 |
| TQ-03 | 查询分解测试 stub 掉被测逻辑且从不断言第二子问题 | `tests/test_query_decomposition_chain.py:59,63-65` | P2 |
| TQ-04 | 前端约 16/24 测试是源码 grep 非行为测试（假覆盖+极脆） | `web/app/history/page.delete-action.test.ts:10-12` 等 | P2 |
| RD-01 | Tier1 死代码：async DB 栈 6 符号、4 个空 embedding 子类、reranker shim、5 个死委托、6 个死异常类 | `database_singleton.py:59-124`、`providers/{bedrock,cohere,jina,voyage}.py`、`bge_v2.py`、`exceptions.py:165+` | P2 |
| RD-02 | 高风险样板复制：`_run_coroutine_sync`×10、openai/ollama 重试 ~90 行、redis client 工厂×8 | `dashscope.py:15-22` 等、`openai.py:26-92`/`ollama.py:20-92` | P2 |
| RD-03 | 两个"死代码"实为未接线：语言路由 resolver、图片 URL 重写 | `factory.py:79`、`image_url_rewriter.py:5` | 决策项 |

## 3. 实施步骤

### 阶段 A：静默降级止血（把故障暴露出来）

#### RB-01 默认路径向量写失败与 dataset-scoped 对齐

改动：
- `_index_chunk_vectors` 默认集合分支删除 `return [None]*len(docs)` 降级，改为与 `:1827` 一致的 `raise`，让 `process_document` 顶层 except 标 failed 并走既有 arq 重试。
- 保留告警日志；不改 dataset-scoped 分支；不新增自动调度（index_audit 维持手动）。

验收：
- [x] 模拟 Milvus 持续写失败：文档标 failed（非 completed），arq 重试可见；Milvus 恢复后重试成功。
- [x] 不再产生 `vector_id=None` 的静默 chunk；已有部分失败重试语义（清理+重建）不回归。
- [x] 正常入库路径行为与提交前一致。

#### RB-02 检索异常与零命中可区分

改动：
- `_hybrid_search` 主/fallback 两处 `except` 保留降级返回，但把异常记入既有 per-channel metrics 与 `_last_debug_metrics`，新增 `retrieval_degraded=true` 及原因（channel+异常类型）上传到 trace/debug 元数据。
- engine 侧：当**所有已启用**检索腿均异常（非零命中）时，`_run_one` 视为失败进 `retrieval_errors`，走既有错误事件路径；仅部分腿异常时正常返回但携带 degraded 标志。
- 不新增重试、不新增调用；纯标志与分支判断。

验收：
- [x] 向量腿抛异常 + BM25 可用：返回结果且 trace 带 `retrieval_degraded`；HTTP 仍 200。
- [x] 全部启用腿异常：请求返回错误事件/非 200，而不是空答案 200。
- [x] 真实零命中不置 degraded 标志；现有检索结果与排序回归测试不变。

#### RB-03 心跳循环容错

改动：`_heartbeat_loop` 循环体包 try/except（记 warning 后 continue），对齐 `task_queue_observability_service.py:402` poller 写法；create_task 加 done callback 记录意外退出。

验收：
- [x] 注入一次性 Redis 异常后心跳继续运行；持续异常时有限频告警日志。
- [x] worker 关停时任务正常取消退出，无泄漏。

### 阶段 B：共享状态与流缓冲正确性

#### RB-04 BM25 缓存单锁化 + 锁创建原子化

改动：
- `_get_bm25_build_lock`/`_get_sparse_build_lock`/`_get_colbert_build_lock` 改 `dict.setdefault(key, threading.Lock())`。
- BM25 数据 dict（retrievers/docs/doc_ids/versions）与 `_bm25_cache_order` 的全部增删改统一在 `_bm25_cache_lock` 下原子完成（构建大计算仍在 build lock 下，仅"写入缓存+记账"进 cache lock）。
- `_last_debug_metrics` 改为每次 invoke 局部构建后整体替换引用，避免跨副本写串。

验收：
- [x] 并发首建同 scope（线程栅栏测试）：索引只构建一次，无重复构建。
- [x] 注入乱序驱逐/构建交错：数据 dict 与 LRU order 条目集合始终一致，`max_tenants` 上限不被逃逸。
- [x] 检索结果、缓存命中语义与既有 `_bm25_dataset_cache_version` 失效行为不变。

#### RB-05 流缓冲不丢正文、close 保证终止

改动：
- 正文 chunk 的 `put` 不再 5s 丢弃：改为阻塞等待，叠加既有断连检测与整体 deadline（超 deadline 走 error 事件终止流，而非静默缺字）。
- `close()` 的 sentinel 投递保证送达：put 失败时改走"置关闭标志 + 唤醒消费者"路径，`__aiter__` 检查关闭标志退出。

验收：
- [x] 慢消费者场景：答案完整无缺字；队列仍有界；断连时生产者及时退出。
- [x] close 后消费者必然终止（含"队列曾满"情形），无永久挂起协程。
- [x] 正常流式事件序列与类型不变。

#### RB-06 前端三处小修

改动：`logout()` 增加 `queryClient.clear()`；`use-document-polling` 增加 `cancelledRef`，每个 await 后检查再注册 timer；`use-local-search` 的 fields/storeFields 由调用方提为常量（或内部 stable memo）。

验收：
- [x] vitest：登出后任意 query 缓存为空；卸载后不再有新 timer 注册；输入连续字符不触发 MiniSearch 重建（spy addAll 调用次数）。
- [x] `pnpm verify` 全绿。

### 阶段 C：测试真实性

#### TQ-01 契约漂移 ratchet 门禁

改动：`check-api-types-drift.mjs` 支持 `--strict --baseline <file>`；提交当前基线（15 模块/87 类型），计数**超过基线即失败**，等于或低于则通过并提示可下调；`api-check` 接入 strict 模式。

验收：
- [x] 新增一个手写漂移类型 → CI 红；删除一个 → 提示下调基线。
- [x] 现状（87）下 `pnpm verify` 保持绿。

#### TQ-02 ACL 分页测试去子串嗅探

改动：重写 `_FakeQuery`：不再对条件 `str()` 嗅探关键词，改为解析真实 BinaryExpression 并对内存行执行过滤（参照 `tests/test_feedback_service.py:22-52` 的既有可靠 fake），或改用内存 SQLite + 真模型执行生产查询。

验收：
- [x] 变异验证：把生产 ACL 条件故意改错（如漏 dataset 级权限 / AND→OR）后该测试必红；恢复后绿。
- [x] 原有分页/total 断言保留。

#### TQ-03 查询分解测试补真断言

改动：断言 `captured_queries` 精确包含两个子问题且顺序正确；另补一个不 stub `_decompose_query` 的单元测试（mock LLM 输出，验证解析/去重/截断逻辑本身）。

验收：
- [x] 变异验证：让分解链丢弃/重复第二子问题时测试必红。

#### TQ-04 前端 grep 测试处置（首批 3 个）

改动：将最误导的三个（`page.delete-action`、`reports/page.real-data.source`、`api-client.rag-evidence`）改为真实行为测试（render+交互 / msw 或 fetch spy）；其余 grep 测试在文件头加注释标记"源码规范检查，非行为覆盖"，排入 backlog 渐进替换，不一次性重写。

验收：
- [x] 三个新测试在对应真实回归（删除不触发/端点改名/数据未接）下必红。
- [x] 全套 vitest 通过，无因样式改动而红的旧断言残留于这三个文件。

### 阶段 D：冗余清理与决策项

#### RD-01 Tier1 死代码删除（逐文件独立提交）

改动：删除 async DB 栈 6 符号+re-export、4 个空 embedding 子类+`__init__` 导出、`bge_v2.py`、5 个死委托函数、6 个死异常类。每删前以词界 grep 复核零引用（含 tests/、字符串派发）。

验收：
- [x] 每次删除后 pytest + Ruff + compileall/导入检查全绿；全仓无新增 ImportError 路径。
- [x] `exceptions.py` 活跃异常（ValidationError/RateLimitError/LLMError 等）不受影响。

#### RD-02 高风险样板提取（行为等价重构）

改动：
- 新建 `app/core/async_bridge.py::run_coroutine_sync`，替换 10 处逐字副本；单测覆盖"有运行中 loop / 无 loop"两分支。
- 提取 `providers/_embedding_http.py`（信号量池、retry-after 解析、退避、重试循环），openai/ollama 只留 payload/response 差异；顺带修复 `_async_sem_by_loop` 按 `id(loop)` 不清理的慢泄漏（改 WeakKeyDictionary 或 loop 关闭钩子）。
- 新建 `app/core/redis_client.py` 统一 8 处 lazy 工厂；各处连接参数差异先显式列出再收敛，语义不同的保留传参。

验收：
- [x] 替换前后各调用点行为等价（mock 下向量/重试/超时结果一致）；embedding provider 既有测试全绿。
- [x] 新 loop 反复创建场景下信号量字典不再增长。

#### RD-03 未接线决策项（本计划登记，不执行）

- 语言路由 resolver（`factory.py:79`）：**移交** `rag-recall-enterprise-latency-neutral-2026-q3.md` P0-2 接线，本计划不删不改。
- `image_url_rewriter.py`：安全相关（JWT 走 URL 修复的一半），接线或删除由用户决策后另行处理。
- 疑似死但需人工确认清单（`rag/middleware/` 备用 API、`deepdoc/vision` vendored 算子、`_resolve_connectors_helper`×6）：维持不动。

## 4. 测试与验证顺序

1. 每项先写确定性失败测试（注错 stub / 线程栅栏 / 变异验证），看红→改→看绿。
2. 阶段顺序 A→B→C→D，各阶段独立提交；后端跑定向 pytest 文件 + Ruff，合并前跑仓库核心测试命令；前端跑 vitest + `pnpm verify`。
3. RB-01/RB-02 需要检索/入库回归：复用既有检索结果与排序回归测试，确认语义不变。
4. 不依赖真实 Milvus/Redis：全部用注错 stub 与内存实现。

## 5. 完成定义

- [x] RB-01~06、TQ-01~04、RD-01~02 验收全部通过；RD-03 两个决策项已登记去向。
- [x] 入库/查询路径不再存在"故障静默当成功"：写失败必 failed，检索腿异常必可观测。
- [x] 契约漂移有 ratchet 门禁；ACL 与分解测试通过变异验证。
- [x] 删除与提取零行为变化：召回、排序、引用、事件序列、响应 schema 全部不变。
- [x] 每阶段独立提交，Lore trailers 记录约束、测试与未覆盖环境。

## 6. 明确不做

- 不动 `engine.py:3563-4037` 缓冲流式：BP 计划 §6 已裁决为 fail-closed 合规边界。
- 不做安全维度修复（用户指定）；`image_url_rewriter` 仅登记决策。
- 不重复 BP-01~06（事件循环卸载、图桥、PDF 页数、反馈分页、embedding 缓存/DashScope 均在性能计划执行）。
- 不机械合并语义漂移的 coercion helpers（`_coerce_int`×22 失败返回 0/None 不一），需逐个定义语义后另行小批处理。
- 不一次性重写全部 16 个前端 grep 测试，不引入新测试框架或 E2E 扩军。
- 不为 index_audit 新增常驻调度服务；RB-01 用 raise 方案使其不再是必需品。
- 不删"疑似需人工确认"清单中的任何符号。

## 7. 风险与回滚

| 风险 | 防护 | 回滚条件 |
| --- | --- | --- |
| RB-01 使入库失败率显性上升（原被隐藏） | 这是暴露不是引入；arq 重试兜底；观察 failed 率一周 | 失败率异常且非 Milvus 故障 → 恢复降级 return 但必须同步登记 drift item |
| RB-02 改变"全腿异常"下的响应形态 | 仅在全部启用腿异常时才改行为；部分异常仍 200+标志 | 下游依赖 200 空答案的集成出现故障 → 撤回全腿异常分支，保留 degraded 标志 |
| RB-05 背压阻塞拖长慢客户端占用 | 整体 deadline + 断连检测双保险 | 生产者堆积 → 恢复丢弃但日志升 error 并发流内 error 事件 |
| TQ-01 strict 挡住无害改动 | ratchet 只挡增量，基线可显式调整 | 误报率过高 → 降回警告并记录原因 |
| RD 删除误伤动态引用 | 逐文件提交 + 词界 grep + 全测试 | 任一 ImportError/测试红 → revert 单文件提交 |
