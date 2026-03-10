# 单机版 Top‑Tier Gap Closure（RAG 知识库后端）设计

**日期：**2026-03-10  
**目标部署形态：**单机 / 单实例（Docker Compose / 一台服务器）  
**核心原则：**少引入新基础设施，把现有能力做成“可长期运行 + 可迭代”的产品闭环  

---

## 1) 背景与问题陈述

MimirQ 目前在 RAG runtime（rewrite / multi-query / KG 扩展 / hybrid retrieval / rerank / citations）层面已经接近“顶级 RAG”的形态；差距主要集中在“知识库平台化后端”的工程成熟度：

- 稀疏检索/过滤的规模化底座（避免进程内 BM25 成为天花板；在单机也要可持续跑）
- 任务编排/运维：吞吐可预测、失败可解释、重试/退避/幂等等工程化
- 评测门禁：检索/重排变更可度量、可回归、可上线
- 反馈→训练→上线：把 evidence/feedback/LTR 串成可操作闭环
- 同步语义工程化：从“可恢复的抓取”走向“可长期运行的数据镜像”

本设计聚焦 **单机/单实例**，避免为了“对标外观”引入 Elastic/OpenSearch 等重型组件；优先复用现有 Postgres、Redis/arq、Milvus 以及现有模块。

---

## 2) 约束与非目标（明确不做什么）

### 约束
- 单机/单实例优先：**允许**引入轻量组件（例如 Compose 内 Redis 已存在），**不鼓励**引入需要专门运维的搜索集群。
- 以“可用 + 可验证 + 可迭代”为第一目标：优先把能力做成闭环，而不是一次性追求全覆盖。

### 非目标（本波不做）
- 多副本/多机一致性（cache coherence、分布式锁、跨实例索引一致性）——只做“单机版版本感知 + 可手动失效”。
- 企业级安全/SSO/SCIM 深化（用户明确可弱化安全）。
- 大规模连接器矩阵扩展（Notion/Slack/SharePoint 等全面覆盖）——本波只做现有连接器的同步语义工程化与一致性提升。

---

## 3) 现状观察（基线）

### 3.1 已有能力（可复用的“底座”）
- **持久化 lexical 通道（Postgres FTS + pg_trgm）**：作为召回假阴性的兜底通道已经存在，并有索引/扩展的运行时 migration 说明。见 `docs/guides/lexical_fallback.md`、`app/rag/retriever.py`、`app/core/migrations.py`。
- **任务队列（Redis + arq）**：包含 worker heartbeat、幂等锁、租户/数据集并发信号量等。见 `app/tasks/*`。
- **检索栈模块化**：hybrid/vector/BM25/lexical/sparse 等通道在 `HybridRetriever` 内可组合，具备进一步“产品化”的空间。见 `app/rag/retriever.py`。
- **缓存 token 体系**：chat cache 已纳入 `embedding_space_hash` + `corpus_cache_token` 的 key 维度，为版本感知缓存打底。见 `app/services/chat_response_cache.py`、`app/services/corpus_cache_tokens.py`。

### 3.2 基线测试状态（需要先把“地基”修平）
在当前代码基线下，`pytest` 存在少量失败用例（与本波目标强相关），应作为最优先修复项（否则后续无法区分“新增回归”与“历史问题”）：

- ColBERT ANN persisted index 语义测试失败
- rerank budget 治理语义测试失败
- retrieval candidate cache 的 corpus 失效语义测试失败
- dataset_id filter 注入语义测试失败

（具体用例名称以 `pytest` 输出为准。）

---

## 4) 方案概述（单机版“顶级体验”路线）

### 4.1 稀疏检索：从“进程内 BM25”转向“Postgres lexical 主通道 + 可选 BM25”
在单机形态下，最务实的路线是把 **Postgres FTS/pg_trgm** 视为“可持续运行的 keyword 检索底座”，避免 BM25 进程内索引在语料增长后造成内存与冷启动成本爆炸。

BM25 仍保留为可选（对短语料/特定场景有效），但默认策略会更偏向 lexical DB。

### 4.2 Sparse（SPLADE 类）通道：持久化、版本指纹、可重建
把现有 sparse scaffolding 变为“可运维能力”：
- 索引落盘（基于 scope key + provider config + corpus fingerprint）
- 增量 upsert 与删除语义明确
- 提供 rebuild 入口（命令/任务队列），并可观测

### 4.3 任务编排：吞吐可预测、失败可解释
在单机也要把后台任务跑成“稳定系统”：
- 标准化 job wrapper 的输出（ok/reason/elapsed/progress）
- 重试退避、并发上限、幂等锁一致化
- `/observability` 里能看到可用的队列快照与 worker 心跳

### 4.4 缓存：版本感知 + 可手动失效（单机版）
把 retrieval/rerank/candidate cache 统一纳入相同的版本维度（`corpus_cache_token`、`embedding_space_hash`、必要时 `pipeline_hash`），并提供 dataset 级手动清缓存入口，避免“重建后仍命中旧缓存”的困扰。

### 4.5 评测门禁：让变更可度量
提供一条命令可跑 retrieval regression 并产出机器可读报告（JSON/Markdown），CI 先做 soft gate（报告可见），后续再 hard gate。

### 4.6 反馈→训练→上线：先做“可操作闭环”，不追求全自动
把 feedback/evidence 做成可导出的训练集，再把 LTR/重排模型训练、离线评测、线上指针切换、回滚做成一条清晰流程（支持人工触发即可）。

### 4.7 同步语义：统一 source identity + tombstone/reconcile 工具链
不扩展连接器数量，先让“已有连接器”具备长期镜像语义的关键工程点：
- 稳定 remote id / source_ref
- tombstone/软删除传播一致
- reconcile（dry-run diff + apply）两段式工具

---

## 5) 8 个 Issue 拆分（并行友好，单机优先）

> 说明：这里的 issue 是“工程落地包”，不是抽象议题。每个 issue 都必须有明确验收口径。

### Issue 1：检索（单机规模化）— lexical DB 提升为 keyword 主通道
**验收：**
- 支持配置把 `LEXICAL_DB` 作为 keyword 的主通道（FTS/trgm），BM25 变为可选或次级
- `query_debug.channels` 能明确归因（vector/bm25/lexical_db/sparse）
- dataset 作用域（dataset_id）与 metadata_filter 的注入语义一致（向量/稀疏/lexical 同步）

### Issue 2：Sparse（SPLADE 类）— 持久化、版本指纹、重建入口
**验收：**
- 支持落盘保存/加载 sparse 索引（scope key + corpus fingerprint）
- 支持增量 upsert 与删除后的向量清理（不需要全量重建）
- 提供 rebuild 入口（CLI/队列任务二选一即可），并有指标/日志

### Issue 3：任务编排/运维 — 吞吐可预测 + 失败可解释
**验收：**
- 关键 job（文档处理/connector run/重建索引/评测）输出结构统一，失败原因可聚合
- 并发上限/幂等锁策略一致化；取消/重试语义清晰
- observability endpoint 能看到队列/worker 心跳快照

### Issue 4：缓存/版本 — 版本感知 + dataset 级手动失效（单机版）
**验收：**
- retrieval candidate cache、rerank cache、chat cache 的 key 全部纳入统一版本维度
- 语料变化后 cache miss 语义正确（与测试用例一致）
- 提供 dataset 级缓存清理入口（API 或内部管理命令）

### Issue 5：连续评测/回归门禁 — retrieval regression 报告化
**验收：**
- 一条命令可跑 retrieval regression 并产出 JSON/Markdown 报告
- CI/本地都可复现；失败时能定位到通道/配置差异

### Issue 6：反馈数据产品化 — evidence/feedback → 训练集导出
**验收：**
- feedback/evidence 记录能稳定保存检索 trace/配置快照
- 支持按 dataset 导出训练集（JSONL/CSV 任一），字段文档清晰

### Issue 7：LTR/训练→上线（单机版手动流水线）— 训练、评测、发布、回滚
**依赖：**Issue 6  
**验收：**
- 提供从训练集训练→离线评测→更新线上指针→回滚的最小闭环
- 过程可重复（同输入得同输出，或至少记录 lineage）

### Issue 8：同步语义工程化（缩小版）— source identity + tombstone + reconcile
**验收：**
- 现有连接器产出的文档具备稳定 `source_id/source_ref` 语义
- reconcile 支持 dry-run diff 与 apply（软删除/禁用传播），并可观测

---

## 6) 建议执行顺序（单机最小闭环优先）

1) 修复基线失败测试（与本波目标强相关）  
2) Issue 1 / 4：检索通道策略 + 缓存版本语义（减少“看起来没生效”的体验问题）  
3) Issue 3：任务编排/可观测（让系统能稳定跑）  
4) Issue 5：评测门禁（让改动可度量）  
5) Issue 6 / 7：反馈→训练→上线闭环  
6) Issue 2 / 8：稀疏持久化与同步语义工具链（可并行推进，但要控制冲突面）  

---

## 7) 风险与降级策略

- **性能风险：**lexical DB 作为主通道可能带来 DB 压力 → 提供候选 overfetch 上限、按 dataset join pushdown、必要时可回退 BM25。
- **语义风险：**缓存 token 维度不统一导致“该 miss 却 hit” → 以测试用例作为硬约束，先修复现有失败用例再扩展。
- **运维风险：**任务重试/并发限制不当导致队列积压 → 先默认 conservative，提供可观测与配置项逐步调优。

