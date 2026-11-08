# Agent Note: 文档变更入口使用实际写入契约

Status: implemented

## Problem

五个批量文档路由用位置参数传递 `payload`，但服务入口只接收关键字参数，请求会在成员校验和逐文档结果处理之前失败。手工创建和修改 chunk 调用了活动 `Indexer` 不存在的 `sync_chunk_corpus`，异常被原有降级分支吸收。追加位置使用 `max_idx or -1`，把合法的最大索引零也当成空查询。文档版本删除在 KG 关系与事件索引的数据库提交失败后回滚却继续返回 204；向量、BM25 和审计旁路失败也没有任何日志，调用方与运维都无法区分完整清理和部分清理。

## Decision

批量路由明确传递 `payload=payload`。创建和修改 chunk 在原位置调用活动 `Indexer._update_bm25_for_chunks`，使用原有参数、异常分支和后续事务顺序。追加位置只把 SQL 聚合的 `None` 当成无记录；已有最大索引零后追加一。创建后的统计刷新复用同文件现有 helper，其完整查询、活动 pipeline 过滤、commit 和 rollback 代码与原内联块相同。

chunk 内部 helper 使用实际 ORM、Indexer 和元数据类型。索引 channel 服务直接读取模型字段，以及 `resolve_pipeline_effective` 通过 `_resolve_flag` 生成的五个布尔值。字段存在性属于这些生产者；nullable 值、原始 JSON、状态、错误和数字仍保留原有清理规则。SQLAlchemy PostgreSQL 语句使用实际 `Insert` 类型。

chunk 写入权限包装继续动态调用 `document_access_service.assert_document_writable_for_lifecycle`。唯一涉及测试的修改仅把旧 monkeypatch 目标迁到该实际所有者；不恢复已退出别名，不增改断言、用例或 helper。

文档版本删除把 DB chunk 删除继续作为第一笔权威提交；随后 KG 关系和事件索引的数据库清理必须提交成功，失败时 rollback 并向上抛出，不再伪造 204。向量和 BM25 属于可重建的派生索引，仍允许主清理继续，但每次失败都以带堆栈的 warning 暴露。激活与删除在主变更提交后共用本模块的审计 helper；审计仍是旁路，失败 rollback、记录 action 与 document_id 后不改变主操作结果。

QA 生成先提交新 chunks，再刷新 Document 的 `chunk_count` 与 `total_characters` 投影。统计提交失败只回滚这笔投影事务，不把已经成功的 QA 生成响应改成失败；原静默分支改为结构化 warning，明确依赖、失败原因和重算建议，并保留异常堆栈。

## Alternatives considered

为 `Indexer` 新增 `sync_chunk_corpus` 包装可以少改两个调用点，但会重新引入没有实现的接口归属。直接使用保留的活动方法能明确 BM25 所有者，也保留该方法既有的元数据和检索失效政策。

把缺失字段继续转换成默认值可以容忍不符合内部 ORM 或完整 pipeline 结果契约的对象；实际查询和生产者已提供这些字段，因此只保留值本身的 nullable 与原始数据防护。资源能力探测仍保留，因为 Session 的 dialect、savepoint 和直接回滚降级分支承担不同职责。

把 KG/事件清理也标成 best-effort 可以维持更高的表面成功率，但会留下无法从 204 响应识别的权威数据库残留。把向量和 BM25 失败改为阻断则能要求一次性完整清理，但这两个派生索引已有重建路径，且跨存储无法与 SQL 事务原子提交；保留可观测降级更符合现有边界。

## Consequences

批量操作可进入原有成员、ACL 和逐项结果逻辑；chunk 的 BM25 更新可到达现行实现，零索引追加计算正确。租户、dataset、文档、chunk、活动 pipeline、批次上限、重复输入和 mixed-outcome 规则保持。向量与 BM25 顺序、严格模式阻断时机、缓存与配额、channel 原子 SQL、计数和时间戳、savepoint、提交和回滚、错误清空与 summary 复制政策保持。版本删除的后段数据库清理失败现在表现为请求失败；前段 chunk 删除已经提交，因此调用方需要按失败响应触发运维修复，而不能把它当作未执行。派生索引、QA 统计投影和审计失败仍不逆转已提交的主操作，但日志提供明确的降级证据。

活跃笔记检索中，[活动索引写入所有者](../simplification/2026-11-05-active-indexing-owner.md) 与 BM25 方法归属部分重叠，沿用其活动实现并互链；[共享标量转换](../simplification/2026-11-03-shared-scalar-coercion-owner.md) 和[语料缓存事务](2026-11-03-corpus-cache-invalidation-transaction.md) 的边界和事务决定保持。检索命中的质量评分、混合排名和预览笔记属于其他生产者，不被替代。没有过时提案或可完全吸收的笔记。

验证使用固定 Git 源码、完整模块 AST、实际 DTO／ORM／Settings／pipeline／SDK 声明、静态调用绑定和 Ruff。测试文件仅做两项 patch 目标替换的完整 AST 与文本差异证明。按授权范围，Python 测试以及应用、ORM、索引、数据库、模型、网络和服务运行时均未执行，因此不声称运行时行为已验证。

2026-11-08 的版本删除增量核对完整调用链，运行 Python 3.14 源码编译、限定差异与空白检查及 Note 三项门禁。当前环境没有 Ruff，且依用户指令未新增或运行 Python 测试；数据库提交失败、派生索引失败和审计失败路径没有运行时回归证明。
