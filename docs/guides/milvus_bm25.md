# Milvus 原生 BM25

知识库的 BM25 文本编码、稀疏倒排索引和评分由 Milvus 2.6.11 提供。API 使用已有的 pymilvus 客户端发送原文，不加载模型，不构造 Python BM25，也不维护各个 worker 的完整 BM25 语料缓存。

## 存储与检索

全文集合默认是 `document_bm25`，使用同一规范分块 ID、正文和元数据；主键带租户前缀，查询和删除始终限定租户。集合使用中文 analyzer、BM25 function 及 `SPARSE_INVERTED_INDEX`。现有语义向量集合仍按模型和维度维护，因此 BM25 可以独立启用，迁移无需重新调用 Embedding。

检索沿原有通道融合、数据集/文档范围、元数据匹配和最终 ACL 裁剪流程运行。PostgreSQL 词法召回及关键词模式的优先级沿用[现有策略](./lexical_fallback.md)。复杂元数据会在有上限的原生候选窗口内严格裁剪；达到上限后可能少于请求的 top_k，可按实际查询调整候选上限。

```dotenv
VECTOR_BACKEND=milvus
BM25_INDEX_ENABLED=true
MILVUS_BM25_COLLECTION_NAME=document_bm25
MILVUS_BM25_TIMEOUT_SEC=10
MILVUS_BM25_MAX_CANDIDATES=2048
```

Milvus 的连接参数继续使用已有 `MILVUS_HOST`、`MILVUS_PORT`、`MILVUS_USER` 和 `MILVUS_PASSWORD`。Chroma、FAISS 等部署保留向量能力，BM25 通道显示需要 Milvus，不回退到进程内索引。

## 已有文档回填

在后端相同的虚拟环境与配置下运行；将 `TENANT_UUID`、`DATASET_UUID` 替换成实际 UUID。默认命令只读取 PostgreSQL 统计，不连接或修改 Milvus：

```bash
python scripts/backfill_milvus_bm25.py --tenant-id TENANT_UUID --dataset-id DATASET_UUID
```

核对 `published_chunks`、目标 `collection` 与 `within_rebuild_limit` 后，显式写入：

```bash
python scripts/backfill_milvus_bm25.py --tenant-id TENANT_UUID --dataset-id DATASET_UUID --batch-size 500 --apply
```

省略 `--dataset-id` 会覆盖该租户的可检索发布语料。回填排除草稿、禁用、归档和已退出流水线版本的分块，并沿用 `RETRIEVAL_REBUILD_MAX_CHUNKS` 上限；超限时应缩小范围或在维护窗口显式调整有界上限。写入按稳定分块 ID 幂等 upsert，空语料的显式回填会初始化空全文集合。

回填不删除或迁移已有语义向量，不调用模型服务，也不自动清理旧遗留全文记录。正常修改、禁用、删除、保留期和索引审计重放使用同一个原生全文所有者。跨 PostgreSQL/Milvus 的提交仍遵守既有索引一致性和失败重放政策。

成功的 apply 会按既有缓存修订机制更新所涉文档和数据集的更新时间，并提交该工具拥有的事务，使 API worker 的候选、语义和回答缓存使用新修订。dry-run 不修改这些时间戳；原生批次失败不会发布成功修订。

新上传可初始化原生集合，但不会替已有文档完成历史回填。在全文集合缺失或 schema/analyzer 不匹配时，检索返回 `BM25_INDEX_NOT_READY`（HTTP 503）；读取不会自动创建空集合并假称迁移完成。既有不匹配集合不会被覆盖，应显式配置新全文集合并回填。

切换全文集合时，API/worker 需要读取新配置后重新启动。可以先在同一后端环境为新集合完成回填，再切换服务配置；新集合名和候选配置会隔离旧的检索与回答缓存。

## 配置与依赖变化

- 移除 `rank-bm25` 和生产代码中的 BM25Retriever。
- 移除本地缓存、懒构建、启动重建相关的 `BM25_LAZY_BUILD_*`、`BM25_STARTUP_BUILD_*`、`BM25_EAGER_UPSERT_MAX_CHUNKS`、`BM25_CACHE_MAX_TENANTS`。
- 保留的 `BM25_TOKENIZE_*` 是轻量查询匹配、融合及聊天记忆的历史配置名；Milvus BM25 由集合 analyzer 分词。
- 聊天记忆只检索当前租户、当前会话的最近消息，由数据库关键词计分；无匹配不会补入无关历史，`LONG_TERM_MEMORY_MAX_MESSAGES` 必须大于零。

Milvus 的统计范围和 analyzer 与原进程内 BM25 不同，排序不保证逐项一致，应使用项目现有评测查询验证召回。当前虚拟环境里已安装的包不会因 requirements 变化自动卸载；使用新环境或重建镜像核对依赖和占用。
