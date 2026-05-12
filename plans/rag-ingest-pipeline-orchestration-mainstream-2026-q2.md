# RAG 入库 Pipeline 编排与工程化主流方案调研 — 2026-Q2

> 用户:深入调研 RAG 系统**入库前**端到端 pipeline — `解析 → 治理 → 切块 → 入库`(parsing → governance → chunking → indexing)。不重复既有 plan 的单点深度(`rag-parsing-chunking-deep-dive` / `rag-data-cleaning-rules` / `rag-pre-poc-scanner` / `industry-rules-productization` 等),本份聚焦**编排、状态机、重试/DLQ、增量、进度报告、Cache、Lineage、并发**等**工程化层面**。

---

## 1. Context

### 1.1 起因

MimirQ 解析(70+ chunking strategies / parsing 5539 行 processor)+ 治理(preprocessing ~5500 行 + governance rule packs)+ 切块(factory + 75 strategies)+ 入库(indexer 1627 行 + Milvus + BM25)**单点能力一流**,但**端到端 pipeline 编排层薄弱**:
- 状态机仅 4 档扁平 `pending|processing|completed|failed`,**无 stage 颗粒度**(看不出卡在哪个阶段)
- 仅 `vector_write` 一阶段有 retry+exponential backoff,**parse/chunk/embed 失败无重试,无 DLQ**
- 没有 task queue(grep `celery|dramatiq|rq` 全 0),纯 asyncio + DB 状态推进,**worker 死了就丢任务**
- 进度报告颗粒粗(document 终态比例),**stage 级进度无暴露**
- `pipeline_provenance_service.py` 331 行已有,但**不符 OpenLineage 标准**,客户拉不出标准化 lineage
- 没有 Pipeline as code 的"transformations 链"(对照 LlamaIndex IngestionPipeline)
- 没有"hash 输入 + 跳过已处理"cache(每次 reingest 全量重跑)

### 1.2 调研问题

1. LlamaIndex `IngestionPipeline` 的 transformations + cache + docstore upsert 三件套是不是工业级最佳实践?
2. 增量 ingest 怎么做?业界用 content hash + per-stage cache 还是 last_modified + 标志位?
3. DLQ(死信队列)在 RAG ingest 该怎么落地?Permanent vs transient 怎么分?
4. 多 worker 并发 + 失败隔离怎么做?Celery / Dramatiq / asyncio?
5. OpenLineage 在 RAG pipeline 的接入方式?
6. RAGFlow 0.21 visual Ingestion Pipeline 值不值得借鉴?
7. 蓝绿迁移(`EMBEDDING_SHADOW_*`)真跑过吗?

---

## 2. MimirQ 现状盘点

### 2.1 入库 Pipeline 核心文件

| 文件 | 行数 | 角色 |
|---|---|---|
| `app/parsing/processors/processor.py` | **5539** | 解析处理器(超大!) |
| `app/services/indexer.py` | **1627** | 索引器(向量+BM25 写入) |
| `app/services/ingestion_run_service.py` | 429 | ingest run 状态管理 |
| `app/services/pipeline_provenance_service.py` | 331 | 自研 provenance(非 OpenLineage) |
| `app/services/ingestion_policy.py` | 314 | ingest 策略 |
| `app/services/pipeline_config.py` | **1109** | pipeline 配置 |
| `app/services/embedding_migration.py` | ? | 蓝绿迁移已实现 |
| `app/services/ingestion_dashboard_service.py` | ? | 监控仪表板 |
| `app/services/ingestion_prometheus_metrics.py` | 129 | Prometheus 指标 |
| `app/api/v1/document_processing.py` | 500 | 处理 API(get_status / cancel / retry / delete) |
| `app/api/v1/document_batch_upload.py` | 81 | 批量上传 |
| `app/api/v1/document_batches.py` | 363 | 批管理 |
| `app/api/v1/document_batches_lifecycle.py` | 288 | 批生命周期 |
| `app/services/dataset_precheck_scan_runner.py` | 1924 | Pre-POC 扫描 |
| `app/services/dataset_profile_service.py` | 1579 | 数据 profile |

### 2.2 关键现状判断(实测)

| 维度 | 现状 | 业界对照 |
|---|---|---|
| **状态机** | `pending\|processing\|completed\|failed` 扁平 4 档(`document.py:74`)| LlamaIndex docstore upsert 三策略 + stage-level state |
| **Stage 进度** | 文档终态比例(0-100%),仅文档级 | RAGFlow per-stage progress + per-component status |
| **重试** | ✅ vector_write 单 stage `VECTOR_WRITE_RETRY_BACKOFF_SEC` exp backoff(`indexer.py:1347-1383`)| 全 stage retry budget + transient/permanent 分类 |
| **DLQ** | ❌ 无 | Kafka @RetryableTopic 多 tier(1s/2s/4s/dlt) |
| **任务队列** | ❌ 无 Celery/Dramatiq/RQ,纯 asyncio + DB 推进 | Celery / Dramatiq + Redis broker 是工业标准 |
| **Content hash 去重** | ✅ sha256 `indexer.py:238-241` | LlamaIndex docstore + hash 完全对齐 |
| **增量 ingest** | ✅ web_crawler.py 38 行有 fingerprint + dataset_precheck_scan_runner.py:867 有 incremental scan | per-stage cache(LlamaIndex 标准)缺失 |
| **Stage cache(input hash → skip)** | ❌ 无 | LlamaIndex 每个 transformation 输入 hash 缓存,重跑直接读 |
| **Pipeline as code** | △ pipeline_config.py 1109 行 | LlamaIndex IngestionPipeline / RAGFlow Agent-based |
| **Provenance / Lineage** | △ 自研 331 行,**非 OpenLineage** | OpenLineage + Marquez 工业标准 |
| **双写蓝绿** | ✅ embedding_migration.py 完整 | 业界对齐 |
| **Prometheus 指标** | ✅ ingestion_prometheus_metrics.py 129 行 | ✅ |
| **可视化编排** | ❌ 后端纯代码 | RAGFlow 0.21 visual Ingestion Pipeline / Dagster UI |

### 2.3 关键短板汇总

🔴 **任务队列缺失**:asyncio worker 死后任务丢,不可恢复
🔴 **状态机扁平**:卡在 parse/chunk/embed 哪一步看不到
🔴 **Stage 级重试缺**:只有 vector_write 重试,parse/chunk/embed 失败直接 failed,不重试
🔴 **无 DLQ**:permanent error 没地方去,失败任务在 DB 标 failed 就完了,无 replay 机制
🟠 **Stage cache 缺**:同一文档重跑全量重做,parse 已 OK 也要重 parse
🟠 **Provenance 非标准**:自研 331 行,客户合规审计无法对接 OpenLineage 生态
🟠 **Pipeline 不可编排**:1109 行 pipeline_config.py 是过程式配置,**不是声明式 transformations 链**

---

## 3. 业界主流 5 大编排范式

### 3.1 LlamaIndex IngestionPipeline(声明式 transformations 链 + cache + docstore)

**核心抽象**:

```python
pipeline = IngestionPipeline(
    transformations=[
        SentenceSplitter(chunk_size=512),
        TitleExtractor(),
        OpenAIEmbedding(),
    ],
    docstore=docstore,         # 用 doc_id + content_hash 检测重复
    vector_store=vector_store, # 自动写入
    cache=cache,               # 每 transformation 输入 hash 缓存
)
nodes = pipeline.run(documents=[...], num_workers=4)
```

**Docstore 三档策略**:
1. **upserts**:文档变更 → 重处理 + upsert
2. **duplicates_only**:仅去重,不更新
3. **upserts_and_delete**:upsert + 删除源端不存在的(适合全量同步)

**Cache 机制**(关键!MimirQ 缺失):
> Each node + transformation combination is hashed and cached. Subsequent runs with the same node+transformation use cached result.

Redis 后端可让 cache + docstore + vector_store 三套统一在 Redis 上。

**MimirQ 落地建议**:
- 把 1109 行 `pipeline_config.py` 抽象成声明式 `transformations: list[Transformation]`
- 实现 `IngestionPipelineCache`(Redis 或 SQL):key = `sha256(input_node + transformation_signature)`,value = output_node
- 每文档进入 pipeline 前先查 `docstore[doc_id].content_hash`,匹配则 skip

### 3.2 RAGFlow 0.21 Ingestion Pipeline(Agent-based + 可视化)

**2025-Q3 发布的新版**:
- 基于 Agent framework 的可编排 pipeline
- 用户在 UI 上**拖拽编排** parser / cleaner / chunker / embedder
- 每个 component 是 Agent,可替换、可并行
- **Parse stage 内置 DeepDoc**(与 MimirQ 同栈,巧合)

**RAGFlow 演进方向**:Context Engine / Context Platform — 不再是检索工具,而是 AI 应用的 context 装配基建。

**MimirQ 落地建议**(P1-P2):
- 前端补 `/governance/pipeline-designer`(对照 RAGFlow visual)
- 后端 `transformations` 抽象到 Agent 接口,与现有 `app/rag/agents/` 复用

### 3.3 Unstructured.io 范式(专注 unstructured 预处理)

**定位差异**(关键洞察):
> Classic ETL(Airbyte/Fivetran)的 connector 不能直接用在 GenAI,因为它们**为结构化数据设计**,缺乏 unstructured 的高级 transformation 能力。

**Unstructured.io 提供**:
- ~75 个 connector 专攻 unstructured(SharePoint / Confluence / Notion / GitHub / S3 / Slack / Google Drive)
- 与 Milvus 原生集成 + Elasticsearch 集成
- 文档解析 + 元数据保留 + chunking 一站

**MimirQ 现状**:`app/connectors/base.py` ABC 已存在,但 MEMORY 记"仅 db/ 一种实现,其他连接器待补"——这正是 Unstructured.io 解决的痛点。

**MimirQ 落地建议**(P0-P1 与已有 connector 扩展 plan 协同):
- 不需要自研 connector 全栈,可直接走 Unstructured.io 客户端嵌入 MimirQ pipeline(MIT license 部分组件可用)
- 或参考 Unstructured.io 架构补 SharePoint/Confluence/Notion/GitHub/S3 五个 P0 connector

### 3.4 Airbyte(connector 数量第一,但通用 ETL)

- 550+ pre-built connectors
- 开源,可自部署
- 缺点:为结构化数据设计,对 unstructured 不专攻
- 与 Milvus 有官方 connector

**MimirQ 取舍**:大语料离线导入场景考虑(GitHub repo / S3 全量 backfill),但实时 ingest 不用 Airbyte。

### 3.5 Cognita(KG-heavy,合规专项)

- 多模态深知识专项,医疗/法律
- 与 MimirQ KG 栈定位重叠,**不作主要借鉴**
- 但其"Knowledge Graph + RAG 一体"思路值得 P2 调研对照

---

## 4. 增量更新与 Dedup 设计模式

### 4.1 三档策略(业界共识)

| 策略 | 适用 | MimirQ 现状 |
|---|---|---|
| **全量重建** | 小 KB(<1 万文档),offline cron | ✅ 现状默认走这条 |
| **增量更新**(基于变更检测) | 中大 KB,频繁更新 | △ web_crawler 部分实现,统一不够 |
| **混合**(频繁增量 + 周期全量) | 大企业 | ❌ 调度未实现 |

### 4.2 变更检测的双重信号

```
source_metadata.last_modified  → 信任度高(Git/SharePoint 等可信)
        ↓ 不可信时
content_hash(sha256/blake3)    → 兜底,内容字节级对比
```

**MimirQ ✅ 已有 content_hash**(`indexer.py:238`),但是否在 ingest 入口先查 docstore 跳过未变?需要核验 `pipeline_config.py` 1109 行流程。

### 4.3 Chunk 级版本

- 每 chunk 一个 `chunk_id`(stable,基于 doc_id + chunk_index + content_hash)
- 加 `version` 或 `created_at` metadata
- 检索期 filter 最新 version
- 旧 version 保留 7-14 天,过期清理(防 index bloat)

**MimirQ 现状**:`document_version_diff_service.py:33` `content_hash_multiset_diff` 有 chunk diff 算法,但是否走 chunk 级 upsert 还是文档级 replace?需要核查。

### 4.4 60% RAG 失败归因 stale data

引述 Markaicode 2025:**Over 60% of RAG failures in production are attributable to stale or outdated knowledge base.**

**MimirQ 启示**:增量 ingest 不是"性能优化",是"产品正确性"——P0 优先级。

### 4.5 Schema 演化(数据库源)

> Schema drift management:source 数据库新增/重命名列,pipeline 自动检测 + adjust mapping,不阻塞 ingestion。

**MimirQ ✅ 已部分实现**:`db_catalog_schema_doc_service.py` + connector 框架,但 schema 演化是否触发自动 re-ingest?P1 验证。

---

## 5. 失败处理与 DLQ 工程化

### 5.1 错误分类(关键设计决策)

| 类型 | 例子 | 处理 |
|---|---|---|
| **Transient**(临时) | 网络超时 / 5xx / DB lock / LLM 限流 | **重试 with exp backoff + jitter** |
| **Permanent**(永久) | schema violation / 401/403 / 文件损坏 / OOM | **立即进 DLQ**,不重试 |
| **Poison**(毒丸) | 重试 N 次仍失败 | DLQ + 标 require_human_review |

**MimirQ 现状**:仅 vector_write 重试,**未做 transient/permanent 分类**,所有失败一律 `status=failed`。

### 5.2 DLQ 实现模式

**Kafka @RetryableTopic 多 tier**:
```
order        ← 主 topic
order-retry-0(delay=1s)
order-retry-1(delay=2s)
order-retry-2(delay=4s)
order-dlt    ← 死信,人工 triage
```

**MimirQ 落地建议(无 Kafka)**:
- 用 Postgres 表 + `next_retry_at` 字段实现 retry 拓扑
- DLQ = 独立表 `ingest_dead_letters`,带 `original_payload`/`error_code`/`first_failed_at`/`last_attempt_at`/`retry_count`
- 前端 `/quarantine` 页已有(MEMORY 提到 2114 行),**直接接 DLQ 数据源**

### 5.3 重试 budget(业界经验)

```
max_attempts = 5
delays = [1m, 5m, 15m, 1h, 6h]   # 给依赖服务恢复时间
+ jitter ±10%                     # 防同步重试 storm
```

### 5.4 元数据(每个失败任务必带)

```json
{
  "task_id": "uuid",
  "doc_id": "uuid",
  "tenant_id": "uuid",
  "stage": "parse | clean | chunk | embed | index",
  "attempt": 3,
  "error_code": "PARSE_TIMEOUT",
  "error_message": "...",
  "first_failed_at": "ISO-8601",
  "last_attempt_at": "ISO-8601",
  "next_retry_at": "ISO-8601 | null (= DLQ)",
  "schema_version": "v1.0",
  "producer_service": "parsing.processor",
  "source_blob_url": "..."
}
```

### 5.5 安全 Replay 工作流

```
DLQ → filter by error_code/time_window
   → dry-run validation
   → rate-limited replay(避免下游 overload)
   → 监控 DLQ depth/age/top-N reasons
```

---

## 6. Stage 状态机细化(MimirQ 当前 4 档 → 业界 ~15 档)

### 6.1 建议状态机

```
                          ┌─────────────┐
                          │   PENDING   │
                          └──────┬──────┘
                                 │
            ┌────────────────────┴───────────────────┐
            │                                        │
       ┌────▼────┐                            ┌──────▼─────┐
       │ PARSING │ ─── FAILED ──────────────► │   FAILED   │
       └────┬────┘                            │  + DLQ     │
            │                                  └─────▲──────┘
       ┌────▼────┐                                   │
       │ PARSED  │                                   │
       └────┬────┘                                   │
            │                                         │
       ┌────▼─────┐                                   │
       │ CLEANING │ ──── FAILED ──────────────────────┤
       └────┬─────┘                                   │
            │                                         │
       ┌────▼────┐                                    │
       │CLEANED  │                                    │
       └────┬────┘                                    │
            │                                         │
       ┌────▼─────┐                                   │
       │CHUNKING  │ ──── FAILED ──────────────────────┤
       └────┬─────┘                                   │
            │                                         │
       ┌────▼─────┐                                   │
       │ CHUNKED  │                                   │
       └────┬─────┘                                   │
            │                                         │
       ┌────▼──────┐                                  │
       │EMBEDDING  │ ──── FAILED ─────────────────────┤
       └────┬──────┘                                  │
            │                                         │
       ┌────▼──────┐                                  │
       │ EMBEDDED  │                                  │
       └────┬──────┘                                  │
            │                                         │
       ┌────▼──────┐                                  │
       │ INDEXING  │ ──── FAILED ─────────────────────┘
       └────┬──────┘
            │
       ┌────▼──────┐
       │ COMPLETED │
       └───────────┘
```

**关键设计**:
- 每个动名词态(`PARSING`/`CHUNKING` 等)= worker 持有任务时的状态
- 每个过去态(`PARSED`/`CHUNKED`)= 该 stage 完成,等下游 worker 来 claim
- `FAILED` 始终携带 `failed_stage` 字段,便于按 stage 重试
- `CANCELLED`(用户主动取消)与 `FAILED` 分离

**与现状对照**:`document.py:74` `status='pending|processing|completed|failed'` 4 档 → 升级 ~12 档 + `failed_stage` 字段。

### 6.2 Stage 颗粒进度(前端透出)

```
parse:    [████████░░] 80% (4/5 pages)
clean:    [░░░░░░░░░░] 0%
chunk:    [░░░░░░░░░░] 0%
embed:    [░░░░░░░░░░] 0%
index:    [░░░░░░░░░░] 0%
total:    [██░░░░░░░░] 16%
```

对照 MEMORY `rag-ingestion-frontend-deep-dive` plan 的"stage 时间线 echarts gantt"。

---

## 7. 任务队列与并发模型

### 7.1 三大候选

| 方案 | 优势 | 劣势 | 推荐 |
|---|---|---|---|
| **Celery + Redis** | 工业标准,中间件成熟 | 配置复杂,Python 异步生态略生疏 | △ |
| **Dramatiq + Redis** | 比 Celery 简单,async 友好 | 社区比 Celery 小 | ★ **推荐** |
| **自研 asyncio + Postgres `SELECT FOR UPDATE SKIP LOCKED`** | 零依赖,事务自带 | 多 worker 调度需要写好(否则惊群) | ✅ 大公司用过 |
| 当前 MimirQ:asyncio + DB | 简单,但 worker 死任务丢 | 灾难恢复差 | ❌ |

### 7.2 选型建议

P0 走 **asyncio + Postgres `FOR UPDATE SKIP LOCKED`**(零新依赖,平滑升级现状):
```sql
UPDATE document_processing_tasks
SET status = 'parsing', claimed_by = $worker_id, claimed_at = now()
WHERE id = (
    SELECT id FROM document_processing_tasks
    WHERE status = 'pending'
    ORDER BY priority DESC, created_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
RETURNING *;
```

P1 视客户语料量决定是否上 Dramatiq(>100k docs/day 才需要)。

### 7.3 失败隔离(worker 隔离 + bulkhead)

- 每 stage 独立 worker pool(`parser_workers=4` / `embedder_workers=8` 等)
- 一个 stage 慢/挂不阻塞另一个 stage(避免 head-of-line blocking)
- LLM rate limit 单独 backoff,不影响 parse/chunk

---

## 8. OpenLineage 接入(替代 pipeline_provenance_service 自研 331 行)

### 8.1 OpenLineage 核心模型

```
RunEvent {
  job: {namespace, name},           # ingest_pipeline.parse_document
  run: {runId, facets},
  inputs: [Dataset...],              # source PDF / SharePoint URL
  outputs: [Dataset...],             # Milvus collection / BM25 index
  eventTime, eventType (START/COMPLETE/FAIL)
}
```

### 8.2 落地架构

```
MimirQ ingest worker
       │ emit OpenLineage event
       ▼
Marquez(参考实现,Apache 2.0)
       │
       ▼
客户合规审计 + Datadog / Grafana 集成
```

**MimirQ 落地建议**:
- `pipeline_provenance_service.py` 331 行**保留为内部** API
- 新增 `app/observability/openlineage_emitter.py`,在 stage 进出时 emit `RunEvent`
- 接 Marquez self-host(MIT license)给合规客户用

### 8.3 自定义 facet(MimirQ 专属)

```python
@facet
class RAGChunkingFacet:
    strategy: str               # laws_structured / sop_steps / etc.
    chunk_count: int
    avg_chunk_chars: int
    parent_child_enabled: bool
```

让客户 lineage 不仅看到"文件 X → Milvus Y",还能看到中间 chunking 策略选择。

---

## 9. P0 / P1 / P2 推荐

### 9.1 P0(3-4 周,工程基建底线)

| 任务 | 落点 | 估算 |
|---|---|---|
| **状态机升级**:4 档 → ~12 档 + `failed_stage` 字段;迁移已有数据 | `app/models/document.py:74` + alembic | 1.5 day |
| **Postgres `FOR UPDATE SKIP LOCKED` 任务队列**:新表 `document_processing_tasks` + worker loop + claim 机制 | new `app/services/task_queue.py` + `document_processing.py` | 2 day |
| **Stage 级 retry budget**:`max_attempts=5` 1m/5m/15m/1h/6h + transient/permanent 分类 | `app/services/indexer.py` 扩展 + 新建通用 retry decorator | 2 day |
| **DLQ 表 + replay API**:`ingest_dead_letters` 表 + `/document/dead-letters` endpoint + 接前端 `/quarantine` | new alembic + endpoint | 1.5 day |
| **Stage cache(input hash → skip)**:Redis backend,key = `sha256(input + transformation_signature)`,跳过 already-processed | new `app/rag/preprocessing/stage_cache.py` | 2 day |
| **`docstore` upsert 三策略**:upserts / duplicates_only / upserts_and_delete | 接入 `app/services/indexer.py` | 1 day |
| **Stage 颗粒进度报告**:`ingestion_run_service.py` 加每 stage 进度,前端 SSE 推 | `ingestion_run_service.py:171-336` 扩 + 前端 | 1.5 day |
| **`pipeline_config.py` 1109 行重构**:抽 `Transformation` ABC + 声明式 chain(对照 LlamaIndex) | refactor | 3 day |
| **失败诊断 trace**:每个 failed task 带 `failed_stage` + `error_code` + `producer_service` + `schema_version`,trace SSE 透出 | `task_queue.py` + frontend | 1 day |

### 9.2 P1(1 个月,标准化 + 蓝绿 + connector)

1. **OpenLineage emitter**:`app/observability/openlineage_emitter.py`(对照 §8)+ 自部 Marquez(MIT)
2. **`EMBEDDING_SHADOW_*` 蓝绿真跑一次**:1k 文档双写 + 一致性 audit + 切换报告
3. **5 个 P0 connector**(SharePoint / Confluence / Notion / GitHub / S3)— 与 MEMORY 中 connector 战略协同
4. **Stage cache 落地 Redis**:Stage cache(P0 占位)→ 真实 Redis 后端 + TTL + size cap
5. **`/governance/pipeline-designer`**:visual pipeline 编辑器(对照 RAGFlow 0.21)
6. **增量 ingest 调度器**:把 dataset_precheck_scan_runner.py:867 的"reuse unchanged"扩成统一调度,所有 connector 走 incremental-first
7. **DLQ 监控**:`/observability/dlq-dashboard` — depth / age / top-N error_code,接 Prometheus alert

### 9.3 P2(独立调研)

| 项 | 内容 |
|---|---|
| Dramatiq + Redis 接入 | 客户语料 > 100k docs/day 触发 |
| Cognita 路线对照 | KG-heavy 客户场景(医疗/法律深知识)|
| Airbyte 离线 backfill 集成 | 大批量历史数据导入场景 |
| Hamilton + OpenLineage Python lineage | 单线程 lineage 自动追踪 |
| RAGFlow 0.21 visual pipeline 移植 | Q4 产品差异化 |
| **客户合规 lineage 报告**(单文件 HTML,对齐 PoC FILE_A023 原则)| 给法务 / 监管交付 |

### 9.4 不该做的事

- ❌ **不要在 P0 上 Celery**:多一个中间件 = 多一个故障点,Postgres `FOR UPDATE SKIP LOCKED` 够用
- ❌ **不要把 retry 写在 indexer.py 内部**:抽通用 decorator,所有 stage 复用
- ❌ **不要把 DLQ 设计成 in-memory queue**:必须 DB 持久化,服务重启不丢
- ❌ **不要先做 visual pipeline 编辑器**:声明式 transformations chain 跑通了再做 UI
- ❌ **不要立刻替换自研 provenance**:`pipeline_provenance_service.py` 331 行保留,OpenLineage 增量接入(两套并存 6 个月)

---

## 10. 关键文件清单(将动)

### 后端 P0
- `app/models/document.py:74`(status 4 档 → 12 档 + failed_stage 字段)
- `alembic/versions/0015_pipeline_state_machine.py`(new,迁移 + DLQ 表)
- `app/services/task_queue.py`(new,Postgres FOR UPDATE SKIP LOCKED)
- `app/services/retry_decorator.py`(new,transient/permanent 分类 + exp backoff)
- `app/services/indexer.py:1347-1383`(改走通用 retry decorator)
- `app/rag/preprocessing/stage_cache.py`(new,Redis-backed)
- `app/services/ingestion_run_service.py:171-336`(扩 stage 进度)
- `app/services/pipeline_config.py:1`(1109 → 重构声明式 Transformation chain)
- `app/api/v1/document_processing.py`(加 retry by stage + DLQ replay)
- `app/api/v1/document_dead_letters.py`(new endpoint)

### P1
- `app/observability/openlineage_emitter.py`(new)
- `app/connectors/{sharepoint,confluence,notion,github,s3}.py`(new,5 个 connector)
- `app/services/incremental_scheduler.py`(new)

### 前端 P0
- `web/components/ingestion/stage-progress-tracker.tsx`(new,每 stage 进度条)
- `web/components/ingestion/failed-stage-badge.tsx`(new,显示卡在哪 stage)
- `web/app/knowledge/quarantine/page.tsx`(2720 行,扩 DLQ 数据源)
- `web/components/ingestion/dlq-replay-dialog.tsx`(new,人工 replay 工作流)

### 前端 P1
- `web/app/governance/pipeline-designer/page.tsx`(new,visual pipeline 编辑器)
- `web/app/observability/dlq-dashboard/page.tsx`(new)
- `web/app/observability/lineage-graph/page.tsx`(new,OpenLineage 可视化)

### 测试
- `tests/test_task_queue_for_update_skip_locked.py`(new,并发 claim 不重复)
- `tests/test_retry_decorator_transient_vs_permanent.py`(new)
- `tests/test_stage_cache_skip_already_processed.py`(new)
- `tests/test_dlq_replay_idempotency.py`(new)
- `tests/test_stage_state_machine_transitions.py`(new)
- `tests/test_openlineage_emitter_facets.py`(new P1)

---

## 11. 验证

### 11.1 P0 验证

1. `pytest tests/test_task_queue* tests/test_retry_decorator* tests/test_stage_cache* tests/test_dlq* tests/test_stage_state_machine*` 全绿
2. **任务队列并发安全**:开 8 worker 同时 claim 100 任务,无重复(P0 必达)
3. **状态机迁移**:历史 `pending|processing|completed|failed` 4 档数据迁移到新 12 档,**0 数据丢失**
4. **Stage 级 retry**:模拟 parse 失败 3 次后成功,验证文档最终 `COMPLETED`,trace 记录 3 次 attempts
5. **DLQ 流转**:模拟 parse 永久失败,验证落 DLQ + `/quarantine` 页能看到 + replay 成功
6. **Stage cache 命中**:同一文档第二次 ingest,**parse stage 应命中 cache 跳过**,P50 时延降 ≥ 50%
7. **Docstore upserts_and_delete**:模拟源端删 10 文档,验证下次同步时这 10 文档从 docstore + vector_store 一起清掉
8. **前端 SSE**:`/datasets/[id]/ingestion` 页能看到 stage 颗粒进度 + failed_stage 徽标

### 11.2 P1 验证

1. **OpenLineage**:Marquez UI 显示完整 lineage graph(source PDF → Milvus collection + BM25 + KG)
2. **蓝绿迁移**:1k 文档双写 一致性 ≥ 99.9%
3. **5 个 connector**:SharePoint/Confluence/Notion/GitHub/S3 各跑通 50 文档 incremental ingest
4. **DLQ dashboard**:depth / age P50/P95 / top-5 error_code 显示
5. **可视化 pipeline**:用户在 UI 拖出 parse → clean → chunk → embed → index,跑通一次

### 11.3 回归(不变性)

- 现有 `pipeline_provenance_service.py` 331 行行为不变(P1 OpenLineage 并存)
- `EMBEDDING_SHADOW_*` 配置项继续工作
- `dataset_precheck_scan_runner.py:867` 已有的 incremental scan 行为不变
- Milvus + BM25 双写不变

---

## 12. 与既有 plan 的关系

**不重复 / 互补**:
- `rag-parsing-chunking-deep-dive-2026-q2.md`:单点 parse/chunk 深度;本 plan 是它们的**编排层**
- `rag-data-cleaning-rules-mainstream-2026-q2.md`:cleaning 单点;本 plan 是它的**pipeline 接入**
- `rag-pre-poc-scanner-2026-q2.md`:入库前预检;本 plan 包**预检之后**的 5 stage
- `rag-ingestion-frontend-deep-dive-2026-q2.md`:前端;本 plan 主要管后端基建,**前端列出但简略**
- `rag-quarantine-frontend-deep-dive-2026-q2.md`:隔离审核前端;本 plan 给它**真实 DLQ 数据源**

**协同**:
- `rag-embedding-models-mainstream-2026-q2.md`(刚写):embedding 切换 + 双写 — 本 plan 实现双写 worker
- `industry-rules-productization-2026-q2.md`:industry rules 是 cleaning 阶段一个 transformation,接入本 plan 的声明式 chain

---

## Sources

### LlamaIndex / Pipeline
- [Ingestion Pipeline — LlamaIndex Docs](https://docs.llamaindex.ai/en/stable/module_guides/loading/ingestion_pipeline/)
- [Ingestion Pipeline + Document Management — LlamaIndex Examples](https://developers.llamaindex.ai/python/examples/ingestion/document_management_pipeline/)
- [Advanced Ingestion Pipeline — LlamaIndex](https://docs.llamaindex.ai/en/stable/examples/ingestion/advanced_ingestion_pipeline/)
- [LlamaIndex Ingestion Pipeline — ClusteredBytes 2024](https://clusteredbytes.pages.dev/posts/2024/llamaindex-ingestion-pipeline/)
- [llama-index-core/llama_index/core/ingestion/pipeline.py — GitHub](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/ingestion/pipeline.py)

### RAGFlow / Unstructured / Airbyte / Cognita
- [RAGFlow 0.21.0 Ingestion Pipeline — RAGFlow Blog](https://ragflow.io/blog/ragflow-0.21.0-ingestion-pipeline-long-context-rag-and-admin-cli)
- [From RAG to Context — 2025 year-end review — RAGFlow](https://ragflow.io/blog/rag-review-2025-from-rag-to-context)
- [GenAI Data Connectors Compared — Unstructured.io](https://unstructured.io/blog/market-map-of-data-connectors-for-the-genai-ecosystem)
- [Unstructured.io for Elasticsearch & RAG — Elastic](https://www.elastic.co/search-labs/integrations/unstructured-io)
- [Best Practices for Implementing RAG in Production — Unstructured.io](https://unstructured.io/insights/rag-systems-best-practices-unstructured-data-pipeline)
- [Best RAG Frameworks 2025 — Latenode](https://latenode.com/blog/ai/frameworks-tech/best-rag-frameworks-2025-complete-enterprise-and-open-source-comparison)

### 增量 / 变更检测
- [How to Update RAG Knowledge Base Without Rebuilding — Particula](https://particula.tech/blog/update-rag-knowledge-without-rebuilding)
- [Build RAG Systems with Real-Time Data Updates — Markaicode](https://markaicode.com/build-rag-systems-real-time-data-updates/)
- [Dynamic RAG Pipeline for Evolving Data — SearchCans](https://www.searchcans.com/blog/build-dynamic-rag-pipeline-evolving-information/)
- [Build a RAG Pipeline from Scratch in 2026 — kapa.ai](https://www.kapa.ai/blog/how-to-build-a-rag-pipeline-from-scratch-in-2026)
- [Production RAG in 2025 — Dextralabs](https://dextralabs.com/blog/production-rag-in-2025-evaluation-cicd-observability/)
- [RAG Data Ingestion Enterprise — Informatica](https://www.informatica.com/resources/articles/enterprise-rag-data-ingestion.html)
- [Build an unstructured data pipeline for RAG — Databricks](https://docs.databricks.com/aws/en/generative-ai/tutorials/ai-cookbook/quality-data-pipeline-rag)

### DLQ / 重试 / 幂等
- [Queue-Based Exponential Backoff: A Resilient Retry Pattern — DEV](https://dev.to/andreparis/queue-based-exponential-backoff-a-resilient-retry-pattern-for-distributed-systems-37f3)
- [Dead Letter Queues: The Complete Guide — Software Engineer's Notes 2025](https://swenotes.com/2025/09/25/dead-letter-queues-dlq-the-complete-developer-friendly-guide/)
- [Integration Patterns IV: Retries and DLQs — LittleHorse](https://littlehorse.io/blog/retries-and-dlq)
- [Kafka DLQ Best Practices — Superstream](https://www.superstream.ai/blog/kafka-dead-letter-queue)
- [How do you implement DLQs and handle poison messages — DesignGurus](https://www.designgurus.io/answers/detail/how-do-you-implement-dlqs-and-handle-poison-messages)
- [Designing Retry-Resilient Fare Pipelines With Event Handling — DZone](https://dzone.com/articles/retry-resilient-fare-pipelines-idempotent-events)
- [ETL Best Practices for Building Reliable Data Pipelines — OneUptime 2026](https://oneuptime.com/blog/post/2026-02-13-etl-best-practices/view)

### Lineage / Observability
- [OpenLineage Getting Started](https://openlineage.io/getting-started/)
- [OpenLineage GitHub](https://github.com/OpenLineage/OpenLineage)
- [Marquez Project — OpenLineage 参考实现](https://marquezproject.ai/)
- [Understanding data lineage — Datadog](https://www.datadoghq.com/blog/data-lineage/)
- [Data Pipeline Auditing and Lineage 2025 — Bix-Tech](https://bix-tech.com/data-pipeline-auditing-and-lineage-how-to-trace-every-record-prove-compliance-and-fix-issues-fast/)
- [Top Data Lineage Tools 2025 — Ataccama](https://www.ataccama.com/blog/top-data-lineage-tools-in-2025)
- [Open Source Python Data Lineage with OpenLineage and Hamilton — Medium](https://medium.com/@stefan.krawczyk/open-source-python-data-lineage-with-openlineage-and-hamilton-fe599c0459d6)
- [LLM Observability Tools 2025 — Iguazio](https://www.iguazio.com/blog/llm-observability-tools-in-2025/)
- [RAGOps: Operating and Managing RAG Pipelines (arXiv 2506.03401)](https://arxiv.org/html/2506.03401v1)
