# Agent Note: BM25 下沉 Milvus 并退出进程内语料索引

Status: implemented

## Problem

知识库在 Milvus 保存语义向量，同时由 API 进程加载分块并构造 Python BM25，维护每个租户、数据集和文档集合的缓存、懒构建和更新重建。写入端与查询端还分别保留 BM25 实现。聊天记忆为了排序近期历史再次构造 BM25。这些行为让多进程维护和检索冷启动复杂，并使 `rank-bm25` 依赖无法退出。

用户已确认将知识库 BM25 下沉 Milvus，保留模型服务、轻量关键词能力和其他向量后端，处理聊天记忆调用后删除本地 BM25 依赖。

## Decision

Milvus 2.6.11 的内置 BM25 function、中文 analyzer 和 sparse inverted index 承担全文索引及评分。直接复用已声明的 `pymilvus`，不新增 LangChain 适配包或模型依赖。知识库召回继续沿现有通道融合、诊断及最终权限裁剪链路。

全文使用独立的 `MILVUS_BM25_COLLECTION_NAME` 集合，存储同一规范分块 ID、正文及元数据，主键加租户前缀。这个实现选择保留 BM25 独立开启、不同维度/模型的语义集合和 BM25-only 流水线；不修改现有语义集合或重新调用 Embedding。租户约束始终进入服务端表达式，数据集、文档及可表达的元数据约束同步下推；其余复杂元数据沿现有 matcher 严格后置裁剪，在有上限的候选窗口内扩展，不能因过滤失败改用无约束查询。删除只允许显式租户和非空过滤，不扫描本地语料。

`CorpusIndex` 是写入、查询、回填与派生测试索引的唯一所有者。退出 BM25 的本地语料缓存、构造、锁、懒加载和启动重建，旧公共调用转到该所有者。保留的确定性 sparse/ColBERT 仅在明确使用时从数据库读取有界的发布语料，不借 BM25 缓存作为数据源。索引服务不导入查询 retriever。Chroma/FAISS 不创建或使用本地 BM25，能力和状态必须说明 Milvus 要求。

读操作不创建集合；集合缺失或 schema/analyzer 不匹配时给出显式回填/迁移错误。正常写入可创建符合版本约定的新集合，既有 schema 不自动覆盖。已有文档通过显式的有界、分批回填命令写入全文集合；命令提供默认 dry-run 和明确 apply，不删除已有向量或自动执行线上迁移。回填按分块 ID 幂等 upsert，保留既有索引审计和失败重放入口，不假称 PostgreSQL 与 Milvus 具备跨库事务。

聊天记忆继续以 PostgreSQL 中当前租户、当前会话的最近有界历史为来源，用数据库关键词匹配计分并按新旧排序。不建立额外的 Milvus 消息副本；空查询或无匹配不制造相关记忆。jieba 及既有轻量文本分词保留。

## Alternatives considered

- 继续保留 API 内 BM25：无需数据回填，也适用于其他向量后端；但长期语料缓存和多进程重建正是本次收窄的目标。
- 把全文字段加入每个语义向量集合：正文可以物理共用；但模型/维度分片、独立索引开关及旧集合迁移会耦合，扩大本次迁移范围。独立全文集合仍由同一 Milvus 服务维护。
- 将聊天记忆也复制到 Milvus：能够继续使用 BM25；但需要新增消息写入、更新、删除及保留期同步，收益不足以支撑第二套消息索引。

## Testing

- 生产源码不再导入或构造 BM25Retriever，基础依赖移除 rank-bm25。
- 原生 schema、中文 analyzer、BM25 function、稀疏索引及文本查询参数经过 SDK 契约验证；不在 API 计算 sparse 权重。
- 租户、数据集、文档、元数据和删除约束有真实边界测试；服务故障、缺少集合和不匹配 schema 明确可见。
- 实际 CorpusIndex、索引写入和通道融合接到同一原生 owner；默认 Milvus、非 Milvus、空索引、更新和删除行为被覆盖。
- PostgreSQL 聊天记忆覆盖租户/会话隔离、近期上限、中文、字面通配符及无匹配。
- 提供显式回填命令和安装/迁移说明；不自动访问或变更现有索引。验证报告区分 SDK/单测与真实服务验收。

原生存储、实际通道、HTTP 错误、SQLAlchemy 数据库和聊天记忆的 33 项定向检查通过。完整选定的 35 个后端文件有 340 项通过，42 个已在原树复现的旧失败另列。回填的禁用、归档、旧流水线过滤先以五条错误结果复现，再验证只写入一条当前有效分块；查询端不能吞掉缺少全文集合或 schema 不匹配的错误。

## Consequences

Milvus 的统计范围和中文 analyzer 与原 rank-bm25/jieba 不同，排序需要按现有检索评测回归。已有数据在回填之前不能假称全文索引完整。独立全文集合增加一份持久正文，但退出各个 API worker 的常驻语料和 BM25 对象。

当前环境的 Milvus 端点探测超时，没有启动服务或执行真实索引/中文召回/性能验收。SDK 检查在临时目录使用真实 pymilvus 2.6.11 和已有基础依赖，未给 SDK 安装 model extras，也未修改原虚拟环境。具体检查、基线失败及后续迁移入口见[验证记录](../../../../docs/development/milvus-bm25-verification.md)。

历史笔记检索结果：[本地模型退出](../../implemented/architecture/2026-11-05-retire-in-process-models.md)和[可选依赖](../../implemented/process/2026-11-05-optional-model-vector-dependencies.md)关于保留 rank-bm25 的决定由本篇部分取代；[语料事务](../../implemented/bug-fix/2026-11-03-corpus-cache-invalidation-transaction.md)的事务与版本 token 所有权保持；[语料内部值](../../implemented/simplification/2026-11-05-retrieval-corpus-owned-values.md)的 BM25 构建细节随实现退出，其他索引内部值约定保持。没有可完全吸收的笔记或过时提案。
