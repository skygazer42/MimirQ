# 后端性能修复计划（2026-07-14）

> 范围：只修复已由当前代码证明的阻塞、重复 I/O 和客户端重复构造。
> 目标：降低并发阻塞和确定性浪费，不增加检索步骤、候选量、外部调用或线上维护负担。
> 关联：`rag-recall-enterprise-latency-neutral-2026-q3.md`、`rag-four-subsystem-audit-2026-07.md`。
> 状态：已实施（2026-07-14，二次复核闭环）。流式抽取回退与 corrective second pass 两个同根漏点已补齐；核心测试、Ruff、compileall 和仓库 verify 均通过。

## 1. 硬约束

1. 不改变召回、排序、ACL、版本过滤、引用、claim check、output guard 和读写一致性语义。
2. 不增加查询改写、检索通道、候选数、rerank 次数、模型调用或请求内缓存查询。
3. 不新增依赖、缓存基础设施、评估数据集、指标体系、k6/Locust 或新的 CI 门禁。
4. 优先复用现有 `run_blocking_retrieval_call`、HTTP client pool、解析产物元数据和 perf suite。
5. 性能证明以确定性的“事件循环可继续运行、调用次数减少、请求路径不再读文件”为主；现有 nightly perf suite 只做同配置观察，不作为新增交付物。

## 2. 审计结论

| ID | 结论 | 代码证据 | 优先级 |
| --- | --- | --- | --- |
| BP-01 | 多个 async 检索入口直接执行同步检索，阻塞事件循环 | `app/rag/engine.py:1948-1964,2646`、`app/services/chat_stream_orchestrator.py:192`、`app/api/v1/rag.py:1139,1207,1567`、`app/api/v1/retrieval_explain.py:197`、`app/rag/agents/rag_agent.py:557`、`app/rag/retriever.py:7287-7293` | P0 |
| BP-02 | `use_graph=True` 的同步 LangGraph 迭代器在 async generator 内运行，独占事件循环 | `app/services/chat_stream_graph.py:164-205`、`app/rag/pipelines/langgraph.py:562-569` | P0（可选图路径） |
| BP-03 | 同一检索请求重复解析 dataset embedding runtime，且无条件执行第二次安全元数据回填 | `app/rag/retriever.py:1011-1045`、`app/rag/retriever.py:4470`、`app/rag/retriever.py:5712`、`app/rag/retriever.py:7006-7040` | P1 |
| BP-04 | 文档列表和详情会对缺少页数的历史 PDF 在请求内同步打开并解析源文件 | `app/api/v1/document_listing.py:201-213`、`app/services/document_runtime_metadata.py:20-32`、`app/services/document_runtime_metadata.py:93-110`、`app/api/v1/document_detail.py:91` | P1 |
| BP-05 | 反馈列表先 `.all()`，再在 Python 中排序和分页 | `app/services/feedback_service.py:365-398` | P1 |
| BP-06 | dataset-scoped embedding 每次查询重建对象；DashScope 每次 async 调用新建 HTTP client，sync 调用新建线程池和事件循环 | `app/services/dataset_embedding_config.py:82-90`、`app/rag/retriever.py:1053-1060`、`app/rag/embedding/providers/dashscope.py:17-24`、`app/rag/embedding/providers/dashscope.py:73-82` | P1 |

原草案中其余条目不进入实施清单，原因见第 6 节。

## 3. 实施步骤

### 阶段 A：消除 async 热路径阻塞

#### BP-01 统一卸载同步检索

改动：

- 在 `app/rag/engine.py` 中让默认串行分支复用现有 `_run_one`，保留其 `asyncio.to_thread(r.invoke, q)`；并行分支和 `RETRIEVAL_QUERY_PARALLELISM` 语义不变，避免双重限流。
- 在 `app/api/v1/rag.py` 的 evidence 主检索、fallback 和 prompt preview，以及 `app/api/v1/retrieval_explain.py` 中，复用 `app/services/rag_runtime_limiter.py:73-88` 的 `run_blocking_retrieval_call`。
- 在 `app/rag/agents/rag_agent.py` 和 `HybridRetriever._aget_relevant_documents` 中卸载同步调用；不改变异常降级、返回结构或检索参数。
- 流式抽取回退复用 `run_blocking_retrieval_call`；corrective second pass 复用 engine 既有 `_run_one`，不保留第二份同步调用和异常解析。
- 不调高 `RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY` 或 `RETRIEVAL_QUERY_PARALLELISM`，本项只恢复事件循环公平性。

验收：

- [x] 用线程身份断言覆盖 async retriever、流式抽取回退和 corrective second pass；不依赖调度时长阈值。
- [x] engine 串行和并行分支的结果顺序及 debug metrics 一致；全通道失败均发 error 事件（修复前串行漏发，现为 RB-02 有意收敛）。
- [x] API 级调用仍受现有全局 gate 约束，`rag_offload_queue_ms` / `rag_offload_exec_ms` 可继续写入已有 runtime metrics。
- [x] 不新增检索调用，不改变单请求 query plan。

#### BP-02 隔离同步图迭代器

改动：

- 在 `app/services/chat_stream_graph.py` 中把整个 `rag_workflow.stream(...)` 生产循环放入一个 worker，而不是只在线程中创建 generator。
- 使用标准库和有界队列把现有 `graph`、`citations`、`token`、`done`、`error` 事件桥接回 async consumer；复用 `app/services/chat_stream_langchain.py` 的断连、心跳和事件组装语义，不新增依赖。
- 断连时设置停止信号并回收 producer；队列满时施加背压，不静默丢事件。
- 保留当前完整 answer 后按 120 字切分的行为。本阶段只解决事件循环阻塞，不宣称改善图路径真实 TTFT。

验收：

- [x] 同步 graph stub 阻塞时，SSE heartbeat 和同进程的另一 coroutine 仍能运行。
- [x] 正常、异常和客户端断连时 producer 都收到停止信号；当前同步 step 返回后退出，无 event-loop task 泄漏。
- [x] 现有 SSE 事件类型、顺序、citations、assistant message ID 和持久化输入不变。
- [x] 队列上限和背压由确定性测试覆盖。

### 阶段 B：删除请求内重复 DB 和文件 I/O

#### BP-03 单次解析 embedding runtime，按候选身份决定第二次回填

改动：

- 在 `HybridRetriever._get_relevant_documents` 开始一次性解析不可变的 `DatasetEmbeddingRuntimeConfig`，向 `_hybrid_search` 和 `_enrich_results_with_db_metadata` 传递该对象或其 `embedding_space_hash`。
- 保留 `_bm25_dataset_cache_version` 的每次版本读取；它负责跨进程索引失效，不做 TTL 或请求外缓存。
- 第一次 enrichment 后保存 `{self._result_key(item)}`；邻居扩展和父子合并后，只有候选身份集合变化才执行第二次 enrichment。
- 不用列表长度差作为判断。父块替换可能长度不变，但新 chunk 仍必须重新经过 ACL、dataset、版本、pipeline 和 embedding-space 过滤。

验收：

- [x] 默认路径 `_resolve_embedding_runtime` 每个检索请求只调用一次。
- [x] 邻居和父子功能关闭时 enrichment 只调用一次。
- [x] 功能开启但候选身份不变时只调用一次。
- [x] “长度不变但 child 被 parent 替换”和“新增 neighbor”时必须调用第二次，并继续过滤无权限、过期或错误 embedding space 的 chunk。
- [x] 检索结果、排序、引用和 ACL 回归测试保持一致。

#### BP-04 从文档读取 API 删除 PDF 解析

改动：

- 保留解析阶段现有 `compute_parsing_artifact_stats` 持久化：`app/parsing/processors/processor.py:1593-1612` 已把 `page_count` 写入 `doc_metadata`，无需新增入库计算。
- 复用 `app/services/dataset_profile_scan_runner.py:141-160` 的幂等回填，先从既有 `pdf_quality.page_count` / `page_max` 补齐历史数据；确需读取源 PDF 的遗留记录，只允许在离线扫描/一次性回填路径处理并持久化。
- 回填能力就绪后，删除 `attach_runtime_document_metadata` 在列表和详情请求中的 `_read_pdf_page_count` fallback；响应 schema 不变。
- 不引入 Redis page-count cache，也不把文件解析简单移到请求线程池，因为那仍会重复消耗 I/O 和 CPU。

验收：

- [x] 新解析文档继续持久化 `page_count`，无需列表请求补算。
- [x] 历史回填可重复运行，已有有效值不覆盖，缺失/损坏文件不会中断批次。
- [x] 文档列表最多 200 条时不调用 `PdfReader`、不打开源 PDF；详情端点同样满足。
- [x] 已回填文档的列表/详情页数与修改前一致；无法回填的遗留文档保持现有缺失值语义。

#### BP-05 下推反馈排序和分页

改动：

- 在 `FeedbackService.list_message_feedback` 中基于同一过滤 query 分别执行 `count()` 和分页查询。
- 使用 `ORDER BY coalesce(updated_at, created_at) DESC, id DESC`，再执行 `OFFSET/LIMIT`；保留后续批量 enrichment。
- 不在本批次重写 feedback upsert 或候选构建，不引入窗口函数或新索引，除非现有数据库执行计划证明必要。

验收：

- [x] 服务层不再对完整反馈结果调用 `.all()` 后切片。
- [x] `total` 仍表示过滤后的总数，页内数量不超过 `limit`。
- [x] 相同时间戳下按 `id DESC` 稳定分页，连续页面无重复、无遗漏。
- [x] conversation、message 和 rating 过滤组合的结果与现有语义一致。

### 阶段 C：复用 embedding 对象和连接

#### BP-06 缓存 dataset-scoped adapter，复用 DashScope HTTP pool

改动：

- 在 `app/services/dataset_embedding_config.py` 对 `create_embeddings_for_runtime` 增加小容量有界 LRU；键直接使用 frozen `DatasetEmbeddingRuntimeConfig`，配置或密钥变化会生成新实例。
- 缓存只覆盖当前已经每查询重建的 dataset-scoped 路径，不改变默认全局 vector store。
- 在 `DashScopeEmbedding` 初始化时复用 `app/core/http_client.py` 的 external sync/async clients；`encode` 直接走 sync client，`aencode` 直接走 async client，删除每调用一次的 `ThreadPoolExecutor`、`asyncio.run` 和 `httpx.AsyncClient`。
- 保留请求 timeout、payload、归一化和错误转换语义。

验收：

- [x] 相同 runtime 连续调用返回同一 adapter；provider/model/base URL/API key/space hash 任一变化均不误复用。
- [x] LRU 容量有上限，并发首次访问不产生错误或错误配置串用。
- [x] DashScope sync/async 各自复用 shared external client，每次 encode 不创建 event loop、executor 或 HTTP client。
- [x] mock HTTP 响应下向量顺序、单位归一化、超时和错误类型与修改前一致。

## 4. 测试与验证顺序

1. 先补确定性回归测试，再改生产代码；优先扩展 `tests/test_retrieval_secondary_pass.py`、`tests/test_feedback_service.py`，并为 async offload、graph bridge、document runtime metadata、dataset embedding runtime 和 DashScope provider 增加聚焦测试。
2. 每个阶段运行对应的 pytest 文件和 Ruff；阶段合并前运行仓库现有核心测试命令，不建立新的性能数据集或质量门禁。
3. 使用 `make perf-smoke` 确认现有 harness 仍可运行；如有可比环境，再复用 `.github/workflows/perf-nightly.yml` 的同镜像、同配置、同迭代参数观察前后报告，不更新 baseline 来掩盖退化。
4. 验证顺序固定为 A → B → C；阶段失败时只回滚该阶段，不把多类优化揉成一次提交。

## 5. 完成定义

- [x] BP-01 至 BP-06 的确定性验收全部通过。
- [x] async 请求路径没有本计划列出的同步检索和源 PDF 解析。
- [x] 默认检索的外部调用数、候选量、排序、ACL、引用、合规校验和一致性语义不变。
- [x] 没有新增依赖、后台常驻服务、评估数据集、指标维护项或默认并发参数变化。
- [ ] 每个阶段独立提交，并在 Lore trailers 中记录约束、测试和未覆盖环境。

## 6. 明确不做

- 不做“先流式输出、末尾 correction/redaction”。`app/rag/engine.py:3540-4037` 的缓冲是 fail-closed 合规边界；改成先泄露后修正不是免费性能优化。
- 不在本计划实现 LangGraph 真 token streaming。它需要改 `chain.invoke`、graph writer 和事件协议，是单独能力项目；BP-02 只修事件循环阻塞。
- 不把聊天写入改为默认 fire-and-forget，不缓存长期记忆 BM25，不迁移全量 AsyncSession；这些会引入丢数据、失效和大范围生命周期风险。
- 不节流 `_bm25_dataset_cache_version`，不移除 Milvus delete/write flush；前者保障跨进程失效，后者涉及 read-after-write/delete 可见性。
- 不改同步 retry sleep，不并发化当前无生产调用的 async embedding 批处理；现有 async retry 已使用 `asyncio.sleep`，未证明的路径不优化。
- 不做全局 query normalization memo、JSON→msgpack、默认并行度提升或客户端池大改；收益未量化，且可能增加 PII 缓存、内存、后端负载或兼容成本。
- 不新增评估指标、检录数据集或压测框架。若后续发现新的热点，必须先用现有 trace/call-count/事件循环测试证明，再进入新计划。

## 7. 风险与回滚

| 风险 | 防护 | 回滚条件 |
| --- | --- | --- |
| offload 后线程任务积压 | API 级继续使用现有 bounded gate，不提高默认并发 | queue 持续堆积或取消后任务不退出 |
| graph producer 泄漏或乱序 | 有界队列、停止信号、producer `finally`、事件序列测试 | 断连后有残留 worker 或 SSE 协议变化 |
| 第二次 enrichment 被错误跳过 | 使用 `_result_key` 集合，不用长度；覆盖同长度替换 | ACL/version/embedding-space 任一回归 |
| embedding 对象缓存过多或串配置 | 小容量 LRU，完整 frozen runtime 作键 | 内存不可控或配置/密钥串用 |
| 历史 PDF 页数缺失 | 先离线幂等回填，再移除请求 fallback | 已回填记录的 API 结果变化 |
| SQL 分页边界不稳定 | 时间字段 `coalesce` + `id` 唯一 tie-breaker | 跨页重复、遗漏或 total 不一致 |
